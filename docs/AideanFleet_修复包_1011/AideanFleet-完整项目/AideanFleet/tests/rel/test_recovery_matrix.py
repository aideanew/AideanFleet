"""崩溃恢复四态矩阵（REL-01 §9.1）：ASSIGNED/DOING/SUBMITTED/REVIEWING 各态注入 kill ->
重启 -> recovery.resume 续跑。断言：状态正确推进、事件不重复、不重复派工、REVIEWING 可续审。"""

from __future__ import annotations

import pytest

from fleet.core import db, events
from fleet.manager import contracts, dispatcher
from fleet.rel import recovery

from tests.core.stubs import StubAdapter, make_task, ok_result, pass_route
from tests.rel.conftest import read_events, simulate_restart


def _actions(project_id):
    return [row["action"] for row in read_events(project_id)]


def _state_to(task_id, states):
    for state in states:
        db.transition_and_log(task_id, state, actor="tester", summary=f"演练推进到 {state}")


def test_matrix_assigned_kill_resume_dispatches_once(project, tmp_path):
    """ASSIGNED kill -> resume：续跑到 SUBMITTED，适配器只执行一次，事件链不重复。"""
    adapter = StubAdapter([ok_result("# 六节报告\nASSIGNED 续跑完成")])
    contracts.register("stub", adapter)
    try:
        workspace = tmp_path / "ws"
        workspace.mkdir()
        make_task(project, "T-R1", workspace=str(workspace))
        _state_to("T-R1", ["ASSIGNED"])
        simulate_restart()

        result = recovery.resume("T-R1")
        assert result["ok"] is True and result["via"] == "dispatch"
        assert result["state"] == "SUBMITTED"
        assert adapter.total_calls == 1
        actions = _actions(project)
        for action in ("task:assigned", "task:doing", "task:submitted"):
            assert actions.count(action) == 1
    finally:
        contracts.unregister("stub")


def test_matrix_doing_kill_resume_never_redispatches(project, tmp_path):
    """DOING kill -> resume：原样返回 already_doing，绝不重复派工（执行体结果不可知）。"""
    adapter = StubAdapter([ok_result("不该被调用")])
    contracts.register("stub", adapter)
    try:
        workspace = tmp_path / "ws"
        workspace.mkdir()
        make_task(project, "T-R2", workspace=str(workspace))
        _state_to("T-R2", ["ASSIGNED", "DOING"])
        assert adapter.calls == []
        simulate_restart()

        result = recovery.resume("T-R2")
        assert result["state"] == "DOING" and "already_doing" in result["detail"]
        assert adapter.calls == []  # 关键：零重复执行
        assert _actions(project).count("task:doing") == 1
        assert db.get_task("T-R2")["exec_status"] == "DOING"
    finally:
        contracts.unregister("stub")


def test_matrix_submitted_kill_resume_review_without_redispatch(project, tmp_path):
    """SUBMITTED kill -> resume：直接续审（不再派工），审查通过到 DONE。"""
    adapter = StubAdapter([ok_result("# 六节报告\n先跑完再 kill")])
    contracts.register("stub", adapter)
    try:
        workspace = tmp_path / "ws"
        workspace.mkdir()
        make_task(project, "T-R3", workspace=str(workspace))
        assert dispatcher.dispatch("T-R3").state == "SUBMITTED"  # 真实执行一轮
        simulate_restart()

        result = recovery.resume("T-R3", router_fn=lambda *a, **k: pass_route())
        assert result["via"] == "review"
        assert result["state"] == "DONE" and result["verdict"] == "PASS"
        assert adapter.total_calls == 1  # 续审没有重新派工
        actions = _actions(project)
        assert actions.count("task:doing") == 1
        assert actions.count("task:submitted") == 1
        assert actions.count("task:reviewing") == 1
    finally:
        contracts.unregister("stub")


def test_matrix_reviewing_kill_resume_can_continue_review(project, tmp_path):
    """REVIEWING kill -> resume：可续审（review 接受 REVIEWING 态），不再产生第二个 task:reviewing。"""
    adapter = StubAdapter([ok_result("# 六节报告\n先跑完再 kill")])
    contracts.register("stub", adapter)
    try:
        workspace = tmp_path / "ws"
        workspace.mkdir()
        make_task(project, "T-R4", workspace=str(workspace))
        assert dispatcher.dispatch("T-R4").state == "SUBMITTED"  # 真实执行一轮
        db.transition_and_log("T-R4", "REVIEWING", actor="tester", summary="审查进程中 kill")  # 模拟审查器崩溃后的残留态
        simulate_restart()

        result = recovery.resume("T-R4", router_fn=lambda *a, **k: pass_route())
        assert result["via"] == "review"
        assert result["state"] == "DONE" and result["verdict"] == "PASS"
        actions = _actions(project)
        assert actions.count("task:reviewing") == 1  # 没有重复进入审查
        assert actions.count("task:doing") == 1
        assert actions[-1] in ("task:done", "memory:recorded")
    finally:
        contracts.unregister("stub")


def test_recover_all_handles_mixed_states_and_skips_failures(project, tmp_path):
    """recover_all：混合四态批量恢复；单条失败（DOING 已 BLOCKED 之类）不拖垮整批。"""
    adapter = StubAdapter([ok_result("# 六节报告\n批量")])
    contracts.register("stub", adapter)
    try:
        for tid, states in (
            ("T-B1", ["ASSIGNED"]),
            ("T-B2", ["ASSIGNED", "DOING"]),
        ):
            workspace = tmp_path / f"ws-{tid}"
            workspace.mkdir()
            make_task(project, tid, workspace=str(workspace))
            _state_to(tid, states)
        # T-B3/T-B4 用真实 dispatch 推到 SUBMITTED/REVIEWING（审查进程中 kill 的两种残留态）
        for tid in ("T-B3", "T-B4"):
            workspace = tmp_path / f"ws-{tid}"
            workspace.mkdir()
            make_task(project, tid, workspace=str(workspace))
            assert dispatcher.dispatch(tid).state == "SUBMITTED"
        db.transition_and_log("T-B4", "REVIEWING", actor="tester", summary="审查进程中 kill")
        calls_before = adapter.total_calls  # T-B3/T-B4 派工已执行 2 次
        assert calls_before == 2
        simulate_restart()

        summary = recovery.recover_all(project, router_fn=lambda *a, **k: pass_route())
        assert summary["total"] == 4
        by_id = {item["task_id"]: item for item in summary["recovered"]}
        assert by_id["T-B1"]["state"] == "SUBMITTED"
        assert by_id["T-B2"]["state"] == "DOING"  # already_doing，不重复派工
        assert by_id["T-B3"]["state"] == "DONE"
        assert by_id["T-B4"]["state"] == "DONE"
        assert adapter.total_calls == calls_before + 1  # 批量恢复期间只有 T-B1 真实派工，续审零重复派工
    finally:
        contracts.unregister("stub")


def test_resume_rejects_state_outside_recoverable_set(project):
    """DRAFT（未派工）不在可恢复集合内，拒绝并报错；scan 也不应把它列为待恢复。"""
    make_task(project, "T-X1")  # DRAFT
    with pytest.raises(ValueError, match="不在可恢复集合"):
        recovery.resume("T-X1")
    assert not any(item["task_id"] == "T-X1" for item in recovery.scan(project))
