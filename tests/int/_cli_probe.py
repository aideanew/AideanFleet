"""CLI 探测共享工具：shutil.which + skip + 版本采集。

tests/core/test_resolve_integration.py 和 tests/int/test_integration验收.py
共用此模块，确保 skip 口径一致、不漂移。
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from dataclasses import dataclass


@dataclass
class CliProbeResult:
    """单个 CLI 的探测结果"""
    name: str
    available: bool
    version_output: str = ""
    returncode: int = -1
    skip_reason: str = ""


# 本机已知 CLI 清单（名称 → shutil.which 查找键）
KNOWN_CLIS: dict[str, str] = {
    "claude": "claude",
    "codex": "codex",
    "opencode": "opencode",
    "hermes": "hermes",
    "cline": "cline",
    "gemini": "gemini",
    "grok": "grok",
}


def probe_cli(name: str, which_key: str | None = None) -> CliProbeResult:
    """探测单个 CLI 是否可用并采集版本输出。

    与 test_resolve_integration.py 口径一致：
    - shutil.which() 为 None → skip（reason = 实测结论）
    - 可用 → 运行 ``{cmd} --version``，记录原样输出
    """
    key = which_key or name
    path = shutil.which(key)
    if path is None:
        return CliProbeResult(
            name=name,
            available=False,
            skip_reason=f"{key} 未安装（shutil.which 返回 None，本机实测）",
        )

    try:
        result = subprocess.run(
            [key, "--version"],
            capture_output=True,
            timeout=30,
            shell=True,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except FileNotFoundError:
        return CliProbeResult(
            name=name,
            available=False,
            skip_reason=f"{key} 在 PATH 中找到 ({path}) 但执行失败",
        )
    except subprocess.TimeoutExpired:
        return CliProbeResult(
            name=name,
            available=False,
            skip_reason=f"{key} --version 超时（30s）",
        )

    # 多编码解码（Windows GBK 兼容）
    output = ""
    raw = result.stdout or b""
    for enc in ("utf-8", "gbk", "latin-1"):
        try:
            output = raw.decode(enc).strip()
            break
        except (UnicodeDecodeError, AttributeError):
            continue

    # 合并 stderr
    stderr_raw = result.stderr or b""
    for enc in ("utf-8", "gbk", "latin-1"):
        try:
            stderr_text = stderr_raw.decode(enc).strip()
            if stderr_text:
                output = f"{output}\n{stderr_text}".strip()
            break
        except (UnicodeDecodeError, AttributeError):
            continue

    return CliProbeResult(
        name=name,
        available=result.returncode == 0,
        version_output=output,
        returncode=result.returncode,
        skip_reason="" if result.returncode == 0 else f"{key} --version 返回非零: {output}",
    )


def probe_all() -> dict[str, CliProbeResult]:
    """探测所有已知 CLI"""
    return {name: probe_cli(name, key) for name, key in KNOWN_CLIS.items()}


def skip_if_unavailable(name: str) -> None:
    """若 CLI 不可用则 pytest.skip（与 test_resolve_integration.py 口径一致）"""
    result = probe_cli(name)
    if not result.available:
        import pytest
        pytest.skip(result.skip_reason)
