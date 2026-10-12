"""P3：需求澄清/冻结内核方法测试（draft → clarify → freeze 生命周期）。

先于 API/契约层落地的内核行为守门：
- create_goal_draft：state='draft'、不建 todo、事件 goal:created；
- append_goal_requirements：追加合并、可多次、frozen 拒绝（GoalAlreadyFrozen）；
- freeze_goal：短需求拒绝（RequirementsNotReady）、锁定 + 建 plan todo、重复冻结拒绝、事件顺序；
- get_goal：不存在 → KeyError。
"""

from __future__ import annotations

import pytest

from fleet.kernel.kernel import (
    FREEZE_MIN_REQUIREMENTS,
    GoalAlreadyFrozen,
    Kernel,
    RequirementsNotReady,
)
from fleet.kernel.store import connect


@pytest.fixture()
def k(tmp_path):
    return Kernel(tmp_path / "k.db")


def _todo_count(k: Kernel, goal_id: str) -> int:
    with connect(k.db_path) as conn:
        return conn.execute(
            "SELECT COUNT(*) AS n FROM todos WHERE goal_id=?", (goal_id,)
        ).fetchone()["n"]


def _event_kinds(k: Kernel) -> list[str]:
    with connect(k.db_path) as conn:
        return [r["kind"] for r in conn.execute("SELECT kind FROM events ORDER BY seq")]


def test_create_goal_draft_state_and_no_todo(k):
    gid = k.create_goal_draft("做网站", "先做营销落地页，再接支付")
    goal = k.get_goal(gid)
    assert goal["requirements_state"] == "draft"
    assert goal["requirements"] == "先做营销落地页，再接支付"
    assert goal["status"] == "active"
    assert _todo_count(k, gid) == 0
    assert _event_kinds(k) == ["goal:created"]


def test_create_goal_with_plan_defaults_to_frozen(k):
    """direct 金线不变：create_goal_with_plan 建的 goal 即 frozen。"""
    gid, tid = k.create_goal_with_plan("做网站", "营销落地页", "")
    goal = k.get_goal(gid)
    assert goal["requirements_state"] == "frozen"
    assert k.get_todo(tid)["kind"] == "plan"


def test_get_goal_missing_raises_keyerror(k):
    with pytest.raises(KeyError):
        k.get_goal("G-nope")


def test_append_requirements_merges_and_repeats(k):
    gid = k.create_goal_draft("做网站", "先做营销落地页")
    goal = k.append_goal_requirements(gid, "加上暗色模式")
    assert "先做营销落地页" in goal["requirements"]
    assert "加上暗色模式" in goal["requirements"]
    assert goal["requirements_state"] == "draft"
    goal = k.append_goal_requirements(gid, "支持多语言")
    assert "支持多语言" in goal["requirements"]
    assert goal["requirements"].count("\n\n") == 2  # 两次追加两段
    assert _event_kinds(k) == ["goal:created", "goal:clarified", "goal:clarified"]


def test_append_to_first_empty_requirements(k):
    """空需求草稿：首次追加直接作为全文（不产生前导空行）。"""
    gid = k.create_goal_draft("做网站", "")
    goal = k.append_goal_requirements(gid, "需求一句话描述")
    assert goal["requirements"] == "需求一句话描述"


def test_append_after_frozen_rejected(k):
    gid = k.create_goal_draft("做网站", "先做营销落地页，再接支付")
    k.freeze_goal(gid)
    with pytest.raises(GoalAlreadyFrozen):
        k.append_goal_requirements(gid, "再加")


def test_freeze_short_requirements_rejected(k):
    gid = k.create_goal_draft("做网站", "太短")
    with pytest.raises(RequirementsNotReady):
        k.freeze_goal(gid)
    goal = k.get_goal(gid)
    assert goal["requirements_state"] == "draft"  # 状态未变
    assert _todo_count(k, gid) == 0  # 未建 todo


def test_freeze_strips_whitespace_before_threshold(k):
    """剥离空白后恰好达标 → 允许冻结。"""
    body = "需" * FREEZE_MIN_REQUIREMENTS
    gid = k.create_goal_draft("做网站", f"  \n\t{body}\n  ")
    _, tid, goal = k.freeze_goal(gid)
    assert goal["requirements_state"] == "frozen"
    assert k.get_todo(tid)["kind"] == "plan"


def test_freeze_locks_and_creates_plan_todo(k):
    requirements = "做一个营销落地页，包含定价区与联系表单"
    gid = k.create_goal_draft("做网站", requirements, "E:/ws/demo")
    out_gid, tid, goal = k.freeze_goal(gid)
    assert out_gid == gid
    assert goal["requirements_state"] == "frozen"
    todo = k.get_todo(tid)
    assert todo["goal_id"] == gid
    assert todo["kind"] == "plan"
    assert todo["status"] == "open"
    assert todo["packet"] == requirements
    assert todo["workspace"] == "E:/ws/demo"
    assert _event_kinds(k) == ["goal:created", "goal:frozen", "todo:created"]


def test_refreeze_rejected_and_no_second_todo(k):
    gid = k.create_goal_draft("做网站", "做一个营销落地页，包含定价与联系表单")
    _, tid, _ = k.freeze_goal(gid)
    with pytest.raises(GoalAlreadyFrozen):
        k.freeze_goal(gid)
    assert _todo_count(k, gid) == 1  # 只有首个 plan todo


def test_freeze_missing_goal_raises_keyerror(k):
    with pytest.raises(KeyError):
        k.freeze_goal("G-nope")
