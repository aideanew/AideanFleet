"""TASK-202：fleet.setup 核心测试（假 npm 可执行文件驱动，全程离线）。"""

from __future__ import annotations

import json
import os
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
    """假 npm：退出码可控，输出版本行。Windows 写 .cmd，POSIX 写可执行 sh 脚本（CI 双平台）。"""
    directory.mkdir(parents=True, exist_ok=True)
    if os.name == "nt":
        npm = directory / "npm.cmd"
        body = "@echo off\r\n"
        if fail:
            body += "echo simulated npm failure 1>&2\r\nexit /b 1\r\n"
        else:
            body += "echo fake-npm ok\r\nexit /b 0\r\n"
        npm.write_text(body, encoding="utf-8")
        return npm
    npm = directory / "npm"
    if fail:
        body = "#!/bin/sh\necho simulated npm failure 1>&2\nexit 1\n"
    else:
        body = "#!/bin/sh\necho fake-npm ok\nexit 0\n"
    npm.write_text(body, encoding="utf-8")
    npm.chmod(npm.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return npm


def _write_slow_npm(directory: Path) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    if os.name == "nt":
        slow = directory / "slow-npm.cmd"
        slow.write_text("@echo off\r\nping -n 3 127.0.0.1 >nul\r\nexit /b 0\r\n", encoding="utf-8")
        return slow
    slow = directory / "slow-npm"
    slow.write_text("#!/bin/sh\nsleep 2\nexit 0\n", encoding="utf-8")
    slow.chmod(slow.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return slow


def test_status_shape_matches_contract(fleet_env):
    from tests.contracts.validator import load_schema, validate
    from pathlib import Path as _P

    contracts = _P(__file__).resolve().parents[2] / "packages" / "contracts"
    payload = core.status()
    schema = load_schema("schemas/setup-status.json", contracts)
    errors = validate(payload, schema, root_dir=contracts)
    assert errors == [], errors
    expected = "windows" if os.name == "nt" else ("macos" if core.sys_platform() == "darwin" else "linux")
    assert payload["platform"] == expected
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

    slow = _write_slow_npm(tmp_path)
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


def _wait_terminal(job_id, timeout=15):
    deadline = time.time() + timeout
    job = None
    while time.time() < deadline:
        job = core.read_job(job_id)
        if job and job["state"] in ("succeeded", "failed"):
            return job
        time.sleep(0.1)
    return job


def test_unexpected_exception_does_not_wedge_job(fleet_env, tmp_path, monkeypatch):
    """审计回归：安装线程意外异常（如 PermissionError）→ 作业终态 failed 且锁释放，可再次安装。"""
    def boom(*args, **kwargs):
        raise PermissionError(13, "Permission denied")

    monkeypatch.setattr(core, "_private_npm", lambda: str(tmp_path / "npm-no-exec"))
    monkeypatch.setattr(core, "_npm_registry", lambda mirror, entry: ["https://registry.example"])
    monkeypatch.setattr(core.subprocess, "run", boom)
    job = _wait_terminal(core.install_components(["codex"], mirror="official"))
    assert job["state"] == "failed", job
    assert any(s.get("error_code") == "NPM_INSTALL_FAILED" for s in job["steps"])
    # 锁已释放：第二次安装不报 INSTALL_IN_PROGRESS
    second = core.install_components(["codex"], mirror="official")
    assert _wait_terminal(second)["state"] == "failed"


def test_default_off_component_skip_is_not_failure(fleet_env, tmp_path, monkeypatch):
    """审计回归：default=false 且未勾选的组件被跳过时，作业不应判为 failed。"""
    manifest = core.load_manifest()
    off = [c["name"] for c in manifest["components"] if c.get("default", True) is False]
    if not off:
        pytest.skip("manifest 中无默认不安装组件")
    monkeypatch.setattr(core, "_EXPLICIT", set())
    job = _wait_terminal(core.install_components([off[0]], mirror="official"))
    assert job["state"] == "succeeded", job
    assert job["steps"][-1]["state"] == "skipped"
