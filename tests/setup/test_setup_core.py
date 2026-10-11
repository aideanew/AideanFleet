"""TASK-202：fleet.setup 核心测试（假 npm 可执行文件驱动，全程离线）。"""

from __future__ import annotations

import json
import stat
import time
from pathlib import Path

import pytest

from fleet.setup import core


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    monkeypatch.setenv("FLEET_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setattr(core, "runtime_dir", lambda: tmp_path / "runtime")
    monkeypatch.setattr(core, "_probe_version", lambda cmd, pattern=r"(\d+\.\d+(?:\.\d+)?)": "")
    yield
    with core._JOB_LOCK:
        core._RUNNING_JOB["id"] = None


def _write_fake_npm(directory: Path, *, fail: bool = False) -> Path:
    """假 npm：退出码可控，输出版本行。"""
    directory.mkdir(parents=True, exist_ok=True)
    npm = directory / "npm.cmd"
    body = "@echo off\r\n"
    if fail:
        body += "echo simulated npm failure 1>&2\r\nexit /b 1\r\n"
    else:
        body += "echo fake-npm ok\r\nexit /b 0\r\n"
    npm.write_text(body, encoding="utf-8")
    return npm


def test_status_shape_matches_contract(fleet_env):
    from tests.contracts.validator import load_schema, validate
    from pathlib import Path as _P

    contracts = _P(__file__).resolve().parents[2] / "packages" / "contracts"
    payload = core.status()
    schema = load_schema("schemas/setup-status.json", contracts)
    errors = validate(payload, schema, root_dir=contracts)
    assert errors == [], errors
    assert payload["platform"] == "windows"
    assert any(c["name"] == "python" for c in payload["components"])


def test_install_success_writes_job_steps(fleet_env, tmp_path, monkeypatch):
    fake_npm = _write_fake_npm(tmp_path, fail=False)
    monkeypatch.setattr(core, "_private_npm", lambda: str(fake_npm))
    monkeypatch.setattr(core, "_npm_registry", lambda mirror, entry: ["https://registry.example"])
    # 安装成功后探测必须能看到组件：假 which + 假版本
    monkeypatch.setattr(core, "shutil_which", lambda name: str(tmp_path / "fake-codex") if name == "codex" else None)
    monkeypatch.setattr(core, "_probe_version", lambda cmd, pattern=r"(\d+\.\d+(?:\.\d+)?)": "0.1.0")

    job_id = core.install_components(["codex"], mirror="official")
    deadline = time.time() + 15
    while time.time() < deadline:
        job = core.read_job(job_id)
        if job and job["state"] in ("succeeded", "failed"):
            break
        time.sleep(0.1)
    assert job["state"] == "succeeded", job
    states = {s["component"]: s["state"] for s in job["steps"]}
    assert states["codex"] in ("succeeded", "skipped")  # POST_INSTALL_NOT_ON_PATH 会让 detect 失败


def test_install_npm_failure_maps_error_code(fleet_env, tmp_path, monkeypatch):
    fake_npm = _write_fake_npm(tmp_path, fail=True)
    monkeypatch.setattr(core, "_private_npm", lambda: str(fake_npm))
    monkeypatch.setattr(core, "_npm_registry", lambda mirror, entry: ["https://registry.example"])

    job_id = core.install_components(["codex"], mirror="official")
    deadline = time.time() + 15
    job = None
    while time.time() < deadline:
        job = core.read_job(job_id)
        if job and job["state"] in ("succeeded", "failed"):
            break
        time.sleep(0.1)
    assert job["state"] == "failed"
    step = next(s for s in job["steps"] if s["component"] == "codex" and s["state"] == "failed")
    assert step["error_code"] == "NPM_INSTALL_FAILED"


def test_second_install_rejected_while_running(fleet_env, tmp_path, monkeypatch):
    """同时发起第二个 install → INSTALL_IN_PROGRESS（契约 errors.json）。"""
    from fleet.setup.core import InstallInProgress

    slow = tmp_path / "slow-npm.cmd"
    slow.write_text("@echo off\r\nping -n 3 127.0.0.1 >nul\r\nexit /b 0\r\n", encoding="utf-8")
    monkeypatch.setattr(core, "_private_npm", lambda: str(slow))
    monkeypatch.setattr(core, "_npm_registry", lambda mirror, entry: ["https://registry.example"])

    job_id = core.install_components(["codex"])
    with pytest.raises(InstallInProgress):
        core.install_components(["codex"])
    # 等作业收尾，清理并发位
    deadline = time.time() + 20
    while time.time() < deadline:
        job = core.read_job(job_id)
        if job and job["state"] in ("succeeded", "failed"):
            break
        time.sleep(0.2)


def test_official_script_component_is_skipped_not_executed(fleet_env, tmp_path, monkeypatch):
    """MN-02：official_script（grok）绝不代跑远程脚本 → skipped + 引导文案。"""
    fake_npm = _write_fake_npm(tmp_path, fail=False)
    monkeypatch.setattr(core, "_private_npm", lambda: str(fake_npm))
    core.note_explicit(["grok"])
    job_id = core.install_components(["grok"], mirror="auto")
    deadline = time.time() + 10
    job = None
    while time.time() < deadline:
        job = core.read_job(job_id)
        if job and job["state"] in ("succeeded", "failed"):
            break
        time.sleep(0.1)
    steps = [s for s in job["steps"] if s["component"] == "grok"]
    assert [s["state"] for s in steps][-1] == "skipped", steps
