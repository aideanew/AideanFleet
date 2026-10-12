"""fleet launch 必须带起 worker（回归测试：断链1）。

背景：cmd_launch 曾硬编码 no_worker=True，与安装器 launcher.cmd 跑 `up --open`
（含 worker）的行为相悖——launch 入口启动后内核 todo 永远无人认领，
「无需任何操作，等待实现和测试」在架构上不成立。

锁定两个不变量：
  1. 委托 cmd_up 时 no_worker 必须为 False（worker 要起来）；
  2. open 必须为 True（自动打开浏览器）。
"""

import argparse

import fleet.cli.main as cli_main


def _fake_up(captured: dict):
    def fake(args: argparse.Namespace) -> int:
        captured["open"] = args.open
        captured["no_worker"] = args.no_worker
        return 0

    return fake


def test_cmd_launch_starts_worker(monkeypatch):
    """launch 子解析器只定义 --port；open/no_worker 由 cmd_launch 显式注入。"""
    captured: dict = {}
    monkeypatch.setattr(cli_main, "cmd_up", _fake_up(captured))
    args = argparse.Namespace(port=3100)
    assert cli_main.cmd_launch(args) == 0
    assert captured["open"] is True
    assert captured["no_worker"] is False


def test_cmd_launch_overrides_explicit_no_worker(monkeypatch):
    """即便上游误传 no_worker=True，launch 也必须纠正为带 worker。"""
    captured: dict = {}
    monkeypatch.setattr(cli_main, "cmd_up", _fake_up(captured))
    args = argparse.Namespace(port=3100, open=False, no_worker=True)
    assert cli_main.cmd_launch(args) == 0
    assert captured["open"] is True
    assert captured["no_worker"] is False


def test_cmd_launch_fills_default_port(monkeypatch):
    """无 port 属性时补默认端口（cmd_up 依赖 args.port）。"""
    monkeypatch.setattr(cli_main, "cmd_up", lambda args: 0)
    args = argparse.Namespace()
    assert cli_main.cmd_launch(args) == 0
    assert args.port == cli_main.DEFAULT_PORT
