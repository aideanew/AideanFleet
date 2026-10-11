"""契约测试（TASK-002）：existing 端点响应用唯一源 schema 校验。

todos.list 与 events.list 的契约测试随 TASK-103 落地（这两个接口按契约
{ok, items, next_cursor}/{ok, items} 改造时一并加测，避免中间态红灯）。
演练口径：人为删除响应字段 → 本测试失败（见任务卡验收）。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from fleet.console import server as console_server
from tests.contracts.validator import load_schema, validate

CONTRACTS = Path(__file__).resolve().parents[2] / "packages" / "contracts"


@pytest.fixture()
def client(fleet_env, project):
    from fastapi.testclient import TestClient

    tc = TestClient(console_server.app)
    response = tc.post("/api/session", json={"project": project})
    assert response.status_code == 200
    tc.headers.update({"Authorization": f"Bearer {response.json()['token']}"})
    return tc


def _check(tc, method: str, url: str, schema_file: str, expect_status: int = 200, **kwargs):
    response = getattr(tc, method)(url, **kwargs)
    assert response.status_code == expect_status, response.text
    schema = load_schema(schema_file, CONTRACTS)
    errors = validate(response.json(), schema, root_dir=CONTRACTS)
    assert errors == [], f"{method} {url} 响应不符契约: {errors}"
    return response


def test_health_matches_contract(fleet_env):
    from fastapi.testclient import TestClient

    tc = TestClient(console_server.app)
    _check(tc, "get", "/api/health", "api.json")


def test_attention_matches_contract(client):
    _check(client, "get", "/api/kernel/attention", "api.json")


def test_todos_reopen_matches_contract(client, fleet_env):
    from fleet.core import db

    todo_id = "T-CONTRACT"
    db.create_task({
        "task_id": todo_id, "project_id": "P-001", "title": "契约测试",
        "detail": "", "verify_cmd": "", "assignee": "worker-a", "reviewer": "reviewer-1",
        "workspace": "", "allowed_files": "", "forbidden_files": "", "adapter": "stub",
    })
    # 旧链路 task id 不在 kernel 中 → 404 TODO_NOT_FOUND 分支一并覆盖
    _check(client, "post", f"/api/kernel/todos/{todo_id}/reopen", "api.json", expect_status=404)
    from fleet.kernel import Kernel
    from fleet.kernel import store

    # 造一个 blocked 的 kernel todo → reopen 成功分支
    kernel = Kernel(fleet_env["data"] / "kernel.db")
    gid = kernel.create_goal("契约")
    tid = kernel.create_todo(gid, title="t", verify=["x"])
    kernel.claim(tid, "w")
    kernel.transition(tid, __import__("fleet.kernel.state", fromlist=["TurnResult"]).TurnResult(
        verdict="blocked"))
    _check(client, "post", f"/api/kernel/todos/{tid}/reopen", "api.json")


def test_validator_rejects_missing_required():
    schema = {"type": "object", "required": ["ok"], "properties": {"ok": {"const": True}}}
    assert validate({"ok": True}, schema, root_dir=CONTRACTS) == []
    errors = validate({"other": 1}, schema, root_dir=CONTRACTS)
    assert any("缺少必填字段" in e for e in errors)


def test_validator_rejects_extra_when_additional_false():
    schema = {"type": "object", "additionalProperties": False,
              "properties": {"a": {"type": "string"}}}
    assert validate({"a": "x"}, schema, root_dir=CONTRACTS) == []
    assert any("多余字段" in e for e in validate({"a": "x", "b": 1}, schema, root_dir=CONTRACTS))
