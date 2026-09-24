"""启动器测试完全隔离，不启动服务、不改写真实项目数据。"""

import importlib
import io
import json
import sys

import pytest

lc = importlib.import_module("fleet.launcher.launch_core")


@pytest.fixture
def isolated_launch(monkeypatch, tmp_path):
    monkeypatch.setattr(lc, "_probe_versions", lambda: {"python": "test"})
    monkeypatch.setattr(lc, "_check_port", lambda port: False)
    monkeypatch.setattr(lc, "_ensure_env_file", lambda: True)
    monkeypatch.setattr(lc, "_start_console", lambda port: True)
    monkeypatch.setattr(lc, "_start_manager_gateway", lambda port: False)
    monkeypatch.setattr(lc, "_health_check", lambda *args: {"console": True, "manager": False})
    monkeypatch.setattr(lc, "_register_project", lambda *args: "Demo")
    monkeypatch.setattr(lc, "_open_browser", lambda port: None)
    monkeypatch.setattr(lc, "_start_watch_events_loop", lambda pid: None)
    monkeypatch.setattr(lc.time, "sleep", lambda _: None)
    monkeypatch.delenv("FLEET_WATCHDOG", raising=False)
    return lc.LaunchRequest(project="Demo", project_path=str(tmp_path / "Demo"), mode="run", port=19997)


@pytest.mark.parametrize("payload,healthy", [
    ({"version": "0.3.0", "db": True, "events": True, "config": True}, True),
    ({"version": "0.3.0", "db": False, "events": True, "config": True}, False),
    ({"status": "ok"}, False),
    ({"version": "0.3.0", "db": "true", "events": True, "config": True}, False),
])
def test_health_contract(monkeypatch, payload, healthy):
    import urllib.request

    def response(req, timeout):
        data = payload if "/api/health" in req.full_url else {"name": "Hermes-Manager"}
        return io.BytesIO(json.dumps(data).encode())

    monkeypatch.setattr(urllib.request, "urlopen", response)
    assert lc._health_check(19997, 19998) == {"console": healthy, "manager": True}


def test_start_console_propagates_port(monkeypatch):
    calls = []
    monkeypatch.setattr(lc.subprocess, "Popen", lambda *args, **kwargs: calls.append((args, kwargs)))
    assert lc._start_console(19997)
    assert calls[0][1]["env"]["FLEET_CONSOLE_PORT"] == "19997"
    assert calls[0][1]["cwd"] == str(lc.paths().root)


def test_failed_console_stops_before_registration(monkeypatch, isolated_launch):
    monkeypatch.setattr(lc, "_start_console", lambda port: False)
    monkeypatch.setattr(lc, "_health_check", lambda *args: {"console": False, "manager": False})
    monkeypatch.setattr(lc, "_register_project", lambda *args: pytest.fail("启动失败不得注册项目"))
    result = lc.launch_core(isolated_launch)
    assert result["ok"] is False
    assert result["errors"]
    assert not next(s for s in result["steps"] if s["step"] == "start_console")["ok"]


def test_config_failure_stops_startup(monkeypatch, isolated_launch):
    monkeypatch.setattr(lc, "_ensure_env_file", lambda: False)
    monkeypatch.setattr(lc, "_start_console", lambda port: pytest.fail("配置失败不得启动服务"))
    assert lc.launch_core(isolated_launch)["ok"] is False


def test_launch_uses_requested_port_and_reports_degradation(monkeypatch, isolated_launch):
    ports = []
    monkeypatch.setattr(lc, "_start_console", lambda port: ports.append(port) or True)
    monkeypatch.setattr(lc, "_open_browser", lambda port: ports.append(port))
    result = lc.launch_core(isolated_launch)
    assert result["ok"]
    assert ports == [19997, 19997]
    assert result["warnings"]
    assert result["console_url"] == "http://127.0.0.1:19997/"
    assert not next(s for s in result["steps"] if s["step"] == "start_manager_gateway")["ok"]


def test_occupied_console_is_reused_only_when_healthy(monkeypatch, isolated_launch):
    monkeypatch.setattr(lc, "_check_port", lambda port: port == 19997)
    monkeypatch.setattr(lc, "_start_console", lambda port: pytest.fail("不得重复启动已占用端口"))
    assert lc.launch_core(isolated_launch)["ok"]


def test_launch_survives_gbk_console_stdout(monkeypatch, isolated_launch):
    """Windows 默认 GBK 控制台下打印 ✓/✗/⚠ 曾抛 UnicodeEncodeError 中断启动。"""
    gbk_out = io.TextIOWrapper(io.BytesIO(), encoding="gbk")
    monkeypatch.setattr(sys, "stdout", gbk_out)
    monkeypatch.setattr(sys, "stderr", gbk_out)
    result = lc.launch_core(isolated_launch)
    gbk_out.flush()
    text = gbk_out.buffer.getvalue().decode("utf-8")
    assert result["ok"] is True
    assert "✓ Fleet启动完成" in text
    assert "http://127.0.0.1:19997/" in text


def test_configure_stdio_skips_non_reconfigurable_stream(monkeypatch):
    """pytest 捕获等无 reconfigure 的流必须静默跳过，不能抛异常。"""
    monkeypatch.setattr(sys, "stdout", io.StringIO())
    monkeypatch.setattr(sys, "stderr", io.StringIO())
    lc._configure_stdio()


def test_child_env_forces_utf8_output(monkeypatch):
    """控制台子进程继承 PYTHONIOENCODING=utf-8，避免其自身打印符号崩溃。"""
    monkeypatch.delenv("PYTHONIOENCODING", raising=False)
    env = lc._child_env({"FLEET_CONSOLE_PORT": "19997"})
    assert env["PYTHONIOENCODING"] == "utf-8"
    assert env["FLEET_CONSOLE_PORT"] == "19997"
