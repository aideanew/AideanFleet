"""P3.3：Quickstart 单源与内核金线测试。

- status.has_api_key 语义升级为 planner_status 三态单源（fleet.toml 密钥不再漏检）；
- create 计划由旧 intake 模板链改为 kernel create_goal_with_plan（kind=plan 规划 todo）；
- 计划失败不阻塞（plan=null）；仅回环可访问。
"""

from __future__ import annotations

import pytest

from fleet.console import server as console_server
from fleet.core import fleet_toml


@pytest.fixture()
def tc(fleet_env, monkeypatch):
    """回环视角客户端（quickstart 免会话但仅回环）。"""
    from fastapi.testclient import TestClient

    monkeypatch.setattr("fleet.console.loopback.client_host",
                        lambda request: "127.0.0.1")
    client = TestClient(console_server.app, base_url="http://127.0.0.1:3100")
    return client


def _write_planner_toml(fleet_env):
    (fleet_env["root"] / "fleet.toml").write_text(
        '[models.quick]\n'
        'base_url = "http://127.0.0.1:9/v1"\n'
        'model_id = "quick-1"\n'
        'api_key_env = "QUICKSTART_TEST_KEY"\n\n'
        '[roles.planner]\n'
        'models = ["quick"]\n',
        encoding="utf-8",
    )


def test_status_planner_ready_single_source(tc, fleet_env, monkeypatch):
    """fleet.toml 自定义密钥变量也能被检测（旧硬编码 6 变量清单漏检的回归）。"""
    _write_planner_toml(fleet_env)
    monkeypatch.delenv("QUICKSTART_TEST_KEY", raising=False)
    resp = tc.get("/api/quickstart/status")
    assert resp.status_code == 200, resp.text
    payload = resp.json()
    assert payload["ok"] is True
    assert payload["has_api_key"] is False  # 有模型缺密钥 → no_key → 未就绪

    monkeypatch.setenv("QUICKSTART_TEST_KEY", "k" * 8)
    payload = tc.get("/api/quickstart/status").json()
    assert payload["has_api_key"] is True  # 密钥补齐 → ready


def test_status_no_model_not_ready(tc, fleet_env):
    """净环境（无模型）→ 未就绪，不误报。"""
    payload = tc.get("/api/quickstart/status").json()
    assert payload["has_api_key"] is False


def test_status_and_create_forbid_non_loopback(fleet_env, monkeypatch):
    from fastapi.testclient import TestClient

    monkeypatch.setattr("fleet.console.loopback.client_host",
                        lambda request: "192.168.1.66")
    client = TestClient(console_server.app, base_url="http://192.168.1.66:3100")
    assert client.get("/api/quickstart/status").status_code == 403
    resp = client.post("/api/quickstart/create", json={"description": "做一个待办应用"})
    assert resp.status_code == 403 and resp.json()["reason"] == "FORBIDDEN_NON_LOOPBACK"


def test_create_validation_minimum_length(tc):
    resp = tc.post("/api/quickstart/create", json={"description": "太"})
    assert resp.status_code == 422 and resp.json()["reason"] == "VALIDATION_FAILED"


def test_create_kernel_golden_line(tc, fleet_env):
    """create → kernel goal + kind=plan 规划 todo（金线），plan 含 goal_id/plan_todo_id。"""
    resp = tc.post("/api/quickstart/create",
                   json={"description": "开发一个待办事项网页应用，能添加删除标记完成"})
    assert resp.status_code == 200, resp.text
    payload = resp.json()
    assert payload["ok"] is True and payload["token"] and payload["project"]
    plan = payload["plan"]
    assert plan is not None, "净环境也应出 plan（kernel 建线不依赖规划器）"
    assert plan["goal_id"] and plan["plan_todo_id"]

    from fleet.kernel import Kernel

    kernel = Kernel(fleet_env["data"] / "kernel.db")
    goal = kernel.get_goal(plan["goal_id"])
    assert goal["requirements"] == "开发一个待办事项网页应用，能添加删除标记完成"
    assert goal["requirements_state"] == "frozen"  # direct 金线建即冻结
    todo = kernel.get_todo(plan["plan_todo_id"])
    assert todo["kind"] == "plan" and todo["goal_id"] == plan["goal_id"]
    assert todo["status"] == "open"
    # 工作区走 roots 缺省推导：data/workspaces/<slug>
    assert "workspaces" in goal["workspace"]


def test_create_plan_failure_not_blocking(tc, fleet_env, monkeypatch):
    """kernel 建线失败 → plan=null 但项目/会话照常（契约：失败不阻塞）。"""
    from fleet.console import kernel_api

    def _boom():
        raise RuntimeError("kernel unavailable")

    monkeypatch.setattr(kernel_api, "_kernel", _boom)
    resp = tc.post("/api/quickstart/create", json={"description": "做一个博客网站"})
    assert resp.status_code == 200, resp.text
    payload = resp.json()
    assert payload["plan"] is None
    assert payload["project"]  # 项目与令牌不受影响
