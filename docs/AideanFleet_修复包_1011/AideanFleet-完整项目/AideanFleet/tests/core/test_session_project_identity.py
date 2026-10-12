"""控制台会话的项目身份解析与切换（大纲 §3.1）。"""

import pytest
from fastapi.testclient import TestClient

from fleet.core import db


@pytest.fixture()
def client(fleet_env, monkeypatch):
    from fleet.console import server as console_server

    monkeypatch.setenv("FLEET_DATA_DIR", str(fleet_env["data"]))
    console_server._sessions.clear()
    db.create_project("P-100", "Test09171500", "E:/Demo/Test09171500")
    db.create_project("P-101", "AideanFleet", "E:/Code/AideanFleet")
    return TestClient(console_server.app)


def test_unlock_by_project_name(client):
    """按 name 解锁成功，会话项目规范化为 project_id。"""
    response = client.post("/api/session", json={"project": "Test09171500"})
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["project"] == "P-100"


def test_unlock_by_project_id(client):
    """按 project_id 解锁依旧可用。"""
    response = client.post("/api/session", json={"project": "P-101"})
    assert response.status_code == 200
    assert response.json()["project"] == "P-101"


def test_unlock_unknown_project_rejected(client):
    response = client.post("/api/session", json={"project": "NoSuch"})
    assert response.status_code == 400
    assert response.json()["ok"] is False


def test_switch_session_project(client):
    """已解锁会话可切换项目，后续 API 使用新项目。"""
    unlocked = client.post("/api/session", json={"project": "Test09171500"}).json()
    headers = {"Authorization": f"Bearer {unlocked['token']}"}

    switched = client.post(
        "/api/session/switch", json={"project": "AideanFleet"}, headers=headers
    )
    assert switched.status_code == 200
    assert switched.json()["project"] == "P-101"

    current = client.get("/api/session", headers=headers)
    assert current.json()["project"] == "P-101"


def test_switch_requires_valid_session(client):
    response = client.post(
        "/api/session/switch", json={"project": "AideanFleet"}
    )
    assert response.status_code == 401


def test_project_names_endpoint_exempt_and_minimal(client):
    """names 端点免会话，仅暴露 id 与 name。"""
    response = client.get("/api/projects/names")
    assert response.status_code == 200
    projects = response.json()["projects"]
    assert {"id": "P-100", "name": "Test09171500"} in projects
    assert all(set(item) == {"id", "name"} for item in projects)
