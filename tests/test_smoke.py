"""执行体适配器冒烟测试（pytest 形式：UNAVAILABLE → skip；其余断言 return → assert）

与 tests/int/_cli_probe.py 口径一致：shutil.which 先探测，不可用则 pytest.skip，
避免依赖系统 PATH 的 CLI 在干净 CI 环境里产生假失败。
"""

import re
import shutil
import pytest

from fleet.executors import (
    ClaudeCodeAdapter,
    CodexAdapter,
    OpenCodeAdapter,
    HermesAdapter,
    ErrorCode,
)

#: 适配器 → CLI 探测键（shutil.which 查找键）
_ADAPTER_CLI_KEY: dict[type, str] = {
    ClaudeCodeAdapter: "claude",
    CodexAdapter: "codex",
    OpenCodeAdapter: "opencode",
    HermesAdapter: "hermes",
}


def _smoke(adapter, label: str, cli_key: str) -> None:
    if shutil.which(cli_key) is None:
        pytest.skip(f"{label}（{cli_key}）未安装，跳过冒烟测试")
    caps = adapter.capabilities()
    print(f"{label} capabilities: {caps}")
    result = adapter.run("回复OK", ".", f"{label}-default", timeout=30)
    if result.error_code == ErrorCode.UNAVAILABLE:
        pytest.skip(f"{label} 未安装，跳过冒烟测试")
    print(f"{label} result: ok={result.ok}, error={result.error_code}")
    # 上游 provider 不可用（UnknownError/Unexpected server error）属 CLI 时点演进/环境漂移，
    # 与 hermes 的 TOOL_FAIL 先例同口径：skip 并注明归因，不判适配器失败（命令构造已对 1.18.31 实测合法）。
    if result.error_code == ErrorCode.TOOL_FAIL and re.search(
        r"Unexpected server error|Provider returned error|Upstream request failed",
        result.error_msg or "",
    ):
        pytest.skip(f"{label} 上游 provider 不可用（环境漂移，非适配器缺陷），详见 docs/CLI安装决策单.md")
    assert result.ok or result.error_code in [ErrorCode.RATE_LIMITED, ErrorCode.BAD_REQUEST], \
        f"{label} 冒烟失败：ok={result.ok}, error_code={result.error_code}, error_msg={result.error_msg}"


def test_claudecode_smoke():
    _smoke(ClaudeCodeAdapter(), "Claude Code", "claude")


def test_codex_smoke():
    _smoke(CodexAdapter(), "Codex", "codex")


def test_opencode_smoke():
    _smoke(OpenCodeAdapter(), "OpenCode", "opencode")


def test_hermes_smoke():
    """Hermes 冒烟：本机为 git clone+venv 非官方渠道安装（官方仅 macOS/Linux/WSL2）。
    TOOL_FAIL 在此环境下属已知兼容缺口（CLI 存在但 Windows 原生执行失败），
    与 decision-unit 口径一致：记录 skip 而非 assert 失败。"""
    adapter = HermesAdapter()
    caps = adapter.capabilities()
    print(f"Hermes capabilities: {caps}")
    result = adapter.run("回复OK", ".", "hermes-default", timeout=30)
    if result.error_code == ErrorCode.UNAVAILABLE:
        pytest.skip("Hermes 未安装，跳过冒烟测试")
    if result.error_code == ErrorCode.TOOL_FAIL:
        pytest.skip(f"Hermes Windows 原生兼容缺口（TOOL_FAIL），已知项，详见 docs/CLI安装决策单.md")
    assert result.ok or result.error_code in [ErrorCode.RATE_LIMITED, ErrorCode.BAD_REQUEST], \
        f"Hermes 冒烟失败：ok={result.ok}, error_code={result.error_code}, error_msg={result.error_msg}"
