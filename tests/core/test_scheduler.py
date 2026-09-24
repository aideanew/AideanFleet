"""这是什么：调度器单测（schedule_once / run_loop 步进与模式切换 / ControlBus）。"""

from __future__ import annotations

import asyncio

import pytest

from fleet.core import db, events
from fleet.manager import scheduler

from .conftest import read_events
from .stubs import StubAdapter, make_task, ok_result


@pytest.fixture()
def stub_adapter():
    from fleet.manager import contracts

    adapter = StubAdapter([ok_result("# 六节报告\n完成")])
    contracts.register("stub", adapter)
    yield adapter
    contracts.unregister("stub")


def test_schedule_once_collects_drafts_and_dispatches(project, stub_adapter):
    make_task(project, "T-1")
    outcomes = scheduler.schedule_once(project)
    assert [o["state"] for o in outcomes] == ["SUBMITTED"]
    assert db.get_task("T-1")["exec_status"] == "SUBMITTED"
    actions = [row["action"] for row in read_events(project)]
    assert "task:assigned" in actions and "task:doing" in actions and "task:submitted" in actions


def test_control_bus_mode_switch_and_confirm(project):
    bus = scheduler.ControlBus("auto")
    bus.set_mode("step")
    assert bus.mode == "step"
    assert [row["action"] for row in events.read()] == ["mode:changed"]

    bus.confirm(task_id="T-9", note="继续")
    assert bus.pending_confirms() == 1
    assert bus.take_confirm()["task_id"] == "T-9"
    assert bus.take_confirm() is None

    with pytest.raises(ValueError):
        bus.set_mode("turbo")


def test_run_loop_step_mode_waits_for_confirm(project, stub_adapter):
    make_task(project, "T-1")
    bus = scheduler.ControlBus("step")

    async def wait_state(task_id, wanted, timeout=3.0):
        deadline = asyncio.get_running_loop().time() + timeout
        while asyncio.get_running_loop().time() < deadline:
            if db.get_task(task_id)["exec_status"] == wanted:
                return True
            await asyncio.sleep(0.02)
        return db.get_task(task_id)["exec_status"] == wanted

    async def drive():
        task = asyncio.create_task(
            scheduler.run_loop(bus, project_id=project, interval=0.01, max_ticks=200)
        )
        await asyncio.sleep(0.1)
        assert db.get_task("T-1")["exec_status"] == "DRAFT"  # 没确认：不收编不派工
        bus.confirm(note="放行")
        reached = await wait_state("T-1", "SUBMITTED")
        state = db.get_task("T-1")["exec_status"]
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        assert reached, "确认后 3 秒内未到达 SUBMITTED"
        return state

    assert asyncio.run(drive()) == "SUBMITTED"


def test_run_loop_auto_mode_dispatches_without_confirm(project, stub_adapter):
    make_task(project, "T-1")
    bus = scheduler.ControlBus("auto")

    async def drive():
        await scheduler.run_loop(bus, project_id=project, interval=0.01, max_ticks=1)
        return db.get_task("T-1")["exec_status"]

    assert asyncio.run(drive()) == "SUBMITTED"


def test_run_loop_step_mode_one_task_per_confirm(project, stub_adapter):
    make_task(project, "T-1")
    make_task(project, "T-2")
    bus = scheduler.ControlBus("step")

    async def wait_until(predicate, timeout=3.0):
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        while loop.time() < deadline:
            if predicate():
                return True
            await asyncio.sleep(0.02)
        return False

    async def drive():
        task = asyncio.create_task(
            scheduler.run_loop(bus, project_id=project, interval=0.01, max_ticks=300)
        )
        await asyncio.sleep(0.05)
        bus.confirm(note="第一个")
        await wait_until(lambda: db.get_task("T-1")["exec_status"] == "SUBMITTED")
        after_first = {tid: db.get_task(tid)["exec_status"] for tid in ("T-1", "T-2")}
        bus.confirm(note="第二个")
        # 新契约：step 模式一次 confirm 只走一步——第二个 confirm 优先评审 SUBMITTED（机器门），
        # T-1 被推进离开 SUBMITTED（stub 回执无六节报告 → 评审推进），T-2 尚未派工。
        await wait_until(lambda: db.get_task("T-1")["exec_status"] != "SUBMITTED")
        after_second = {tid: db.get_task(tid)["exec_status"] for tid in ("T-1", "T-2")}
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        return after_first, after_second

    after_first, after_second = asyncio.run(drive())
    submitted_first = [tid for tid, state in after_first.items() if state == "SUBMITTED"]
    assert len(submitted_first) == 1  # 一次确认只收编+派一个
    assert after_second["T-1"] != "SUBMITTED"  # 第二个确认走了机器门评审而非派新任务
    assert after_second["T-2"] == "ASSIGNED"  # T-2 仍在待派队列


# ---------------------------------------------------------------------------
# 派工异常可见性：只记内存 outcome 会让任务长期停在 DOING，控制台也看不到原因
# ---------------------------------------------------------------------------


def test_normal_dispatch_not_marked_blocked(project, stub_adapter):
    """正常派工不受影响：不产生 task:blocked 事件。"""
    make_task(project, "T-9")
    outcomes = scheduler.schedule_once(project)
    assert outcomes[0]["ok"] is True
    task = db.get_task("T-9")
    assert task["exec_status"] == "SUBMITTED"
    assert task.get("blocked_reason") in (None, "")
    assert "task:blocked" not in [row["action"] for row in read_events(project)]


def test_dispatch_exception_after_doing_persists_blocked(project, monkeypatch):
    """派工进入 DOING 后抛异常必须落 BLOCKED（真实场景：写证据/落 SUBMITTED 失败）。"""
    make_task(project, "T-9")

    def dispatch_then_fail(task_id, **kwargs):
        db.transition_and_log(task_id, "DOING", actor="scheduler", summary="进入执行")
        raise OSError("证据目录不可写")

    monkeypatch.setattr(scheduler.dispatcher, "dispatch", dispatch_then_fail)

    outcomes = scheduler.schedule_once(project)

    assert len(outcomes) == 1
    assert outcomes[0]["taskId"] == "T-9"
    assert outcomes[0]["state"] == "ERROR"
    assert outcomes[0]["ok"] is False
    assert "dispatch_failed" in outcomes[0]["detail"]
    task = db.get_task("T-9")
    assert task["exec_status"] == "BLOCKED"
    assert task["blocked_reason"].startswith("dispatch_exception:")
    assert "task:blocked" in [row["action"] for row in read_events(project)]


def test_dispatch_exception_in_step_mode_does_not_escape(project, monkeypatch):
    """step 模式（once=True）此前完全没有异常保护：抛异常会静默杀死 run_loop 线程。"""
    make_task(project, "T-9")

    def boom(task_id, **kwargs):
        db.transition_and_log(task_id, "DOING", actor="scheduler", summary="进入执行")
        raise RuntimeError("step 模式内部故障")

    monkeypatch.setattr(scheduler.dispatcher, "dispatch", boom)

    outcomes = scheduler.schedule_once(project, once=True)

    assert outcomes[0]["state"] == "ERROR"
    assert "dispatch_failed" in outcomes[0]["detail"]
    assert db.get_task("T-9")["exec_status"] == "BLOCKED"


def test_run_loop_step_mode_survives_dispatch_exception(project, monkeypatch, stub_adapter):
    """一轮派工抛异常后 run_loop 必须继续跑下一拍，否则后续任务永久无人推进。"""
    make_task(project, "T-9")
    make_task(project, "T-10")
    real_dispatch = scheduler.dispatcher.dispatch

    # DEBUG: track calls
    import sys as _sys
    _dispatch_calls = []
    _persist_calls = []

    # Wrap _persist_dispatch_failure for debugging
    _orig_persist = scheduler._persist_dispatch_failure
    def _debug_persist(task_id, exc, *, db_file=None):
        try:
            t = db.get_task(task_id, db_file=db_file)
            state_before = t["exec_status"] if t else "None"
        except Exception as e:
            state_before = f"get_task_error: {e}"
        _persist_calls.append((task_id, state_before, str(exc)))
        _orig_persist(task_id, exc, db_file=db_file)
        try:
            t2 = db.get_task(task_id, db_file=db_file)
            state_after = t2["exec_status"] if t2 else "None"
        except Exception as e:
            state_after = f"get_task_error: {e}"
        _persist_calls[-1] = (task_id, state_before, str(exc), state_after)
    monkeypatch.setattr(scheduler, "_persist_dispatch_failure", _debug_persist)

    def boom_for_first(task_id, **kwargs):
        _dispatch_calls.append(task_id)
        if task_id == "T-9":
            t_before = db.get_task(task_id)
            _sys.stderr.write(f"DEBUG boom T-9: state_before={t_before['exec_status']}\n")
            db.transition_and_log(task_id, "DOING", actor="scheduler", summary="进入执行")
            t_after = db.get_task(task_id)
            _sys.stderr.write(f"DEBUG boom T-9: state_after_DOING={t_after['exec_status']}\n")
            raise RuntimeError("第一拍故障")
        _sys.stderr.write(f"DEBUG dispatch {task_id}\n")
        return real_dispatch(task_id, **kwargs)

    monkeypatch.setattr(scheduler.dispatcher, "dispatch", boom_for_first)

    async def drive():
        bus = scheduler.ControlBus("step")
        task = asyncio.create_task(
            scheduler.run_loop(bus, project_id=project, interval=0.01, max_ticks=6)
        )
        for _ in range(5):  # 每拍一次确认；循环若死在第一拍，T-10 会永远停在 ASSIGNED
            bus.confirm(note="放行")
            await asyncio.sleep(0.05)
        await task
        return {tid: db.get_task(tid)["exec_status"] for tid in ("T-9", "T-10")}

    states = asyncio.run(drive())
    _sys.stderr.write(f"DEBUG dispatch_calls={_dispatch_calls}\n")
    _sys.stderr.write(f"DEBUG persist_calls={_persist_calls}\n")
    _sys.stderr.write(f"DEBUG final_states={states}\n")
    assert states["T-9"] == "BLOCKED"
    assert states["T-10"] != "ASSIGNED", "run_loop 在第一拍异常后停止运转，T-10 未再被派工"


def test_persist_failure_keeps_state_without_blocked_edge(project):
    """REWORK 等无 BLOCKED 出边的状态保持原样，绝不强行落库（状态机契约已冻结）。"""
    make_task(project, "T-9")
    for state in ("ASSIGNED", "DOING", "SUBMITTED", "REVIEWING", "REWORK"):
        db.transition("T-9", state)
    before = list(read_events(project))

    scheduler._persist_dispatch_failure("T-9", RuntimeError("boom"))

    assert db.get_task("T-9")["exec_status"] == "REWORK"
    assert list(read_events(project)) == before


def test_persist_failure_is_silent(project, monkeypatch):
    """落库失败必须静默——不能反过来杀掉调度循环。"""
    make_task(project, "T-9")
    monkeypatch.setattr(db, "get_task", lambda *a, **k: (_ for _ in ()).throw(OSError("db down")))

    scheduler._persist_dispatch_failure("T-9", RuntimeError("boom"))


def test_draft_collect_failure_is_reported_not_raised(project, monkeypatch):
    """DRAFT 收编失败同样只记 outcome，不杀掉调度循环。"""
    monkeypatch.setattr(
        scheduler, "collect_drafts",
        lambda pid, db_file=None: (_ for _ in ()).throw(OSError("db busy")),
    )

    outcomes = scheduler.schedule_once(project)

    assert outcomes[0]["state"] == "ERROR"
    assert "draft_collect_failed" in outcomes[0]["detail"]
