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
