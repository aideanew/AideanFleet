"""BLOCKED 放行端点不得阻塞事件循环（回归：dispatch 同步执行导致控制台全端点停摆）。"""

from __future__ import annotations

import threading
import time

from fastapi.testclient import TestClient

from fleet.console import server as console_server


def _login(tc: TestClient) -> None:
    response = tc.post("/api/session", json={"project": "AideanFleet"})
    assert response.status_code == 200
    tc.headers.update({"Authorization": f"Bearer {response.json()['token']}"})


def test_blocked_confirm_returns_immediately_and_redispatches_async(monkeypatch):
    tc = TestClient(console_server.app)
    _login(tc)
    task_id = "EVICT-T01"
    task = {
        "task_id": task_id, "project_id": "AideanFleet", "exec_status": "BLOCKED",
        "blocked_reason": "executor_failed", "assignee": "be-1", "adapter": "",
        "workspace": "", "title": "t", "detail": "", "verify_cmd": "", "report_path": "",
        "evidence_path": "", "baseline_path": "",
    }
    monkeypatch.setattr(console_server.db, "get_task", lambda tid: task if tid == task_id else None)
    logged: list[tuple] = []
    monkeypatch.setattr(
        console_server.db, "transition_and_log",
        lambda tid, state, **kw: logged.append((tid, state)) or {**task, "exec_status": state},
    )
    started = threading.Event()
    calls: list[str] = []

    def slow_dispatch(tid, **kw):
        started.set()
        time.sleep(0.4)
        calls.append(tid)
        return console_server.dispatcher.DispatchOutcome(ok=True, task_id=tid, state="SUBMITTED")

    monkeypatch.setattr(console_server.dispatcher, "dispatch", slow_dispatch)

    t0 = time.perf_counter()
    response = tc.post("/api/control/confirm", json={"taskId": task_id, "note": "放行"})
    elapsed = time.perf_counter() - t0

    assert response.status_code == 200
    assert response.json()["state"] == "ASSIGNED"
    # dispatch 转后台线程：端点立即返回，不等子进程（同步执行时 elapsed ≥ 0.4s）
    assert elapsed < 0.3, f"放行端点被 dispatch 阻塞了 {elapsed:.2f}s"
    assert logged == [(task_id, "ASSIGNED")]
    assert started.wait(timeout=2), "后台派工线程未启动"
    deadline = time.time() + 2
    while not calls and time.time() < deadline:
        time.sleep(0.05)
    assert calls == [task_id]
