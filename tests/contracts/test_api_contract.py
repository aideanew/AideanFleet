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


# ---------------------------------------------------------------------------
# 路由反向守门（P0.3 契约补录）：新增端点必须登记 api.json
# ---------------------------------------------------------------------------

_HTTP_METHODS = {"GET", "POST", "PUT", "DELETE", "PATCH"}

# 非 API 语义路由（SPA 静态文件 catch-all），不参与契约登记检查
_INFRA_ROUTES = frozenset({
    "GET /{path:path}",
})

# 旧链路端点（早于契约唯一源约定，响应未收敛）：只允许存量，禁止新增。
# 某端点补录契约后必须从本白名单移除（test_legacy_allowlist_still_tight 守门）。
_LEGACY_UNREGISTERED = frozenset({
    "GET /api/session", "POST /api/session", "POST /api/session/switch", "DELETE /api/session",
    "GET /api/projects", "GET /api/projects/names",
    "GET /api/mode", "POST /api/mode", "GET /api/plan", "GET /api/events",
    "GET /api/launch-resolve", "POST /api/launch-event",
    "POST /api/confirm", "POST /api/control/confirm", "POST /api/chat",
    "POST /api/notify/test", "GET /api/notify/triggers",
    "GET /api/extensions", "POST /api/extensions",
    "GET /api/role-adapters", "POST /api/role-adapters",
    "GET /api/config/{section}", "POST /api/config/{section}",
    "GET /api/tasks/{task_id}",
    "GET /api/approvals", "GET /api/approvals/{approval_id}",
    "POST /api/approvals/{approval_id}/approve", "POST /api/approvals/{approval_id}/reject",
    "GET /api/usage/total", "GET /api/usage/by_date",
    "GET /api/budget", "POST /api/budget",
    "GET /api/roles/summary", "GET /api/roles/{role}/profile",
    "GET /api/executors/running", "GET /api/history/tasks",
    "POST /tasks/{task_id}/dispatch",
    # evidence 下载返回 FileResponse（二进制流），无 JSON 响应体可契约化
    "GET /api/kernel/todos/{todo_id}/evidence/{name}",
})


def _app_route_signatures() -> set:
    """展平 app 路由为 'METHOD /path' 集合。

    starlette>=1.6 的 include_router 惰性化为 _IncludedRouter（请求匹配期才展开），
    这里读 original_router 主动展平；旧版 starlette 直接复制 APIRoute 到 app.routes，两者兼容。
    """
    from fastapi.routing import APIRoute

    signatures: set = set()

    def add(route) -> None:
        for method in (getattr(route, "methods", None) or set()) & _HTTP_METHODS:
            signatures.add(f"{method} {route.path}")

    for route in console_server.app.routes:
        if isinstance(route, APIRoute):
            add(route)
            continue
        included = getattr(route, "original_router", None)  # starlette>=1.6 _IncludedRouter
        if included is not None:
            prefix = getattr(getattr(route, "include_context", None), "prefix", "") or ""
            for inner in included.routes:
                if isinstance(inner, APIRoute):
                    for method in (inner.methods or set()) & _HTTP_METHODS:
                        signatures.add(f"{method} {prefix}{inner.path}")
    return signatures


def _declared_route_signatures() -> set:
    api = load_schema("api.json")
    return {f"{ep['method']} {ep['path']}" for ep in api["endpoints"]}


def test_all_app_routes_registered_or_legacy():
    orphans = sorted(
        _app_route_signatures() - _declared_route_signatures() - _LEGACY_UNREGISTERED - _INFRA_ROUTES
    )
    assert not orphans, (
        "发现未登记契约的端点：新端点必须先补 packages/contracts/api.json；"
        f"确属旧链路存量的才允许加入白名单：{orphans}"
    )


def test_legacy_allowlist_still_tight():
    stale = sorted(_LEGACY_UNREGISTERED & _declared_route_signatures())
    assert not stale, f"白名单中这些端点已登记契约，请从 _LEGACY_UNREGISTERED 移除：{stale}"


def test_contract_existing_endpoints_mounted():
    api = load_schema("api.json")
    actual = _app_route_signatures()
    missing = [
        f"{ep['method']} {ep['path']}"
        for ep in api["endpoints"]
        if str(ep.get("status", "")).startswith("existing")
        and f"{ep['method']} {ep['path']}" not in actual
    ]
    assert not missing, f"契约标记 existing 的端点未在 app 注册：{missing}"
