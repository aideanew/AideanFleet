"""可观测性端点（需求4/5/6）：/api/executors/running、/api/history/tasks、/api/roles/{role}/profile。"""

import pytest
from fastapi.testclient import TestClient

from fleet.core import db
from fleet.executors import registry


@pytest.fixture()
def client(fleet_env, monkeypatch):
    from fleet.console import server as console_server

    monkeypatch.setenv("FLEET_DATA_DIR", str(fleet_env["data"]))
    console_server._sessions.clear()
    db.create_project("P-810", "Observability", "E:/Demo/Observability")
    return TestClient(console_server.app)


def _unlock(client):
    body = client.post("/api/session", json={"project": "P-810"}).json()
    return {"Authorization": f"Bearer {body['token']}"}


class FakeProc:
    def __init__(self, pid, code=None):
        self.pid = pid
        self.code = code

    def poll(self):
        return self.code


# ------------------------------- /api/executors/running -------------------------------

def test_executors_running_lists_registered_processes(client):
    headers = _unlock(client)
    registry._entries.clear()
    registry.clear_run_context()
    keys = []
    try:
        with registry.run_context(task_id="P-810-T01", role="fe-1", adapter="opencode", project="P-810", model="agnes"):
            keys.append(registry.begin(["opencode", "run"], cwd="E:/ws", proc=FakeProc(111)))
        # 其它项目的登记项不应混进本项目的读数
        with registry.run_context(project="P-OTHER", task_id="P-810-T01"):
            keys.append(registry.begin(["codex"], proc=FakeProc(222)))
        body = client.get("/api/executors/running", headers=headers).json()
        assert body["ok"] is True
        assert body["count"] == 1
        row = body["executors"][0]
        assert row["pid"] == 111
        assert row["task_id"] == "P-810-T01"
        assert row["role"] == "fe-1"
        assert row["alive"] is True
        assert "proc" not in row
    finally:
        for key in keys:
            registry.end(key)
        registry.clear_run_context()


def test_executors_running_requires_session(client):
    assert client.get("/api/executors/running").status_code == 401


# ------------------------------- /api/history/tasks -------------------------------

def test_history_tasks_sorted_and_field_mapped(client):
    headers = _unlock(client)
    db.create_task({"task_id": "P-810-T01", "project_id": "P-810", "title": "写契约",
                    "assignee": "pm-1", "workspace": "E:/Demo/Observability"})
    db.create_task({"task_id": "P-810-T02", "project_id": "P-810", "title": "实现前端",
                    "assignee": "fe-1", "workspace": "E:/Demo/Observability"})
    db.update_task("P-810-T01", exec_status="DONE", reviewer="rv-1", duration_ms=90_000,
                   token=1234, rework_count=1)
    db.update_task("P-810-T02", exec_status="DOING", reviewer="rv-2", duration_ms=5_000)
    # update_task 自动刷 updated_at（秒级并发会撞时间戳）：直接回写确定值验证倒序口径
    with db.session() as conn:
        conn.execute("UPDATE tasks SET updated_at = ? WHERE task_id = ?",
                     ("2026-09-17T10:00:00", "P-810-T01"))
        conn.execute("UPDATE tasks SET updated_at = ? WHERE task_id = ?",
                     ("2026-09-18T09:00:00", "P-810-T02"))

    body = client.get("/api/history/tasks", headers=headers).json()
    assert body["ok"] is True
    assert body["total"] == 2
    first, second = body["tasks"]
    # updated_at 倒序：T02 更新在后
    assert first["task_id"] == "P-810-T02"
    assert first["assignee"] == "fe-1" and first["reviewer"] == "rv-2"
    assert second["task_id"] == "P-810-T01"
    assert second["duration_ms"] == 90_000
    assert second["token"] == 1234
    assert second["rework_count"] == 1
    assert second["exec_status"] == "DONE"


def test_history_tasks_unknown_project(client):
    headers = _unlock(client)
    body = client.get("/api/history/tasks", params={"project": "P-404"}, headers=headers).json()
    assert body["ok"] is False and body["reason"] == "project_not_found"


def test_history_tasks_requires_session(client):
    assert client.get("/api/history/tasks").status_code == 401


# ------------------------------- /api/roles/{role}/profile -------------------------------

def test_role_profile_buckets_executed_reviewed_future(client):
    from fleet.core import events

    headers = _unlock(client)
    db.create_task({"task_id": "P-810-T01", "project_id": "P-810", "title": "写契约",
                    "assignee": "fe-1", "reviewer": "rv-1", "workspace": "E:/Demo/Observability"})
    db.update_task("P-810-T01", exec_status="DONE", duration_ms=60_000)
    db.create_task({"task_id": "P-810-T02", "project_id": "P-810", "title": "写页面",
                    "assignee": "fe-1", "workspace": "E:/Demo/Observability"})
    db.update_task("P-810-T02", exec_status="ASSIGNED")
    events.append(
        actor="fe-1", action="model:call", task_id="P-810-T01", project="P-810",
        extra={"role": "fe-1", "usage": {"total_tokens": 800}},
    )
    # 审查调用（无 task_id）按 extra.role 归属到 rv-1
    events.append(
        actor="rv-1", action="model:call", project="P-810",
        extra={"role": "rv-1", "usage": {"total_tokens": 300}},
    )

    fe = client.get("/api/roles/fe-1/profile", headers=headers).json()
    assert fe["ok"] is True
    profile = fe["profile"]
    assert profile["executed_count"] == 2
    assert profile["done_count"] == 1
    assert profile["duration_ms"] == 60_000
    assert profile["future_count"] == 1  # T02 还是 ASSIGNED
    assert profile["future"][0]["task_id"] == "P-810-T02"
    assert profile["total_tokens"] == 800
    assert profile["call_count"] == 1

    rv = client.get("/api/roles/rv-1/profile", headers=headers).json()["profile"]
    assert rv["executed_count"] == 0
    assert rv["reviewed_count"] == 1
    assert rv["total_tokens"] == 300


def test_role_profile_requires_session(client):
    assert client.get("/api/roles/fe-1/profile").status_code == 401
