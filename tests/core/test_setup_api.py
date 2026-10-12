"""TASK-203：Setup API 契约测试（回环限制 + install 作业 + 错误码）。"""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from fleet.console import server as console_server
from fleet.setup import core as setup_core
from tests.contracts.validator import load_schema, validate

CONTRACTS = Path(__file__).resolve().parents[2] / "packages" / "contracts"


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    monkeypatch.setenv("FLEET_DATA_DIR", str(tmp_path / "data"))
    yield
    with core_lock():
        pass


def core_lock():
    from fleet.setup.core import _JOB_LOCK, _RUNNING_JOB

    _RUNNING_JOB["id"] = ""
    _RUNNING_JOB["state"] = ""
    return _JOB_LOCK


@pytest.fixture()
def tc(fleet_env):
    from fastapi.testclient import TestClient

    # 回环 Host 头（loopback.browser_context_ok 校验 Host 防 DNS rebinding）
    return TestClient(console_server.app, base_url="http://127.0.0.1:3100")


def _host(monkeypatch, host: str):
    monkeypatch.setattr("fleet.console.loopback.client_host", lambda request: host)


def test_status_loopback_ok_and_validates(tc, monkeypatch):
    _host(monkeypatch, "127.0.0.1")
    response = tc.get("/api/setup/status")
    assert response.status_code == 200, response.text
    payload = response.json()
    schema = load_schema("schemas/setup-status.json", CONTRACTS)
    errors = validate(payload["status"], schema, root_dir=CONTRACTS)
    assert errors == [], errors


def test_status_non_loopback_403(tc, monkeypatch):
    _host(monkeypatch, "192.168.1.2")
    response = tc.get("/api/setup/status")
    assert response.status_code == 403
    assert response.json()["reason"] == "FORBIDDEN_NON_LOOPBACK"


def test_install_rejects_unknown_component(tc, monkeypatch):
    _host(monkeypatch, "::1")
    response = tc.post("/api/setup/install", json={"components": ["not-a-cli"]})
    assert response.status_code == 422
    assert response.json()["reason"] == "VALIDATION_FAILED"


def test_install_rejects_empty_components(tc, monkeypatch):
    _host(monkeypatch, "127.0.0.1")
    response = tc.post("/api/setup/install", json={"components": []})
    assert response.status_code == 422


def test_install_starts_job_and_job_endpoint_follows(tc, monkeypatch, tmp_path):
    _host(monkeypatch, "127.0.0.1")
    monkeypatch.setattr("platform.machine", lambda: "AMD64")  # 与宿主架构无关（审计：arm64 沙箱曾误判）
    from tests.setup.test_setup_core import _write_fake_npm

    fake_npm = _write_fake_npm(tmp_path, fail=True)  # 失败路径：job 终态 failed
    monkeypatch.setattr(setup_core, "_private_npm", lambda: str(fake_npm))
    monkeypatch.setattr(setup_core, "_npm_registry", lambda mirror, entry: ["https://registry.example"])
    monkeypatch.setattr(setup_core, "shutil_which", lambda name: None)

    response = tc.post("/api/setup/install", json={"components": ["codex"], "mirror": "official"})
    assert response.status_code == 200, response.text
    job_id = response.json()["job_id"]

    deadline = time.time() + 15
    payload = {}
    while time.time() < deadline:
        response = tc.get(f"/api/setup/jobs/{job_id}")
        payload = response.json()
        # 作业线程可能尚未写盘（404 未就绪），轮询直到终态
        if response.status_code == 200 and payload.get("state") in ("succeeded", "failed"):
            break
        time.sleep(0.2)
    assert payload["state"] == "failed"
    assert any(s["error_code"] == "NPM_INSTALL_FAILED" for s in payload["steps"])

    missing = tc.get("/api/setup/jobs/J-NOT-EXIST")
    assert missing.status_code == 404 and missing.json()["reason"] == "JOB_NOT_FOUND"


def test_setup_endpoints_require_loopback_even_for_install(tc, monkeypatch):
    _host(monkeypatch, "10.0.0.5")
    response = tc.post("/api/setup/install", json={"components": ["codex"]})
    assert response.status_code == 403


def test_kernel_goals_still_require_session(tc):
    response = tc.post("/api/kernel/goals", json={"title": "x", "requirements": "y"})
    assert response.status_code == 401


def _config_host(monkeypatch, host):
    monkeypatch.setattr("fleet.console.loopback.client_host", lambda request: host)


def test_config_fleet_put_rejects_non_loopback_and_secret(tc, monkeypatch):
    _config_host(monkeypatch, "10.1.1.1")
    response = tc.put("/api/config/fleet", json={"workspace": {"allowed_roots": ["E:/Demo"]}})
    assert response.status_code == 403

    _config_host(monkeypatch, "127.0.0.1")
    bad = tc.put("/api/config/fleet", json={
        "models": {"x": {"base_url": "https://x/v1", "model_id": "sk-abc1234567890123456789xyz",  # nosec 测试夹具,
                         "api_key_env": "X_KEY"}}})
    assert bad.status_code == 422 and bad.json()["reason"] == "PLAINTEXT_SECRET"


def test_secret_put_writes_write_only_and_validates(tc, monkeypatch):
    _config_host(monkeypatch, "127.0.0.1")
    # 未声明 → 422
    undeclared = tc.put("/api/setup/secrets/NOT_DECLARED_KEY", json={"value": "v"})
    assert undeclared.status_code == 422 and undeclared.json()["reason"] == "SECRET_NAME_NOT_DECLARED"

    from fleet.core import fleet_toml, paths as paths_mod

    cfg = fleet_toml.load_config()
    # 直接构造声明：写一个 fleet.toml
    (paths_mod.paths().root / "fleet.toml").write_text(
        '[models.fake]\nbase_url = "https://x/v1"\nmodel_id = "fake"\napi_key_env = "FAKE_SECRET_ENV"\n',
        encoding="utf-8")
    declared = tc.put("/api/setup/secrets/FAKE_SECRET_ENV", json={"value": "super-secret-value-42"})
    assert declared.status_code == 200 and declared.json()["key_present"] is True

    # 值只写不读：响应体不含明文
    assert "super-secret-value-42" not in declared.text
    secrets_file = paths_mod.paths().data_dir.parent / "secrets" / ".env"
    assert secrets_file.is_file()
    assert "FAKE_SECRET_ENV=super-secret-value-42" in secrets_file.read_text(encoding="utf-8")

    # 全库 grep：值不出现在 data/logs 与 events（写后立即检查）
    events_text = (paths_mod.paths().data_dir / "events.jsonl")
    if events_text.is_file():
        assert "super-secret-value-42" not in events_text.read_text(encoding="utf-8")


def test_model_test_missing_key_and_unknown(tc, monkeypatch):
    _config_host(monkeypatch, "127.0.0.1")
    unknown = tc.post("/api/setup/models/nope/test")
    assert unknown.status_code == 404 and unknown.json()["reason"] == "MODEL_NOT_FOUND"

    from fleet.core import fleet_toml, paths as paths_mod

    (paths_mod.paths().root / "fleet.toml").write_text(
        '[models.needkey]\nbase_url = "http://127.0.0.1:9/v1"\nmodel_id = "m"\napi_key_env = "MISSING_ENV_9"\n',
        encoding="utf-8")
    monkeypatch.delenv("MISSING_ENV_9", raising=False)
    missing = tc.post("/api/setup/models/needkey/test")
    assert missing.status_code == 409 and missing.json()["reason"] == "SECRET_MISSING"


def test_setup_login_launches_console(monkeypatch, tc):
    _config_host(monkeypatch, "127.0.0.1")
    launched: list = []
    monkeypatch.setattr("subprocess.Popen",
                        lambda cmd, creationflags=0: launched.append((cmd, creationflags)))
    ok = tc.post("/api/setup/login/codex")
    assert ok.status_code == 200 and ok.json()["launched"] is True
    assert ok.json()["command"] == "codex login"
    assert launched and launched[0][0] == ["codex", "login"]

    missing = tc.post("/api/setup/login/no-such-harness")
    assert missing.status_code == 404 and missing.json()["reason"] == "HARNESS_NOT_FOUND"


# ---- 审计回归：浏览器跨站 / DNS rebinding 不得触达免会话管理面 ----

@pytest.mark.parametrize("headers", [
    {"Origin": "https://evil.example"},
    {"Origin": "null"},
    {"Sec-Fetch-Site": "cross-site"},
    {"Host": "evil.example:3100"},
])
def test_cross_site_browser_requests_rejected(tc, monkeypatch, headers):
    _host(monkeypatch, "127.0.0.1")
    response = tc.get("/api/setup/status", headers=headers)
    assert response.status_code == 403, response.text
    put = tc.put("/api/config/fleet", content='{"models": {}}',
                  headers={**headers, "Content-Type": "text/plain"})
    assert put.status_code == 403, put.text


def test_same_origin_browser_request_allowed(tc, monkeypatch):
    _host(monkeypatch, "127.0.0.1")
    response = tc.get("/api/setup/status", headers={
        "Origin": "http://127.0.0.1:3100", "Sec-Fetch-Site": "same-origin"})
    assert response.status_code == 200, response.text
