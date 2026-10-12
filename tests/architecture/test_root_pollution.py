"""根目录白名单守门（TASK-002）：仓库根不允许出现白名单之外的条目。

守门语义（v2，跨机器确定性）：
1. 被 git 跟踪的根级条目必须在 TRACKED_ALLOWED 内 —— 拦「意外入库的临时文件/产物目录」；
2. 未跟踪且未被 .gitignore 覆盖的根级条目视为污染 —— 拦「该 ignore 却没 ignore 的新产物」；
3. 未跟踪但已被 .gitignore 覆盖的本地 scratch（.box-agent、DELIVERY 等）豁免 ——
   它们是机器相关的运行时残留，不入库、不算仓库污染（D5 裁决默认口径）。
"""

from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

# 允许被 git 跟踪的根级条目（源码目录 + 根文件）
TRACKED_ALLOWED = {
    # 目录（源码/契约/配置）
    ".github", "config", "database", "docs", "fleet", "packages",
    "scripts", "tests", "tests-e2e",
    # 根文件
    ".env.example", ".gitignore", ".gitattributes", "AGENTS.md", "Makefile",
    "make.ps1", "README.md", "pyproject.toml", "requirements.txt",
    "run_interactive.py",
}


def _git(*args: str) -> list[str]:
    """-z：NUL 分隔输出，非 ASCII 路径不加引号转义。"""
    proc = subprocess.run(
        ["git", *args, "-z"], cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    if proc.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} 失败: {proc.stderr.strip()}")
    return [chunk for chunk in proc.stdout.split("\0") if chunk]


def _tracked_root_entries() -> set[str]:
    return {line.split("/", 1)[0] for line in _git("ls-files")}


def _untracked_not_ignored_root_entries() -> set[str]:
    """git status 默认不显示已忽略文件，?? 即「未跟踪且未忽略」。

    只统计根级条目（路径不含 /）：子目录内部的新文件（如 fleet/core/roots.py）
    属于正常开发产物，不是根目录污染——split("/")[0] 会把顶层目录名误当污染。
    """
    entries: set[str] = set()
    for record in _git("status", "--porcelain", "--untracked-files=normal"):
        # porcelain -z 记录格式：XY<space>path（XY 为两字符状态）
        if len(record) < 4:
            continue
        status, path = record[:2], record[3:]
        if status != "??":
            continue
        path = path.rstrip("/")
        if "/" in path:
            continue
        entries.add(path)
    return entries


def test_root_entries_within_allowlist():
    tracked = _tracked_root_entries()
    bad_tracked = tracked - TRACKED_ALLOWED
    assert not bad_tracked, (
        f"仓库根出现被 git 跟踪但不在白名单内的条目: {sorted(bad_tracked)}；"
        "若是误提交的产物请 git rm 移除，若是新源码目录请同步更新 TRACKED_ALLOWED"
    )

    stray = _untracked_not_ignored_root_entries()
    assert not stray, (
        f"仓库根出现未跟踪且未被 .gitignore 覆盖的条目: {sorted(stray)}；"
        "若是临时产物请加入 .gitignore 并移出根目录，若是新目录请更新白名单"
    )
