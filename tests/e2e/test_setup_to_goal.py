"""P1.5：新装机器金线 e2e——纯 HTTP 全链路（SetupPage 同款提交体）。

复现真实新用户时序（不预写 fleet.toml、不预置环境变量）：
  净环境 → goals.create 409(no_model) → PUT /api/config/fleet 存模型（merge+保底绑定）
  → goals.create 409(no_key) → PUT /api/setup/secrets/<ENV> 写钥（进程热更新）
  → goals.create 200（默认工作区推导 + planner_ready）。

每个断点都对应 P1.1–P1.4 修过的一条实测断链：
  409 三态 hint / PUT 500 / 422 allowed_roots / PLAINTEXT_SECRET 误伤 / 写钥后需重启。
"""

from __future__ import annotations

import pytest

from fleet.core import fleet_toml

_ENV_NAME = "E2E_GOLDEN_KEY"


@pytest.fixture(autouse=True)
def _deterministic_env(monkeypatch):
    """隔离宿主环境：密钥变量与 FLEET_ALLOWED_ROOTS 均不受宿主 shell 影响。"""
    monkeypatch.delenv(_ENV_NAME, raising=False)
    monkeypatch.delenv("FLEET_ALLOWED_ROOTS", raising=False)


@pytest.fixture()
def tc(fleet_env, project, monkeypatch):
    """会话客户端（owner 已解锁）+ 回环视角（config/secrets 路由要求）。"""
    from fastapi.testclient import TestClient

    from fleet.console import server as console_server

    monkeypatch.setattr("fleet.console.loopback.client_host",
                        lambda request: "127.0.0.1")
    client = TestClient(console_server.app, base_url="http://127.0.0.1:3100")
    resp = client.post("/api/session", json={"project": "P-001"})
    assert resp.status_code == 200, resp.text
    client.headers.update({"Authorization": f"Bearer {resp.json()['token']}"})
    return client


def _create_goal(client, title="金线验证目标"):
    return client.post("/api/kernel/goals",
                       json={"title": title, "requirements": "走通新装机器全链路"})


def test_setup_to_goal_golden_line(tc, fleet_env):
    # 1) 净环境：无模型 → 409 no_model（三态 hint）
    resp = _create_goal(tc)
    assert resp.status_code == 409, resp.text
    assert resp.json()["reason"] == "SETUP_INCOMPLETE"
    assert resp.json()["details"]["hint"]["state"] == "no_model"

    # 2) 存模型（SetupPage 同款提交体：只带 models，不带 roles/workspace/runtime）
    resp = tc.put("/api/config/fleet", json={"models": {
        "golden": {"base_url": "https://api.openai.com/v1",
                   "model_id": "gpt-4o-mini",
                   "api_key_env": _ENV_NAME}}})
    assert resp.status_code == 200, resp.text
    cfg = fleet_toml.load_config()
    assert cfg.roles["planner"].models == ["golden"]  # 保底绑定，无需显式 roles

    # 3) 有模型无密钥 → 409 no_key + 待填变量名
    resp = _create_goal(tc)
    assert resp.status_code == 409, resp.text
    hint = resp.json()["details"]["hint"]
    assert hint["state"] == "no_key" and hint["missing_keys"] == [_ENV_NAME]

    # 4) 写密钥（写后同进程热更新，无需重启控制台）
    resp = tc.put(f"/api/setup/secrets/{_ENV_NAME}",
                  json={"value": "e2e-golden-secret-0001"})
    assert resp.status_code == 200, resp.text

    # 5) goals.create 200：密钥热更新过门 + 默认工作区推导（roots 回退链）
    resp = _create_goal(tc)
    assert resp.status_code == 200, resp.text
    goal = resp.json()["goal"]
    assert goal["status"] == "active"
    assert "workspaces" in goal["workspace"]  # 未配置 roots → data/workspaces/<slug>
    from pathlib import Path

    expected_root = fleet_env["data"] / "workspaces"
    assert Path(goal["workspace"]).parent == expected_root


def test_draft_clarify_freeze_golden_line(tc, fleet_env):
    """P3：draft 离线立标 → 冻结门序（SETUP 先于长度）→ 澄清 → 冻结出计划 → frozen 拒改。"""
    # 1) 净环境即可建草稿（P3 决策：draft 不依赖规划器就绪）
    resp = tc.post("/api/kernel/goals", json={
        "title": "草稿金线", "requirements": "先立目标", "mode": "draft"})
    assert resp.status_code == 200, resp.text
    gid = resp.json()["goal"]["id"]
    assert resp.json()["plan_todo_id"] is None
    assert resp.json()["goal"]["requirements_state"] == "draft"

    # 2) 净环境冻结 → SETUP_INCOMPLETE（门先于需求长度检查：冻结即触发规划）
    resp = tc.post(f"/api/kernel/goals/{gid}/freeze")
    assert resp.status_code == 409, resp.text
    assert resp.json()["reason"] == "SETUP_INCOMPLETE"

    # 3) 补模型 + 密钥（golden 同款 merge+保底绑定+热更新）
    resp = tc.put("/api/config/fleet", json={"models": {
        "golden2": {"base_url": "https://api.openai.com/v1",
                    "model_id": "gpt-4o-mini",
                    "api_key_env": _ENV_NAME}}})
    assert resp.status_code == 200, resp.text
    resp = tc.put(f"/api/setup/secrets/{_ENV_NAME}",
                  json={"value": "e2e-draft-secret-0002"})
    assert resp.status_code == 200, resp.text

    # 4) 规划器就绪但需求太短 → REQUIREMENTS_NOT_READY（状态仍 draft）
    resp = tc.post(f"/api/kernel/goals/{gid}/freeze")
    assert resp.status_code == 409, resp.text
    assert resp.json()["reason"] == "REQUIREMENTS_NOT_READY"

    # 5) 追加式澄清补足需求
    resp = tc.post(f"/api/kernel/goals/{gid}/clarify",
                   json={"addition": "做一个个人博客，支持 Markdown 渲染与标签归档"})
    assert resp.status_code == 200, resp.text

    # 6) 冻结 200：锁定 + 同事务建 plan todo
    resp = tc.post(f"/api/kernel/goals/{gid}/freeze")
    assert resp.status_code == 200, resp.text
    payload = resp.json()
    assert payload["goal"]["requirements_state"] == "frozen"
    assert payload["plan_todo_id"]
    todo = tc.get(f"/api/kernel/todos/{payload['plan_todo_id']}").json()
    assert todo["todo"]["kind"] == "plan" and todo["todo"]["status"] == "open"

    # 7) frozen 后再澄清 → GOAL_ALREADY_FROZEN
    resp = tc.post(f"/api/kernel/goals/{gid}/clarify", json={"addition": "迟到的需求"})
    assert resp.status_code == 409
    assert resp.json()["reason"] == "GOAL_ALREADY_FROZEN"
