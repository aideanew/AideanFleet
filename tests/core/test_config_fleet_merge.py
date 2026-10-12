"""P1.1/P1.3：config.fleet.put merge 语义 + planner 保底绑定 + allowed_roots 单源回退。

背景（新装机器金线断链三连，全部实测定位）：
1. PUT 成功路径曾误调 config_fleet_get() 缺 request 参数 → TypeError 500（从未被测试覆盖）；
2. body 不带 workspace 且 toml 无配置 → 422 "allowed_roots 至少一条"（SetupPage 必中）；
3. 旧 PUT 全量替换：SetupPage 提交 roles:{} 抹掉 planner 绑定 → goals.create 409 SETUP_INCOMPLETE。
"""

from __future__ import annotations

import pytest

from fleet.console import server as console_server
from fleet.core import fleet_toml


@pytest.fixture(autouse=True)
def _clean_roots_env(monkeypatch):
    """隔离宿主 shell 的 FLEET_ALLOWED_ROOTS，保证缺省回退断言确定性。"""
    monkeypatch.delenv("FLEET_ALLOWED_ROOTS", raising=False)


@pytest.fixture()
def tc(fleet_env):
    from fastapi.testclient import TestClient

    return TestClient(console_server.app, base_url="http://127.0.0.1:3100")


def _host(monkeypatch, host="127.0.0.1"):
    monkeypatch.setattr("fleet.console.loopback.client_host", lambda request: host)


def _write_toml(fleet_env, text):
    (fleet_env["root"] / "fleet.toml").write_text(text, encoding="utf-8")


def test_put_success_returns_config_not_500(tc, fleet_env, monkeypatch):
    """回归：旧实现成功路径 config_fleet_get() 缺 request → TypeError 500。"""
    _host(monkeypatch)
    resp = tc.put("/api/config/fleet", json={"models": {
        "main": {"base_url": "https://api.openai.com/v1", "model_id": "gpt-4o-mini",
                 "api_key_env": "MAIN_KEY"}}})
    assert resp.status_code == 200, resp.text
    payload = resp.json()
    assert payload["ok"] is True
    assert payload["config"]["models"]["main"]["api_key_env"] == "MAIN_KEY"
    assert payload["path"].endswith("fleet.toml")


def test_put_accepts_realistic_urls_and_model_ids(tc, fleet_env, monkeypatch):
    """P1.1 回归：旧高熵启发式把真实 URL/model_id 误判 PLAINTEXT_SECRET → 真实用户必 422。"""
    _host(monkeypatch)
    resp = tc.put("/api/config/fleet", json={"models": {
        "agnes": {"base_url": "https://apihub.agnes-ai.com/v1",
                  "model_id": "claude-sonnet-4-20250514",
                  "api_key_env": "AGNES_API_KEY"}}})
    assert resp.status_code == 200, resp.text
    cfg = fleet_toml.load_config()
    assert cfg.models["agnes"].model_id == "claude-sonnet-4-20250514"


def test_put_still_rejects_sk_shaped_model_id(tc, fleet_env, monkeypatch):
    """窄口径守门仍生效：sk- 20+ 形态拒绝（与 fleet_toml._reject_secret 同源）。"""
    _host(monkeypatch)
    resp = tc.put("/api/config/fleet", json={"models": {
        "leak": {"base_url": "https://x.example/v1",
                 "model_id": "sk-abc1234567890123456789xyz",  # nosec 测试夹具
                 "api_key_env": "X_KEY"}}})
    assert resp.status_code == 422 and resp.json()["reason"] == "PLAINTEXT_SECRET"


def test_put_merges_models_and_keeps_unmentioned(tc, fleet_env, monkeypatch):
    """merge 语义：只提交新模型 → 旧模型/白名单/显式 planner 绑定全部保留。"""
    _host(monkeypatch)
    _write_toml(fleet_env, (
        '[workspace]\nallowed_roots = ["E:/Old"]\n\n'
        '[models.agnes]\nbase_url = "https://a.example/v1"\nmodel_id = "a"\napi_key_env = "A_KEY"\n'
        'priority = 5\n\n'
        '[roles.planner]\nmodels = ["agnes"]\n'))
    resp = tc.put("/api/config/fleet", json={"models": {
        "newm": {"base_url": "https://n.example/v1", "model_id": "n",
                 "api_key_env": "N_KEY"}}})
    assert resp.status_code == 200, resp.text
    cfg = fleet_toml.load_config()
    assert set(cfg.models) == {"agnes", "newm"}        # 未提及的 agnes 保留
    assert cfg.allowed_roots == ["E:/Old"]             # 未提交 workspace → 保留原值
    assert cfg.roles["planner"].models == ["agnes"]    # 显式 planner 绑定不被保底覆盖


def test_put_null_deletes_model_and_cleans_role_refs(tc, fleet_env, monkeypatch):
    """null = 删除模型，角色引用同步清理，无悬空模型名。"""
    _host(monkeypatch)
    _write_toml(fleet_env, (
        '[models.a]\nbase_url = "https://a.example/v1"\nmodel_id = "a"\napi_key_env = "A_KEY"\n'
        '[models.b]\nbase_url = "https://b.example/v1"\nmodel_id = "b"\napi_key_env = "B_KEY"\n'
        '[roles.planner]\nmodels = ["a", "b"]\n'))
    resp = tc.put("/api/config/fleet", json={"models": {"a": None}})
    assert resp.status_code == 200, resp.text
    cfg = fleet_toml.load_config()
    assert set(cfg.models) == {"b"}
    assert cfg.roles["planner"].models == ["b"]


def test_planner_auto_binds_first_model_golden_line(tc, fleet_env, monkeypatch):
    """金线：空配置新装机器 → 只保存一个模型（不带 workspace/roles）→
    planner 自动绑定 → planner_ready()=True（goals.create 409 消除、422 消除）。"""
    _host(monkeypatch)
    monkeypatch.setenv("MAIN_KEY", "test-key-value-000")  # 模拟密钥已写（写后 env 生效）
    resp = tc.put("/api/config/fleet", json={"models": {
        "main": {"base_url": "https://apihub.agnes-ai.com/v1", "model_id": "agnes-3.0-flash",
                 "api_key_env": "MAIN_KEY"}}})
    assert resp.status_code == 200, resp.text
    cfg = fleet_toml.load_config()
    assert cfg.roles["planner"].models == ["main"]     # 保底绑定（唯一模型）

    from fleet.cli.clients import planner_ready
    assert planner_ready() is True                     # 保存模型即可建目标


def test_planner_auto_bind_prefers_lowest_priority(tc, fleet_env, monkeypatch):
    """保底绑定选 priority 最小者（= 最高优先，pool.level 口径：数字小=优先）。"""
    _host(monkeypatch)
    resp = tc.put("/api/config/fleet", json={"models": {
        "slow": {"base_url": "https://s.example/v1", "model_id": "s",
                 "api_key_env": "S_KEY", "priority": 20},
        "fast": {"base_url": "https://f.example/v1", "model_id": "f",
                 "api_key_env": "F_KEY", "priority": 1},
    }})
    assert resp.status_code == 200, resp.text
    cfg = fleet_toml.load_config()
    assert cfg.roles["planner"].models == ["fast"]


def test_allowed_roots_defaults_to_data_workspaces(tc, fleet_env, monkeypatch):
    """P1.3：不提交 workspace 且无任何配置 → 缺省 <data_dir>/workspaces，不再 422。"""
    _host(monkeypatch)
    resp = tc.put("/api/config/fleet", json={"models": {
        "main": {"base_url": "https://apihub.agnes-ai.com/v1", "model_id": "m",
                 "api_key_env": "MAIN_KEY"}}})
    assert resp.status_code == 200, resp.text
    cfg = fleet_toml.load_config()
    assert cfg.allowed_roots == [str(fleet_env["data"] / "workspaces")]
