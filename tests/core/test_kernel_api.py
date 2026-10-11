"""TASK-103：Kernel 投影 API 契约测试（goals.create/list、todos.get、evidence、todos.list 分页）。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from fleet.console import server as console_server
from fleet.kernel import Kernel, store
from fleet.kernel.state import TurnResult
from tests.contracts.validator import validate

CONTRACTS = Path(__file__).resolve().parents[2] / "packages" / "contracts"


@pytest.fixture()
def client(fleet_env, project, monkeypatch):
    """会话客户端 + 隔离 kernel 库 + 可用规划模型（假 fleet.toml + 假 key）。"""
    from fastapi.testclient import TestClient

    (fleet_env["root"] / "fleet.toml").write_text(
        '[models.fake]\n'
        'base_url = "http://127.0.0.1:9/v1"\n'
        'model_id = "fake-1"\n'
        'api_key_env = "FAKE_PLANNER_KEY"\n\n'
        '[roles.planner]\n'
        'models = ["fake"]\n\n'
        '[workspace]\n'
        'allowed_roots = ["E:/Demo"]\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("FAKE_PLANNER_KEY", "k" * 8)
    tc = TestClient(console_server.app)
    response = tc.post("/api/session", json={"project": project})
    assert response.status_code == 200
    tc.headers.update({"Authorization": f"Bearer {response.json()['token']}"})
    return tc


def _validate(payload: dict, schema_file: str):
    schema = __import__("json").loads((CONTRACTS / schema_file).read_text(encoding="utf-8"))
    errors = validate(payload, schema, root_dir=CONTRACTS)
    assert errors == [], f"{schema_file}: {errors}"


def test_goals_create_success_and_idempotency(client):
    body = {"title": "命令行计算器", "requirements": "做一个支持四则运算的命令行计算器",
            "workspace": "E:/Demo/Calc"}
    response = client.post("/api/kernel/goals", json=body,
                           headers={"Idempotency-Key": "key-001"})
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["ok"] is True and payload["goal"]["title"] == "命令行计算器"
    assert payload["goal"]["workspace"] == "E:/Demo/Calc"
    _validate(payload, "api.json")

    repeat = client.post("/api/kernel/goals", json=body,
                         headers={"Idempotency-Key": "key-001"})
    assert repeat.json()["goal"]["id"] == payload["goal"]["id"]  # 同 key 只建一次
    assert len(client.get("/api/kernel/goals").json()["items"]) == 1


def test_goals_create_validation_and_workspace_errors(client):
    bad = client.post("/api/kernel/goals", json={"title": "", "requirements": ""})
    assert bad.status_code == 422 and bad.json()["reason"] == "VALIDATION_FAILED"
    outside = client.post("/api/kernel/goals", json={
        "title": "x", "requirements": "y", "workspace": "C:/Windows/Temp/Evil"})
    assert outside.status_code == 422 and outside.json()["reason"] == "WORKSPACE_NOT_ALLOWED"


def test_goals_create_setup_incomplete(client, monkeypatch):
    monkeypatch.delenv("FAKE_PLANNER_KEY", raising=False)
    response = client.post("/api/kernel/goals", json={
        "title": "x", "requirements": "y", "workspace": "E:/Demo/Calc"})
    assert response.status_code == 409 and response.json()["reason"] == "SETUP_INCOMPLETE"


def test_goals_list_paginated(client):
    for i in range(3):
        client.post("/api/kernel/goals", json={"title": f"目标{i}", "requirements": "r",
                                               "workspace": "E:/Demo/Calc"},
                    headers={"Idempotency-Key": f"g-{i}"})
    page1 = client.get("/api/kernel/goals?limit=2").json()
    assert len(page1["items"]) == 2 and page1["next_cursor"]
    page2 = client.get(f"/api/kernel/goals?limit=2&cursor={page1['next_cursor']}").json()
    assert len(page1["items"]) + len(page2["items"]) == 3
    assert page2["next_cursor"] is None


def test_todos_list_paginated_and_get(client):
    created = client.post("/api/kernel/goals", json={
        "title": "目标A", "requirements": "r", "workspace": "E:/Demo/Calc"},
        headers={"Idempotency-Key": "ga"}).json()
    plan_todo = created["plan_todo_id"]

    listing = client.get(f"/api/kernel/todos?goal_id={created['goal']['id']}").json()
    assert listing["ok"] and [t["id"] for t in listing["items"]] == [plan_todo]
    assert listing["next_cursor"] is None
    _validate(listing, "api.json")

    detail = client.get(f"/api/kernel/todos/{plan_todo}").json()
    assert detail["ok"] and detail["todo"]["id"] == plan_todo
    assert detail["attempts"] == [] and detail["evidence"] == []
    _validate(detail, "api.json")

    missing = client.get("/api/kernel/todos/T-NOPE")
    assert missing.status_code == 404 and missing.json()["reason"] == "TODO_NOT_FOUND"


def test_evidence_download_name_whitelist(client):
    kernel = Kernel(client.app and __import__("fleet.core.paths", fromlist=["paths"]).paths().data_dir / "kernel.db")
    gid = kernel.create_goal("g")
    tid = kernel.create_todo(gid, title="t", verify=["x"])
    evidence_dir = __import__("fleet.core.paths", fromlist=["paths"]).paths().data_dir / "evidence" / tid
    evidence_dir.mkdir(parents=True)
    (evidence_dir / "gate.json").write_text('{"ok": true}', encoding="utf-8")
    (evidence_dir / "secret.txt").write_text("evil", encoding="utf-8")

    ok = client.get(f"/api/kernel/todos/{tid}/evidence/gate.json")
    assert ok.status_code == 200 and b"true" in ok.content

    traversal = client.get(f"/api/kernel/todos/{tid}/evidence/..%2F..%2Fsecrets")
    assert traversal.status_code in (404, 422)
    evil = client.get(f"/api/kernel/todos/{tid}/evidence/secret.txt")
    assert evil.status_code == 422 and evil.json()["reason"] == "VALIDATION_FAILED"

    detail = client.get(f"/api/kernel/todos/{tid}").json()
    assert detail["evidence"] == [{
        "name": "gate.json", "kind": "gate", "size": 12,
        "url": f"/api/kernel/todos/{tid}/evidence/gate.json",
    }]


def test_reopen_illegal_transition_and_success(client, fleet_env):
    kernel = Kernel(fleet_env["data"] / "kernel.db")
    gid = kernel.create_goal("g")
    tid = kernel.create_todo(gid, title="t", verify=["x"])
    # open 状态不可 reopen → 409 ILLEGAL_TRANSITION
    illegal = client.post(f"/api/kernel/todos/{tid}/reopen")
    assert illegal.status_code == 409 and illegal.json()["reason"] == "ILLEGAL_TRANSITION"

    kernel.claim(tid, "w")
    kernel.transition(tid, TurnResult(verdict="blocked"))
    ok = client.post(f"/api/kernel/todos/{tid}/reopen")
    assert ok.status_code == 200 and ok.json()["todo"]["status"] == "open"
    _validate(ok.json(), "api.json")


def test_events_list_contract_shape(client):
    kernel = Kernel(__import__("fleet.core.paths", fromlist=["paths"]).paths().data_dir / "kernel.db")
    gid = kernel.create_goal("g")
    kernel.create_todo(gid, title="t", verify=["x"])
    listing = client.get("/api/kernel/events?limit=10").json()
    assert listing["ok"] and listing["items"]
    event = listing["items"][0]
    assert {"seq", "ts", "kind", "todo_id", "goal_id", "payload", "published"} <= set(event)
    _validate(listing, "api.json")


def test_steer_create_and_decision_flow(client, monkeypatch):
    """TASK-602：steer.create → plan.diff.get → plan.decide（approve/reject/重复 409）。"""
    created = client.post("/api/kernel/goals", json={
        "title": "目标S", "requirements": "r", "workspace": "E:/Demo/Calc"},
        headers={"Idempotency-Key": "st-0"}).json()

    steer = client.post(f"/api/kernel/goals/{created['goal']['id']}/steer",
                        json={"message": "补一个日志功能"})
    assert steer.status_code == 200, steer.text
    steer_id = steer.json()["steer_todo_id"]
    _validate(steer.json(), "api.json")

    # 产出 diff：直接造 needs_user + pending
    kernel = __import__("fleet.kernel", fromlist=["Kernel"]).Kernel(
        __import__("fleet.core.paths", fromlist=["paths"]).paths().data_dir / "kernel.db")
    kernel.claim(steer_id, "w")
    kernel.propose_plan_diff(steer_id, {"add": [], "cancel": [], "modify": []})

    diff_view = client.get(f"/api/kernel/todos/{steer_id}/diff").json()
    assert diff_view["ok"] and diff_view["decision"] == "pending"
    _validate(diff_view, "api.json")

    approved = client.post(f"/api/kernel/todos/{steer_id}/decision",
                           json={"decision": "approve"})
    assert approved.status_code == 200
    assert approved.json()["todo"]["plan_decision"] == "approved"

    again = client.post(f"/api/kernel/todos/{steer_id}/decision", json={"decision": "reject"})
    assert again.status_code == 409 and again.json()["reason"] == "DECISION_ALREADY_MADE"

    missing_goal = client.post("/api/kernel/goals/G-NOPE/steer", json={"message": "x"})
    assert missing_goal.status_code == 404 and missing_goal.json()["reason"] == "GOAL_NOT_FOUND"


def test_chat_routes_to_steer_when_single_active_goal(client, monkeypatch, fleet_env):
    """TASK-602：会话发普通消息且恰有一个活跃 kernel goal → 生成 steer todo；旧启动指令路径不变。"""
    created = client.post("/api/kernel/goals", json={
        "title": "唯一目标", "requirements": "r", "workspace": "E:/Demo/Calc"},
        headers={"Idempotency-Key": "chat-0"}).json()

    response = client.post("/api/chat", json={"message": "给核心模块补上错误处理"})
    assert response.status_code == 200
    payload = response.json()
    assert payload.get("steer_todo_id"), payload
    kernel = __import__("fleet.kernel", fromlist=["Kernel"]).Kernel(
        __import__("fleet.core.paths", fromlist=["paths"]).paths().data_dir / "kernel.db")
    todo = kernel.get_todo(payload["steer_todo_id"])
    assert todo["kind"] == "steer" and todo["goal_id"] == created["goal"]["id"]

    # 旧启动指令路径不受影响（正则命中 → 走旧 intake；工作区在白名单内）
    legacy = client.post("/api/chat", json={
        "message": f"启动新项目：ChatLegacy（工作区：{fleet_env['root'] / 'ChatLegacy'}）"})
    assert legacy.status_code == 200
    assert not legacy.json().get("steer_todo_id")
