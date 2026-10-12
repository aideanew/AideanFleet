"""P1.2：secret 热更新——写钥后无需重启即可用。

断链背景（金线第 3 环）：控制台/worker 进程启动早于用户写钥，
secrets/.env 的导入期一次性注入与 os.environ 均未见新键 →
model_test 409 SECRET_MISSING、goals.create 409 SETUP_INCOMPLETE，
"保存密钥后仍不可用，须重启进程"。

修复口径：
- secret_put 写后同进程 os.environ 热更新；
- key_present / ${VAR} 解析回退 secrets/.env 调用期解析（mtime 缓存）；
- make_planner_client 每次调用重建链（worker 启动后添加的模型立即可见）。
"""

from __future__ import annotations

import pytest

from fleet.console import server as console_server
from fleet.core import fleet_toml


@pytest.fixture(autouse=True)
def _isolate_keys(monkeypatch):
    for name in ("HOT_KEY_A", "HOT_KEY_B"):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture()
def tc(fleet_env):
    from fastapi.testclient import TestClient

    return TestClient(console_server.app, base_url="http://127.0.0.1:3100")


def _host(monkeypatch, host="127.0.0.1"):
    monkeypatch.setattr("fleet.console.loopback.client_host", lambda request: host)


def _write_toml(fleet_env, text):
    (fleet_env["root"] / "fleet.toml").write_text(text, encoding="utf-8")


def _write_secrets(fleet_env, text):
    secrets = fleet_env["data"].parent / "secrets"
    secrets.mkdir(parents=True, exist_ok=True)
    (secrets / ".env").write_text(text, encoding="utf-8")


def test_secret_put_hot_reloads_process_env(tc, fleet_env, monkeypatch):
    """API 写钥 → 同进程 os.environ 立即可见（无需重启控制台）。"""
    _host(monkeypatch)
    import os

    _write_toml(fleet_env, (
        '[models.hot]\nbase_url = "http://127.0.0.1:9/v1"\nmodel_id = "hot-1"\n'
        'api_key_env = "HOT_KEY_A"\n'))
    assert not os.environ.get("HOT_KEY_A")

    resp = tc.put("/api/setup/secrets/HOT_KEY_A", json={"value": "hot-key-value-001"})
    assert resp.status_code == 200, resp.text
    assert os.environ.get("HOT_KEY_A") == "hot-key-value-001"

    # model_test 不再卡 SECRET_MISSING（密钥已解析；URL 不可达属 reachable=False，非 409）
    test_resp = tc.post("/api/setup/models/hot/test")
    assert test_resp.status_code == 200, test_resp.text
    assert test_resp.json()["reachable"] is False  # 127.0.0.1:9 无服务，但密钥已过门


def test_model_cfg_key_present_falls_back_to_secrets_file(fleet_env):
    """fleet_toml.ModelCfg.key_present：env 缺失时回退 secrets/.env（/setup 指示灯）。"""
    _write_secrets(fleet_env, "HOT_KEY_B=file-key-value\n")
    cfg = fleet_toml.ModelCfg(name="m", base_url="https://x/v1", model_id="m",
                              api_key_env="HOT_KEY_B")
    assert cfg.key_present() is True

    cfg_no_env = fleet_toml.ModelCfg(name="m2", base_url="https://x/v1", model_id="m2",
                                     api_key_env="")
    assert cfg_no_env.key_present() is False


def test_planner_ready_via_secrets_file_without_env(fleet_env):
    """planner_ready：模拟 worker 子进程（env 无键、secrets/.env 有键）。"""
    _write_toml(fleet_env, (
        '[models.hot]\nbase_url = "https://x/v1"\nmodel_id = "hot-1"\n'
        'api_key_env = "HOT_KEY_B"\n\n[roles.planner]\nmodels = ["hot"]\n'))
    _write_secrets(fleet_env, "HOT_KEY_B=file-key-value\n")

    from fleet.cli.clients import planner_ready

    assert planner_ready() is True  # 无 os.environ，仅凭 secrets/.env 过门


def test_worker_chain_rebuilt_per_call(fleet_env):
    """make_planner_client 按需构建：构造时无模型 → 报错；补配置后同一 client 立即可用。"""
    from types import SimpleNamespace

    from fleet.cli.clients import make_planner_client

    transport_calls: list = []

    def stub_transport(entry, prompt):
        transport_calls.append((entry.name, prompt))
        return SimpleNamespace(ok=True, text="plan-ok")

    client = make_planner_client(transport_fn=stub_transport)
    with pytest.raises(RuntimeError, match="无任何候选"):
        client("first")

    _write_toml(fleet_env, (
        '[models.hot]\nbase_url = "https://x/v1"\nmodel_id = "hot-1"\n'
        'api_key_env = "HOT_KEY_B"\n\n[roles.planner]\nmodels = ["hot"]\n'))
    _write_secrets(fleet_env, "HOT_KEY_B=file-key-value\n")

    assert client("second") == "plan-ok"  # 链已按需重建，无需重启 worker
    assert transport_calls and transport_calls[0][0] == "hot"


def test_unmask_resolves_from_secrets_file(fleet_env):
    """transport 构钥路径：unmask('${VAR}') env 缺失时回退 secrets/.env。"""
    _write_secrets(fleet_env, "HOT_KEY_A=file-key-value\n")
    from fleet.core import config

    assert config.unmask("${HOT_KEY_A}") == "file-key-value"
    assert config.unmask("${NEVER_SET_KEY_7}") is None


def test_secrets_file_layout(fleet_env):
    """运行期口径：<data_dir>/../secrets/.env（安装器部署 = LOCALAPPDATA）。"""
    from fleet.core import config

    assert config.secrets_file() == fleet_env["data"].parent / "secrets" / ".env"
