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

    class FakeOpener:
        def open(self, req, timeout=None):
            data = payload if "/api/health" in req.full_url else {"name": "Hermes-Manager"}
            return io.BytesIO(json.dumps(data).encode())

    # _health_check 自建 loopback opener（TASK-106）：在 build_opener 层打桩
    monkeypatch.setattr(urllib.request, "build_opener", lambda *handlers: FakeOpener())
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


def test_ensure_env_file_migrates_port_5000_to_3100(tmp_path, monkeypatch, capsys):
    """ADR-005：存量 .env 中恰为 5000 的 FLEET_CONSOLE_PORT 自动迁移为 3100；其他值不动。"""
    from fleet.core import paths as paths_mod

    root = tmp_path / "fleet-root"
    root.mkdir()
    (root / ".env.example").write_text("FLEET_CONSOLE_PORT=3100\n", encoding="utf-8")
    env_file = root / ".env"
    env_file.write_text(
        "FLEET_CONSOLE_PORT=5000\nFLEET_SCHEDULER=0\n", encoding="utf-8"
    )
    monkeypatch.setenv("FLEET_ROOT", str(root))
    monkeypatch.setenv("FLEET_DATA_DIR", str(root / "data"))
    paths_mod._CACHE = None  # paths() 每次读 env，无需缓存失效；保险起见不依赖

    assert lc._ensure_env_file() is True
    text = env_file.read_text(encoding="utf-8")
    assert "FLEET_CONSOLE_PORT=3100" in text
    assert "FLEET_CONSOLE_PORT=5000" not in text
    assert "FLEET_SCHEDULER=0" in text  # 显式 0 不被 A1 迁移覆盖

    # 5050 等自定义值不被改写
    env_file.write_text("FLEET_CONSOLE_PORT=5050\n", encoding="utf-8")
    assert lc._ensure_env_file() is True
    assert "FLEET_CONSOLE_PORT=5050" in env_file.read_text(encoding="utf-8")


def test_health_check_bypasses_proxy(monkeypatch):
    """TASK-106（F-07）：HTTP_PROXY 指向不可达地址时，回环探活仍成功。"""
    import json as json_mod
    import threading
    from http.server import BaseHTTPRequestHandler, HTTPServer

    monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:9")
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:9")

    class _Health(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            body = json_mod.dumps(
                {"version": "0.3.0", "db": True, "events": True, "config": True}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = HTTPServer(("127.0.0.1", 0), _Health)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        health = lc._health_check(port, port)
        assert health["console"] is True, "回环探活被代理劫持（F-07 回归）"
    finally:
        server.shutdown()
