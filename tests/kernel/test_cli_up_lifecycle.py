"""cmd_up 单实例与进程生命周期测试（S12）。

S12.1：端口复用（既有控制台在跑）→ 不拉第二个 worker、不覆盖 pidfile（保留原实例进程记录）；
S12.2：watchdog 随 up 拉起（FLEET_WATCHDOG=1 门控）并记入 pidfile，down 先停 watchdog
（避免 watchdog 把刚停下的 api 又拉起）。
"""

from __future__ import annotations

import argparse
import json
import types

import pytest

import fleet.cli.main as cli_main
from fleet.cli import pidutil


class _FakeProc:
    def __init__(self, pid: int) -> None:
        self.pid = pid


@pytest.fixture()
def up_env(tmp_path, monkeypatch):
    """隔离 cmd_up 的外部效应：日志→tmp、pidfile→内存 spy、Popen→fake、sleep→打断前台循环。"""
    recorded: dict = {"spawns": [], "pidfile": []}

    def _fake_popen(cmd, **kw):
        recorded["spawns"].append(list(cmd))
        return _FakeProc(4000 + len(recorded["spawns"]))

    monkeypatch.setattr(cli_main, "_log_file", lambda name: tmp_path / f"{name}.log")
    monkeypatch.setattr(cli_main, "write_pidfile",
                        lambda info: recorded["pidfile"].append(dict(info)))
    monkeypatch.setattr(cli_main, "_wait_healthy", lambda port: True)
    monkeypatch.setattr(cli_main, "subprocess",
                        types.SimpleNamespace(CREATE_NO_WINDOW=0, STDOUT=-2, Popen=_fake_popen))

    def _interrupt(_s):
        raise KeyboardInterrupt

    monkeypatch.setattr(cli_main.time, "sleep", _interrupt)
    return recorded


def _args(**kw):
    base = {"port": 3999, "open": False, "no_worker": False}
    base.update(kw)
    return argparse.Namespace(**base)


# ---------- S12.1 单实例 ----------

def test_up_reuse_does_not_spawn_worker_or_touch_pidfile(up_env, monkeypatch):
    """端口已占用（复用）→ 不拉 api/worker、不写 pidfile（保留原实例记录，fleet down 仍停原实例）。"""
    monkeypatch.setattr(cli_main, "_port_open", lambda p: True)
    assert cli_main.cmd_up(_args()) == 0
    assert up_env["spawns"] == []
    assert up_env["pidfile"] == []


def test_up_fresh_spawns_api_and_worker_and_writes_pidfile(up_env, monkeypatch):
    """对照：全新启动 → api+worker 各一，pidfile 记录 api/worker pid 与端口。"""
    monkeypatch.setattr(cli_main, "_port_open", lambda p: False)
    assert cli_main.cmd_up(_args()) == 0
    assert len(up_env["spawns"]) == 2
    info = up_env["pidfile"][-1]
    assert info["api"] == 4001 and info["worker"] == 4002
    assert info["port"] == 3999


def test_up_fresh_no_worker(up_env, monkeypatch):
    """--no-worker：仅 api，pidfile worker=None。"""
    monkeypatch.setattr(cli_main, "_port_open", lambda p: False)
    assert cli_main.cmd_up(_args(no_worker=True)) == 0
    assert len(up_env["spawns"]) == 1
    assert up_env["pidfile"][-1]["worker"] is None


# ---------- S12.2 watchdog 生命周期 ----------

def test_up_watchdog_spawned_and_recorded(up_env, monkeypatch):
    """FLEET_WATCHDOG=1 → up 拉起 watchdog 并记入 pidfile（down 可停）。"""
    monkeypatch.setattr(cli_main, "_port_open", lambda p: False)
    monkeypatch.setenv("FLEET_WATCHDOG", "1")
    fake_wd = _FakeProc(9001)
    monkeypatch.setattr("fleet.rel.watchdog.spawn_for_console",
                        lambda port, host="127.0.0.1": fake_wd)
    assert cli_main.cmd_up(_args()) == 0
    info = up_env["pidfile"][-1]
    assert info["watchdog"] == 9001
    assert info["worker"] == 4002  # api/worker 照常


def test_up_watchdog_off_by_default(up_env, monkeypatch):
    """缺省（未设 FLEET_WATCHDOG）不拉 watchdog，pidfile watchdog=None。"""
    monkeypatch.setattr(cli_main, "_port_open", lambda p: False)
    monkeypatch.delenv("FLEET_WATCHDOG", raising=False)
    spawned = []
    monkeypatch.setattr("fleet.rel.watchdog.spawn_for_console",
                        lambda port, host="127.0.0.1": spawned.append(port))
    assert cli_main.cmd_up(_args()) == 0
    assert spawned == []
    assert up_env["pidfile"][-1]["watchdog"] is None


def test_down_stops_watchdog_first(tmp_path, monkeypatch):
    """停止顺序：watchdog → api → worker（防 watchdog 复活 api），pidfile 清理。"""
    pidfile = tmp_path / "fleet.pid"
    pidfile.write_text(json.dumps({"api": 111, "worker": 222, "watchdog": 333, "port": 3999}),
                       encoding="utf-8")
    monkeypatch.setattr(pidutil, "pidfile_path", lambda: pidfile)
    order: list[int] = []
    monkeypatch.setattr(pidutil, "_kill_pid", lambda pid, gentle=True: order.append(pid) or True)
    result = pidutil.stop_fleet()
    assert result["stopped"] is True
    assert order == [333, 111, 222]
    assert not pidfile.exists()
