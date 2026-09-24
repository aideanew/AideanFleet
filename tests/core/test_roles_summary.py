"""角色贡献聚合 API（大纲 L1-B 2.2）。"""

import pytest
from fastapi.testclient import TestClient

from fleet.core import db


@pytest.fixture()
def client(fleet_env, monkeypatch):
    from fleet.console import server as console_server

    monkeypatch.setenv("FLEET_DATA_DIR", str(fleet_env["data"]))
    console_server._sessions.clear()
    db.create_project("P-900", "RolesSummary", "E:/Demo/RolesSummary")
    return TestClient(console_server.app)


def _unlock(client):
    body = client.post("/api/session", json={"project": "P-900"}).json()
    return {"Authorization": f"Bearer {body['token']}"}


def test_roles_summary_aggregates_duration_and_usage(client):
    """任务数/耗时按 assignee；token 按事件 extra.role 归属（审查调用无 taskId 也计入）。"""
    from fleet.core import events

    headers = _unlock(client)
    db.create_task(
        {"task_id": "P-900-T01", "project_id": "P-900", "title": "实现",
         "assignee": "fe-1", "workspace": "E:/Demo/RolesSummary"}
    )
    db.update_task("P-900-T01", exec_status="DONE", duration_ms=120_000)
    events.append(
        actor="fe-1", action="model:call", task_id="P-900-T01", project="P-900",
        extra={"role": "fe-1", "model": "agnes", "usage": {
            "prompt_tokens": 1000, "completion_tokens": 200, "total_tokens": 1200,
        }},
    )
    # 审查类调用：无 taskId，但 role=reviewer-1 也要计入其 token
    events.append(
        actor="reviewer-1", action="model:call", project="P-900",
        extra={"role": "reviewer-1", "model": "agnes", "usage": {"total_tokens": 500}},
    )

    response = client.get("/api/roles/summary", headers=headers)
    assert response.status_code == 200
    roles = response.json()["roles"]
    fe = next(role for role in roles if role["role"] == "fe-1")
    assert fe["tasks_total"] == 1
    assert fe["tasks_done"] == 1
    assert fe["duration_ms"] == 120_000
    assert fe["total_tokens"] == 1200
    assert fe["call_count"] == 1
    reviewer = next(role for role in roles if role["role"] == "reviewer-1")
    assert reviewer["tasks_total"] == 0
    assert reviewer["total_tokens"] == 500


def test_roles_summary_requires_session(client):
    assert client.get("/api/roles/summary").status_code == 401
