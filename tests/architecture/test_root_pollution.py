"""根目录白名单守门（TASK-002）：仓库根不允许出现白名单之外的条目。

运行时目录（data/、.venv、__pycache__ 等）显式豁免；其余任何新条目（误提交的
临时文件、人格模板回潮、脚本产物落错位置）都会让本测试失败。
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

ALLOWED_ENTRIES = {
    # 目录（源码/契约/配置）
    ".github", "config", "database", "docs", "fleet", "packages", "scripts", "tests", "tests-e2e",
    # 根文件
    ".env.example", ".gitignore", "AGENTS.md", "Makefile", "make.ps1",
    "README.md", "pyproject.toml", "requirements.txt", "run_interactive.py",
    # 运行时/本地产物（豁免，不入库也不算污染）
    ".git", ".venv", ".pytest_cache", "__pycache__", "build", "dist", "data",
    ".claude", ".zcode", "node_modules",
    # 本地运行时配置与 pip 可编辑安装产物（均 gitignore）
    ".env", "aideanfleet.egg-info",
}


def test_root_entries_within_allowlist():
    actual = {entry.name for entry in ROOT.iterdir()}
    unexpected = actual - ALLOWED_ENTRIES
    assert not unexpected, (
        f"仓库根出现白名单之外的条目: {sorted(unexpected)}；"
        "若是临时产物请加入 .gitignore 并移出根目录，若是新目录请更新白名单"
    )
