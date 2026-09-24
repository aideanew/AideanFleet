"""watchdog 测试（REL-01 §9.2）：探活判死、自动拉起、rel:restart 事件、防风暴 rel:escalate。
含一个真实 kill-拉起演练（子进程 HTTP 服务 + 真实 Popen，非 mock）。"""

from __future__ import annotations

import socket
import subprocess
import sys
import threading
import time
import urllib.request

import pytest

from fleet.rel.watchdog import Watchdog, WatchdogConfig, spawn_for_console

from tests.rel.conftest import read_events


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _make(fleet_env, config_overrides: dict) -> Watchdog:
    base = dict(
        port=5999,
        interval=0.0,
        max_failures=3,
        restart_window=300.0,
        max_restarts=3,
        sleep=lambda *_: None,
        now=time.monotonic,
    )
    base.update(config_overrides)
    return Watchdog(WatchdogConfig(**base))


def test_probe_failure_threshold_triggers_restart_and_event(fleet_env):
    """连续 max_failures 次探活失败 -> 判死 -> 拉起 + rel:restart 事件（注入 spawner，无真进程）。"""
    spawns: list[list[str]] = []

    def spawner(cmd):
        spawns.append(cmd)

        class FakeChild:
            pid = 40000 + len(spawns)

        return FakeChild()

    wd = _make(fleet_env, {"probe": lambda url: False, "spawner": spawner, "restart_cmd": ["fake", "cmd"]})
    summary = wd.run(max_cycles=4)

    assert summary["restarts"] == 1  # 第 3 拍满 3 次失败判死重启 1 次；第 4 拍失败计数 1，不再触发
    assert summary["escalated"] is False
    assert len(spawns) == 2  # 启动时预拉起 1 次 + 判死后重启 1 次（watchdog 自己负责把服务带起来）
    assert spawns == [["fake", "cmd"], ["fake", "cmd"]]
    restarts = [row for row in read_events() if row["action"] == "rel:restart"]
    assert len(restarts) == 1
    extra = restarts[0]["extra"]
    assert extra["restarts"] == 1 and extra["old_pid"] == 40001 and extra["new_pid"] == 40002
    assert extra["port"] == 5999


def test_healthy_probe_never_restarts(fleet_env):
    """探活全绿：零重启、零 rel:restart 事件。"""
    wd = _make(fleet_env, {"probe": lambda url: True})
    summary = wd.run(max_cycles=5)
    assert summary["restarts"] == 0 and summary["escalated"] is False
    assert not [row for row in read_events() if row["action"] in ("rel:restart", "rel:escalate")]


def test_storm_guard_stops_and_escalates(fleet_env):
    """防风暴：窗口内重启达到 max_restarts 后停止拉起，写 rel:escalate 等人工。"""

    def spawner(cmd):
        class FakeChild:
            pid = 50000 + time.monotonic_ns() % 1000

        return FakeChild()

    wd = _make(
        fleet_env,
        {
            "probe": lambda url: False,
            "spawner": spawner,
            "restart_cmd": ["fake"],
            "max_failures": 1,  # 每拍都判死 -> 每拍都尝试重启
            "restart_window": 300.0,
            "max_restarts": 3,
        },
    )
    summary = wd.run(max_cycles=10)

    assert summary["escalated"] is True
    assert wd.stopped is True
    assert summary["restarts"] == 3  # 第 4 次尝试被风暴闸门拦下
    actions = [row["action"] for row in read_events()]
    assert actions.count("rel:restart") == 3
    assert actions.count("rel:escalate") == 1
    escalate = [row for row in read_events() if row["action"] == "rel:escalate"][0]
    assert escalate["extra"]["max_restarts"] == 3 and escalate["extra"]["port"] == 5999


def test_real_kill_and_revive_drill(fleet_env):
    """实杀实拉演练：watchdog 在线程里监视真实子进程；kill 子进程 -> 自动拉起新进程（新 pid、端口复活）。"""
    port = _free_port()
    cmd = [sys.executable, "-m", "tests.rel.drill_target", str(port)]

    def probe(url: str) -> bool:
        try:
            with urllib.request.urlopen(url, timeout=1) as resp:
                return resp.status == 200
        except OSError:
            return False

    config = WatchdogConfig(
        port=port,
        interval=0.2,
        max_failures=2,
        restart_window=300.0,
        max_restarts=3,
        restart_cmd=cmd,
        spawner=lambda arguments: subprocess.Popen(arguments),
        probe=probe,  # 真实 HTTP 探活（与 _default_probe 同语义），显式注入仅为收紧超时
        sleep=time.sleep,
        now=time.monotonic,
    )
    wd = Watchdog(config)
    thread = threading.Thread(target=wd.run, daemon=True)
    thread.start()

    # 等第一个子进程探活通过
    deadline = time.time() + 15
    while time.time() < deadline and (wd.child is None or not probe(wd.health_url)):
        time.sleep(0.1)
    assert wd.child is not None, "watchdog 未能在时限内拉起第一个子进程"
    first_pid = wd.child.pid

    # 实杀
    wd.child.kill()
    wd.child.wait(timeout=10)
    assert not probe(wd.health_url), "kill 后端口仍存活？"

    # 等自动拉起（interval 0.2s × 2 次失败判死 + 拉起就绪）
    deadline = time.time() + 20
    while time.time() < deadline:
        child = wd.child
        if child is not None and child.pid != first_pid and probe(wd.health_url):
            break
        time.sleep(0.1)
    else:
        pytest.fail("watchdog 未能在时限内自动拉起新进程")

    assert wd.restarts == 1
    restarts = [row for row in read_events() if row["action"] == "rel:restart"]
    assert len(restarts) == 1
    assert restarts[0]["extra"]["old_pid"] == first_pid
    assert restarts[0]["extra"]["new_pid"] not in (None, first_pid)

    # 清理：停 watchdog 与子进程
    wd.stopped = True
    try:
        wd.child.terminate()
        wd.child.wait(timeout=5)
    except Exception:
        pass


def test_spawn_for_console_builds_detached_process(monkeypatch):
    """launch_core 挂载点：spawn_for_console 生成 `python -m fleet.rel.watchdog` 子进程命令。"""
    captured: dict = {}

    def fake_popen(cmd, creationflags=0):
        captured["cmd"] = cmd
        captured["flags"] = creationflags

        class FakeChild:
            pid = 424242

        return FakeChild()

    monkeypatch.setattr("fleet.rel.watchdog.subprocess.Popen", fake_popen)
    child = spawn_for_console(5000)
    assert child.pid == 424242
    assert captured["cmd"][:3] == [sys.executable, "-m", "fleet.rel.watchdog"]
    assert "--port" in captured["cmd"] and "5000" in captured["cmd"]
