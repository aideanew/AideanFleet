# 断点恢复演练（CORE-02）：模拟执行进程在 DOING/ASSIGNED 阶段被 kill 后重启，
# 验证 dispatcher 不重复派工（DOING 原样返回）、ASSIGNED 可续跑至完成且事件链不重复。
import pytest

from fleet.core import db, events
from fleet.manager import contracts, dispatcher

from .stubs import StubAdapter, make_task, ok_result, pass_route


def _simulate_restart() -> None:
    """模拟进程重启：进程内缓存全部失效，只有 SQLite 里的状态还在。"""
    events._CACHE["size"] = -1
    events._CACHE["seq"] = 0
    from fleet.core import config as fleet_config

    fleet_config._CACHE.mtime_ns = None
    fleet_config._CACHE.values = {}
    fleet_config._CACHE.section_of = {}


def _actions(project_id):
    return [row["action"] for row in events.read(project=project_id)]


def test_doing_kill_restart_no_duplicate_dispatch(project, tmp_path):
    """DOING 中途 kill -> 重启后再 dispatch：不重复派工、事件只有一次 task:doing。"""
    from fleet.core import state_machine as sm

    adapter = StubAdapter([ok_result("不该被调用")])
    contracts.register("stub", adapter)
    try:
        workspace = tmp_path / "ws"
        workspace.mkdir()
        make_task(project, "T-K1", workspace=str(workspace))
        # 模拟上一轮进程：进入 DOING 后立刻被 kill（适配器还没跑或跑了一半）
        db.transition_and_log("T-K1", "ASSIGNED", actor="manager", summary="已派工")
        db.transition_and_log("T-K1", "DOING", actor="manager", summary="进入执行")
        assert adapter.calls == []

        # 进程重启：缓存失效，重新调用派工
        _simulate_restart()
        outcome = dispatcher.dispatch("T-K1")
        assert outcome.ok is True
        assert outcome.state == "DOING"
        assert "already_doing" in outcome.detail
        # 关键断言：绝不重复执行
        assert adapter.calls == []
        assert _actions(project).count("task:doing") == 1
        assert db.get_task("T-K1")["exec_status"] == "DOING"
    finally:
        contracts.unregister("stub")


def test_assigned_crash_resume_completes_chain(project, tmp_path):
    """ASSIGNED 阶段 crash -> 重启后 dispatch 续跑：一路到 SUBMITTED，事件不重复。"""
    adapter = StubAdapter([ok_result("# 六节报告\n续跑完成")])
    contracts.register("stub", adapter)
    try:
        workspace = tmp_path / "ws"
        workspace.mkdir()
        make_task(project, "T-K2", workspace=str(workspace))
        # 模拟刚派工就 crash（留下 task:assigned 事件，与真实运行一致）
        db.transition_and_log("T-K2", "ASSIGNED", actor="manager", summary="已派工")
        _simulate_restart()

        outcome = dispatcher.dispatch("T-K2")
        assert outcome.state == "SUBMITTED"
        actions = _actions(project)
        # 每个动作恰好一次：没有因续跑而产生重复事件
        for action in ("task:assigned", "task:doing", "task:submitted"):
            assert actions.count(action) == 1
    finally:
        contracts.unregister("stub")


def test_assigned_crash_resume_run_to_completion(project, tmp_path):
    """ASSIGNED crash -> run_to_completion 续跑全链：审查通过直达 DONE。"""
    adapter = StubAdapter([ok_result("# 六节报告\n一次到位")])
    contracts.register("stub", adapter)
    try:
        workspace = tmp_path / "ws"
        workspace.mkdir()
        make_task(project, "T-K3", workspace=str(workspace))
        db.transition_and_log("T-K3", "ASSIGNED", actor="manager", summary="已派工")
        _simulate_restart()

        from fleet.models import retry

        result = dispatcher.run_to_completion(
            "T-K3",
            actor="tester",
            router_fn=lambda *a, **k: pass_route(),
            policy=retry.policy(delay_seconds=0),
        )
        assert result["state"] == "DONE"
        assert result["ok"] is True
        assert adapter.total_calls == 1  # 全程只执行了一次
        actions = _actions(project)
        assert actions.count("task:doing") == 1
        # CORE-04 契约 v1.2：DONE 后会自动提炼项目记忆（memory:recorded），终局任务事件仍是 task:done
        assert actions[-1] in ("task:done", "memory:recorded")
        assert "task:done" in actions
    finally:
        contracts.unregister("stub")


def test_doing_stuck_task_escalates_via_manual_release(project, tmp_path):
    """DOING 卡死任务：确认接口走 BLOCKED 释放通道，回到派工轨道。"""
    adapter = StubAdapter([ok_result("释放后再跑")])
    contracts.register("stub", adapter)
    try:
        workspace = tmp_path / "ws"
        workspace.mkdir()
        make_task(project, "T-K4", workspace=str(workspace))
        db.transition_and_log("T-K4", "ASSIGNED", actor="manager", summary="已派工")
        db.transition_and_log("T-K4", "DOING", actor="manager", summary="进入执行")  # 卡死在这里

        # 直接 DOING->ASSIGNED 非法，须走 BLOCKED 中转
        with pytest.raises(Exception):
            db.transition("T-K4", "ASSIGNED")

        # 人工释放：DOING -> BLOCKED -> ASSIGNED（action=task:blocked_release）后重新派工
        db.transition_and_log(
            "T-K4", "BLOCKED", actor="human", summary="人工卡死释放", blocked_reason="stuck_doing"
        )
        db.transition_and_log(
            "T-K4", "ASSIGNED", actor="human", action="task:blocked_release", summary="人工确认重新派工"
        )
        outcome = dispatcher.dispatch("T-K4")
        assert outcome.state == "SUBMITTED"
        assert adapter.total_calls == 1
    finally:
        contracts.unregister("stub")
