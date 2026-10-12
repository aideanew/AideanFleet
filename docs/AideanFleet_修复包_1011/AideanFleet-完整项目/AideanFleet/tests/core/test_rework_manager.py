"""这是什么：返工管理器单测（意见并入派工提示词 / 重派 / ESCALATED 人工放行=后继任务）。"""

from __future__ import annotations

import pytest

from fleet.core import db
from fleet.core import state_machine as sm
from fleet.manager import dispatcher, rework_manager
from fleet.manager.contracts import TaskPack

from .conftest import read_events
from .stubs import StubAdapter, make_task, ok_result, rework_route


def _task_to_reviewing(task_id: str) -> None:
    for target in ("ASSIGNED", "DOING", "SUBMITTED", "REVIEWING"):
        db.transition(task_id, target)


def test_handle_rework_merges_reason_into_detail(project):
    make_task(project, "T-1")
    _task_to_reviewing("T-1")
    db.bump_rework("T-1", remark="实现缺六节报告")
    assert db.get_task("T-1")["exec_status"] == "ASSIGNED"  # bump 后即 ASSIGNED

    handled = rework_manager.handle_rework("T-1", actor="tester")
    assert handled["state"] == "ASSIGNED" and handled["ok"]
    detail = db.get_task("T-1")["detail"]
    assert "【返工意见 · 第 1 轮】" in detail and "实现缺六节报告" in detail


def test_redispatch_full_chain(project, tmp_path):
    from fleet.manager import contracts

    adapter = StubAdapter([ok_result("第一次（不完整）"), ok_result("# 六节报告\n修好了")])
    contracts.register("stub", adapter)
    try:
        workspace = tmp_path / "ws"
        workspace.mkdir()
        task = make_task(project, "T-2", workspace=str(workspace))
        # 第一轮：完整派工到 SUBMITTED -> 审查 REWORK -> bump 回 ASSIGNED
        assert dispatcher.dispatch("T-2").state == "SUBMITTED"
        from fleet.manager import reviewer

        outcome = reviewer.review("T-2", actor="tester", router_fn=lambda *a, **k: rework_route())
        assert outcome.verdict == "REWORK"
        assert db.get_task("T-2")["exec_status"] == "ASSIGNED"

        # 重派：走完整派工流程，再次到 SUBMITTED；CORE-04 契约 v1.2 §13.5 后返工 prompt
        # 只发增量（retry_context + 修复指令），含模板句，不再重发全量 detail
        handled = rework_manager.redispatch("T-2", actor="tester")
        assert handled["state"] == "SUBMITTED"
        rework_prompt = adapter.calls[1]["prompt"]
        assert "这是第 1 轮返工，只需基于以下增量信息修复，不要重新调查全项目" in rework_prompt
        assert "review_verdict=REWORK" in rework_prompt  # 修复指令 = 返工意见原文
        assert "retry_context" in rework_prompt and "previous_diff" in rework_prompt
        assert "【MANAGER DISPATCH】" not in rework_prompt  # 不重发全量派工上下文
        assert db.get_task("T-2")["rework_count"] == 1
    finally:
        contracts.unregister("stub")


def test_handle_rework_escalated_is_noop(project):
    make_task(project, "T-3")
    _task_to_reviewing("T-3")
    for _ in range(4):
        db.bump_rework("T-3")
    assert db.get_task("T-3")["exec_status"] == "ESCALATED"
    handled = rework_manager.handle_rework("T-3", actor="tester")
    assert handled["state"] == "ESCALATED" and not handled["ok"]
    assert db.get_task("T-3")["exec_status"] == "ESCALATED"  # 原状态不动


def test_confirm_release_creates_successor(project):
    make_task(project, "T-4", dependencies=[])
    _task_to_reviewing("T-4")
    for _ in range(4):
        db.bump_rework("T-4", remark="一直做不好")
    result = rework_manager.confirm_release("T-4", actor="tester", note="人工复核：方案可行，放行")

    assert result["released"] and result["successor"] == "T-4-R1"
    successor = db.get_task("T-4-R1")
    assert successor is not None and successor["exec_status"] == "DRAFT"
    assert successor["rework_count"] == 4  # 返工计数延续
    assert "人工复核：方案可行" in successor["detail"]
    assert db.get_task("T-4")["exec_status"] == "ESCALATED"  # 原任务保持终态
    release_events = [row for row in read_events(project) if row["action"] == "task:escalated_release"]
    assert len(release_events) == 1 and release_events[0]["extra"]["successor"] == "T-4-R1"


def test_confirm_release_rejects_non_escalated(project):
    make_task(project, "T-5")
    with pytest.raises(ValueError):
        rework_manager.confirm_release("T-5", actor="tester")


def test_confirm_release_successor_id_increments(project):
    make_task(project, "T-6")
    _task_to_reviewing("T-6")
    for _ in range(4):
        db.bump_rework("T-6")
    first = rework_manager.confirm_release("T-6", actor="tester")
    # 后继任务同样反复失败升级后，编号自增
    _task_to_reviewing("T-6-R1")
    for _ in range(4):
        db.bump_rework("T-6-R1")
    second = rework_manager.confirm_release("T-6-R1", actor="tester")
    assert first["successor"] == "T-6-R1" and second["successor"] == "T-6-R1-R1"
