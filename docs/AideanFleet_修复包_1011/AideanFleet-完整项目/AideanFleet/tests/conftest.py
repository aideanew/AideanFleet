"""会话级快照：记录 pytest 启动时的 git status，供"测试不改写已跟踪文件"守门测试比对。

快照在任何测试运行前生成（本模块被 import 时即快照——pytest 收集阶段）。
"""

from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def git_porcelain() -> str | None:
    try:
        result = subprocess.run(
            ["git", "-C", str(ROOT), "status", "--porcelain"],
            capture_output=True, text=True, timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    return result.stdout


#: 收集阶段快照（import 时执行一次）
PORCELAIN_AT_START = git_porcelain()


def _tracked_mutations(porcelain: str) -> list[str]:
    lines = []
    for line in (porcelain or "").splitlines():
        if not line.strip():
            continue
        if line[:2].strip() in ("", "?"):
            continue  # 未跟踪不算改写
        lines.append(line)
    return lines


def pytest_sessionfinish(session, exitstatus):
    """会话结束守门（审计修复）：test_tests_do_not_mutate_tracked_files 位于 tests/architecture，
    按收集顺序最先运行，看不到之后测试造成的改写（F-11 在 Linux 上复现即因此漏检）。
    这里在全部测试结束后再比对一次，有新增改写则把退出码置为失败。"""
    if PORCELAIN_AT_START is None:
        return
    after = git_porcelain()
    if after is None:
        return
    before = set(_tracked_mutations(PORCELAIN_AT_START))
    new = [line for line in _tracked_mutations(after) if line not in before]
    if new:
        reporter = session.config.pluginmanager.get_plugin("terminalreporter")
        message = f"测试改写了已跟踪文件（REQ-NF-07）: {new}"
        if reporter is not None:
            reporter.write_line(message, red=True)
        session.exitstatus = 1
