"""TASK-204：fleet up --open / fleet setup / doctor 修复建议测试。"""

from __future__ import annotations

import json

import pytest

from fleet.cli import main as cli_main


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    monkeypatch.setenv("FLEET_DATA_DIR", str(tmp_path / "data"))
    yield


def test_up_open_opens_browser_once_with_ready_route(monkeypatch):
    """--open：webbrowser.open 调一次；ready=True → /tasks。"""
    opened: list[str] = []
    monkeypatch.setattr("fleet.cli.main._port_open", lambda port: True)  # 复用既有实例
    monkeypatch.setattr("fleet.cli.main._wait_healthy", lambda port, timeout_s=20.0, interval_s=0.5: True)
    monkeypatch.setattr("fleet.cli.main._log_file", lambda name: __import__("pathlib").Path(__import__("tempfile").gettempdir()) / "noop.log")
    monkeypatch.setattr("fleet.cli.main._start_worker_placeholder", lambda: None, raising=False)
    monkeypatch.setattr("fleet.setup.core.status", lambda: {"ready": True, "components": [], "models": [], "harness_auth": [], "platform": "windows"})
    monkeypatch.setattr("webbrowser.open", lambda url: opened.append(url))
    monkeypatch.setattr("time.sleep", lambda s: None)

    # 只跑一遍循环体就退出：up 会死等——用 KeyboardInterrupt 模拟 Ctrl+C
    def fake_sleep_forever(_seconds):
        raise KeyboardInterrupt

    monkeypatch.setattr("time.sleep", fake_sleep_forever)
    code = cli_main.main(["up", "--open", "--no-worker"])
    assert code == 0
    assert len(opened) == 1 and opened[0].endswith("/tasks"), opened


def test_up_open_routes_to_setup_when_not_ready(monkeypatch):
    opened: list[str] = []
    monkeypatch.setattr("fleet.cli.main._port_open", lambda port: True)
    monkeypatch.setattr("fleet.cli.main._wait_healthy", lambda port, timeout_s=20.0, interval_s=0.5: True)
    monkeypatch.setattr("fleet.setup.core.status", lambda: {"ready": False, "components": [], "models": [], "harness_auth": [], "platform": "windows"})
    monkeypatch.setattr("webbrowser.open", lambda url: opened.append(url))

    def fake_sleep_forever(_seconds):
        raise KeyboardInterrupt

    monkeypatch.setattr("time.sleep", fake_sleep_forever)
    assert cli_main.main(["up", "--open", "--no-worker"]) == 0
    assert opened[0].endswith("/setup")


def test_fleet_setup_passthrough(monkeypatch, capsys):
    """fleet setup status --json 与 python -m fleet.setup status --json 输出一致。"""
    from fleet.setup import __main__ as setup_main

    payload = json.dumps({"platform": "windows", "ready": False,
                          "components": [], "models": [], "harness_auth": []}, ensure_ascii=False)
    monkeypatch.setattr("fleet.setup.core.status", lambda: json.loads(payload))

    via_fleet = capsys.readouterr()
    assert cli_main.main(["setup", "status", "--json"]) == 0
    out_via_fleet = capsys.readouterr().out

    import io
    from contextlib import redirect_stdout

    buffer = io.StringIO()
    with redirect_stdout(buffer):
        setup_main.main(["status", "--json"])
    assert json.loads(out_via_fleet) == json.loads(buffer.getvalue())


def test_doctor_suggests_fleet_setup_install(monkeypatch, capsys):
    """doctor 对缺失 codex 输出可复制的 `fleet setup install codex`。"""
    monkeypatch.setattr("fleet.harness.available_profiles", lambda: ["codex"])
    from fleet.harness.profile import HarnessProfile

    profile = HarnessProfile(name="codex", detect=["codex", "--version"],
                             invoke=["codex", "exec"])
    monkeypatch.setattr("fleet.harness.load_profile", lambda name: profile)
    monkeypatch.setattr("fleet.harness.detect", lambda profile: (False, "未安装: codex"))

    code = cli_main.main(["doctor"])
    out = capsys.readouterr().out
    assert code == 1
    assert "fleet setup install codex" in out
