"""这是什么：工作包 §9.8 的十个核心场景（状态机/配置/事件/重试/门/e2e）。
怎么跑：python -m pytest tests/core/test_ten_scenarios.py -v
口径：全部用 tests/core/conftest.py 的隔离环境，不碰真实 data/。
"""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path

import pytest

import fleet.core.config as fleet_config
from fleet.core import db, events, plan
from fleet.core import state_machine as sm
from fleet.gates import verify
from fleet.manager import dispatcher, reviewer
from fleet.models import retry

from .stubs import StubAdapter, error_result, make_task, ok_result, pass_route

from .conftest import read_events


@pytest.fixture()
def stub_registry():
    from fleet.manager import contracts

    before = set(contracts.registered())
    yield contracts
    for name in set(contracts.registered()) - before:
        contracts.unregister(name)


# ---------------------------------------------------------------------------
# 场景 1：状态机合法迁移链（全链走通 + 每步有事件）
# ---------------------------------------------------------------------------


def test_scenario_1_legal_chain(project):
    task = make_task(project, "T-001")
    assert task["exec_status"] == "DRAFT"
    for target in ("ASSIGNED", "DOING", "SUBMITTED", "REVIEWING", "DONE"):
        db.transition_and_log("T-001", target, actor="tester", summary=f"-> {target}")
    assert db.get_task("T-001")["exec_status"] == "DONE"
    actions = [row["action"] for row in read_events(project)]
    assert actions == ["task:assigned", "task:doing", "task:submitted", "task:reviewing", "task:done"]
    # 终态不可再迁移
    with pytest.raises(sm.InvalidTransition):
        db.transition_and_log("T-001", "ASSIGNED", actor="tester")


# ---------------------------------------------------------------------------
# 场景 2：非法 DRAFT->DONE 必须抛 InvalidTransition 且不落库、不写事件
# ---------------------------------------------------------------------------


def test_scenario_2_illegal_transition(project):
    make_task(project, "T-002")
    before_rows = read_events(project)
    with pytest.raises(sm.InvalidTransition):
        db.transition_and_log("T-002", "DONE", actor="tester")
    assert db.get_task("T-002")["exec_status"] == "DRAFT"
    assert read_events(project) == before_rows  # 事件流零新增（契约 §2.2）


# ---------------------------------------------------------------------------
# 场景 3：第 4 次 REWORK 自动升级 ESCALATED
# ---------------------------------------------------------------------------


def test_scenario_3_fourth_rework_escalates(project):
    make_task(project, "T-003")
    for target in ("ASSIGNED", "DOING", "SUBMITTED", "REVIEWING"):
        db.transition("T-003", target)
    # 冻结口径：resolve_rework_target <=3 次回 ASSIGNED（可直接重派），>3 次升级 ESCALATED
    for round_no in range(1, 5):
        updated = db.bump_rework("T-003", remark=f"第 {round_no} 轮返工")
        expected = "ESCALATED" if round_no > sm.REWORK_ESCALATE_THRESHOLD else "ASSIGNED"
        assert updated["exec_status"] == expected
    assert db.get_task("T-003")["rework_count"] == 4
    assert sm.resolve_rework_target(3) == "ASSIGNED"
    assert sm.resolve_rework_target(4) == "ESCALATED"


# ---------------------------------------------------------------------------
# 场景 4：config 原子写"崩溃"（os.replace 失败）—— .env 原样、无半写内容
# ---------------------------------------------------------------------------


def test_scenario_4_config_atomic_crash(fleet_env):
    env_file = fleet_config.ensure_env_file()
    original = env_file.read_text(encoding="utf-8")

    real_replace = os.replace

    def crashing_replace(src, dst):
        if str(dst) == str(env_file):
            raise OSError("模拟断电：replace 失败")
        return real_replace(src, dst)

    os.replace = crashing_replace
    try:
        with pytest.raises(OSError):
            fleet_config.save("notify", {"on_task_start": True})
    finally:
        os.replace = real_replace

    assert env_file.read_text(encoding="utf-8") == original  # 原文件分毫未动
    tmp_leftover = env_file.parent / f".{env_file.name}.tmp"
    assert tmp_leftover.exists()  # 半成品只留在临时文件里

    # 恢复后重写成功
    result = fleet_config.save("notify", {"on_task_start": True})
    assert result["applied"] == {"on_task_start": True}
    assert fleet_config.load("notify")["on_task_start"] is True


# ---------------------------------------------------------------------------
# 场景 5：10 线程并发追加事件 —— seq 唯一且单调
# ---------------------------------------------------------------------------


def test_scenario_5_concurrent_event_appends(project):
    barrier = threading.Barrier(10)

    def worker(index: int) -> None:
        barrier.wait()
        events.append(actor=f"worker-{index}", action="chat", summary=f"并发 {index}", project=project)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(10)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    rows = read_events(project)
    assert len(rows) == 10
    seqs = sorted(int(row["seq"]) for row in rows)
    assert seqs == list(range(1, 11))  # 从 1 开始、无重复、无跳号


# ---------------------------------------------------------------------------
# 场景 6：软失败 429 重试 10 次后切换模型（launch:model_switch 事件）
# ---------------------------------------------------------------------------


def test_scenario_6_soft_retry_then_model_switch(project, stub_registry, monkeypatch):
    adapter = StubAdapter([error_result("429", "rate limited")] * 10 + [ok_result()])
    stub_registry.register("stub", adapter)
    monkeypatch.setattr(dispatcher, "_model_candidates", lambda role: [("m1", "id1"), ("m2", "id2")])
    policy = retry.policy(max_attempts=10, delay_seconds=0, sleep=lambda _s: None)

    make_task(project, "T-006")
    outcome = dispatcher.dispatch("T-006", policy=policy)

    assert outcome.ok and outcome.state == "SUBMITTED"
    assert len(adapter.calls) == 11  # m1 试满 10 次 + m2 一次成功
    assert adapter.calls[0]["model"] == "id1" and adapter.calls[-1]["model"] == "id2"
    switches = [row for row in read_events(project) if row["action"] == "launch:model_switch"]
    assert len(switches) == 1
    assert switches[0]["extra"]["from"] == "m1" and switches[0]["extra"]["to"] == "m2"


# ---------------------------------------------------------------------------
# 场景 7：硬失败 401 只试 1 次立刻换模型，绝不空耗 10 次
# ---------------------------------------------------------------------------


def test_scenario_7_hard_fail_no_retry(project, stub_registry, monkeypatch):
    adapter = StubAdapter([error_result("401", "unauthorized"), ok_result()])
    stub_registry.register("stub", adapter)
    monkeypatch.setattr(dispatcher, "_model_candidates", lambda role: [("m1", "id1"), ("m2", "id2")])
    policy = retry.policy(max_attempts=10, delay_seconds=0, sleep=lambda _s: None)

    make_task(project, "T-007")
    outcome = dispatcher.dispatch("T-007", policy=policy)

    assert outcome.ok and outcome.state == "SUBMITTED"
    models_used = [call["model"] for call in adapter.calls]
    assert models_used == ["id1", "id2"]  # 401 在 m1 上只发生一次
    switches = [row for row in read_events(project) if row["action"] == "launch:model_switch"]
    assert len(switches) == 1 and switches[0]["extra"]["attempts"] == 1


# ---------------------------------------------------------------------------
# 场景 8：机器门失败 -> REWORK，全程不调 LLM
# ---------------------------------------------------------------------------


def test_scenario_8_gate_fail_rework_without_llm(project, stub_registry, tmp_path):
    adapter = StubAdapter([ok_result("实现做完了（但其实没做完）")])
    stub_registry.register("stub", adapter)
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    make_task(project, "T-008", verify_cmd='python -c "import sys; sys.exit(2)"', workspace=str(workspace))

    assert dispatcher.dispatch("T-008").state == "SUBMITTED"

    def forbidden_router(*args, **kwargs):
        raise AssertionError("门失败时绝不允许调用审查 LLM")

    outcome = reviewer.review("T-008", actor="tester", router_fn=forbidden_router)

    assert outcome.verdict == "REWORK"
    # 冻结口径：<=3 次返工落库为 ASSIGNED（可立即重派），rework_count +1
    assert outcome.state == "ASSIGNED"
    assert outcome.detail.startswith("machine_gate_failed")
    assert outcome.rework_count == 1
    actions = [row["action"] for row in read_events(project)]
    assert "gate:fail" in actions and "task:rework" in actions
    assert "gate:pass" not in actions


# ---------------------------------------------------------------------------
# 场景 9：plan.json 并发原子写 —— 任何时刻都是完整 JSON，绝不出现半写文件
# ---------------------------------------------------------------------------


def test_scenario_9_plan_concurrent_atomic_write(project):
    plan_file = plan.plan_file(project)
    barrier = threading.Barrier(10)

    def worker(index: int) -> None:
        barrier.wait()
        plan.save(project, {"project": project, "writer": f"w-{index}", plan.STAGE_KEY: []})

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(10)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    raw = plan_file.read_text(encoding="utf-8")
    payload = json.loads(raw)  # 能解析 = 没有半写
    assert payload["project"] == project
    assert payload["writer"].startswith("w-")  # 是某一个写者的完整版本


# ---------------------------------------------------------------------------
# 场景 10：MockExecutor 全链 DRAFT->DONE，事件恰好 8 条（契约 §9.5-3 事件链）
# ---------------------------------------------------------------------------


EXPECTED_CHAIN = [
    "task:created",
    "task:assigned",
    "task:doing",
    "task:submitted",
    "gate:pass",
    "task:reviewing",
    "task:review_pass",
    "task:done",
]


def test_scenario_10_mock_executor_eight_events(project, stub_registry, tmp_path):
    from fleet.manager.contracts import TaskPack

    adapter = StubAdapter([ok_result("# 六节报告\n## 一、目标\n\n全部完成。")])
    stub_registry.register("stub", adapter)

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "deliver.txt").write_text("done", encoding="utf-8")

    pack = TaskPack(
        id="T-010", title="全链演练", detail="从创建到 DONE", verify_cmd='python -c "print(1)"',
        assignee="worker-a", reviewer="reviewer-1", workspace=str(workspace), forbidden_files=".env",
        project_id=project,
    )
    dispatcher.create_task(pack, project_id=project, stage="阶段0", subtask="全链演练")

    assert dispatcher.dispatch("T-010").state == "SUBMITTED"
    outcome = reviewer.review("T-010", actor="tester", router_fn=lambda *a, **k: pass_route())
    assert outcome.verdict == "PASS" and outcome.state == "DONE"

    chain = [row["action"] for row in read_events(project)]
    # CORE-04 契约 v1.2 后事件流还含 prompt:assembled/budget:check/model:call 等计量事件，
    # 本场景断言的是八事件任务链本身，故按动作码过滤后比对（顺序与唯一性不变）。
    chain = [action for action in chain if action in set(EXPECTED_CHAIN)]
    assert chain == EXPECTED_CHAIN  # 恰好 8 条、顺序一致
    assert db.get_task("T-010")["exec_status"] == "DONE"
