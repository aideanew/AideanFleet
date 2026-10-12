"""审计回归：fleet run / run_interactive 的引导默认端口（ADR-005 迁移后曾 NameError）。"""

from __future__ import annotations

from fleet.core.ports import DEFAULT_CONSOLE_PORT
from fleet.launcher import cli_start


def test_cli_start_uses_default_console_port(monkeypatch):
    captured = {}
    monkeypatch.setattr(cli_start, "get_user_input", lambda prompt, default="": default)
    monkeypatch.setattr(cli_start, "_configure_stdio", lambda: None)

    def fake_launch(request):
        captured["port"] = request.port
        return {"ok": True}

    monkeypatch.setattr(cli_start, "launch_core", fake_launch)
    cli_start.main()
    assert captured["port"] == DEFAULT_CONSOLE_PORT == 3100
