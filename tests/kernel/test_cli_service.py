"""fleet service（用户级开机自启）测试：Startup 目录注入、幂等安装/卸载、
脚本内容（FLEET_WATCHDOG=1 + up --open + 最小化）、CLI 子命令解析。
不触真实 Startup 目录、不写注册表、不用 schtasks（免管理员设计）。
"""

from __future__ import annotations

import pytest

import fleet.cli.main as cli_main
from fleet.cli import service


@pytest.fixture()
def fake_startup(tmp_path, monkeypatch):
    """把 Startup 目录指到 tmp_path，隔离真实用户目录。"""
    monkeypatch.setenv("APPDATA", str(tmp_path))
    target = tmp_path / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"
    return target


def test_install_writes_script_with_watchdog_and_open(fake_startup):
    result = service.install()
    assert result["installed"] is True and result["overwritten"] is False
    script = fake_startup / service.SERVICE_NAME
    assert script.is_file()
    content = script.read_text(encoding="ascii")
    assert "set FLEET_WATCHDOG=1" in content
    assert "up --open" in content
    assert "/min" in content  # 最小化窗口启动


def test_install_is_idempotent_overwrite(fake_startup):
    service.install()
    result = service.install()
    assert result["overwritten"] is True  # 幂等：二次安装覆盖


def test_uninstall_removes_and_is_idempotent(fake_startup):
    service.install()
    result = service.uninstall()
    assert result["removed"] is True
    assert not (fake_startup / service.SERVICE_NAME).exists()
    again = service.uninstall()
    assert again["removed"] is False and "reason" in again  # 未安装再卸：幂等


def test_status_reflects_state(fake_startup):
    assert service.status()["installed"] is False
    service.install()
    assert service.status()["installed"] is True
    service.uninstall()
    assert service.status()["installed"] is False


def test_cli_parser_has_service_subcommands():
    """argparse 装配：service install/uninstall/status 三入口。"""
    parser = cli_main.build_parser()
    args = parser.parse_args(["service", "install"])
    assert args.func is cli_main.cmd_service and args.service_action == "install"
    args2 = parser.parse_args(["service", "status"])
    assert args2.service_action == "status"


def test_cli_service_roundtrip(fake_startup, capsys):
    """CLI 端到端：install → status → uninstall 输出可读、状态正确。"""
    ns_install = cli_main.build_parser().parse_args(["service", "install"])
    assert cli_main.cmd_service(ns_install) == 0
    assert "已安装" in capsys.readouterr().out
    ns_status = cli_main.build_parser().parse_args(["service", "status"])
    cli_main.cmd_service(ns_status)
    assert "已安装" in capsys.readouterr().out
    ns_rm = cli_main.build_parser().parse_args(["service", "uninstall"])
    cli_main.cmd_service(ns_rm)
    assert "已移除" in capsys.readouterr().out
