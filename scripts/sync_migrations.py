#!/usr/bin/env python3
"""sync_migrations —— database/migrations/*.sql → fleet/kernel/_migrations/（wheel 打包副本）。

唯一源是 database/migrations；_migrations 是构建期生成物（gitignore），
由 pyproject package-data 打进 wheel（TASK-002 / TASK-101）。
--check：比对源与副本内容，不一致退出码 1。
"""

from __future__ import annotations

import argparse
import filecmp
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "database" / "migrations"
DST = ROOT / "fleet" / "kernel" / "_migrations"
# 审计修复：fleet/setup/core.py 声明 manifest 打包副本由本脚本同步，但此前从未实现，
# 导致 wheel（安装器即用 wheel 安装）缺 _manifest.json，/setup 在安装版上找不到清单。
MANIFEST_SRC = ROOT / "scripts" / "installer" / "manifest.json"
MANIFEST_DST = ROOT / "fleet" / "setup" / "_manifest.json"


def sync() -> list[Path]:
    DST.mkdir(parents=True, exist_ok=True)
    copied = []
    for sql in sorted(SRC.glob("*.sql")):
        target = DST / sql.name
        if not target.exists() or not filecmp.cmp(sql, target, shallow=False):
            shutil.copy2(sql, target)
            copied.append(sql.name)
    for stale in DST.glob("*.sql"):
        if not (SRC / stale.name).exists():
            stale.unlink()
            copied.append(f"-{stale.name}")
    if MANIFEST_SRC.is_file() and (
            not MANIFEST_DST.exists() or not filecmp.cmp(MANIFEST_SRC, MANIFEST_DST, shallow=False)):
        shutil.copy2(MANIFEST_SRC, MANIFEST_DST)
        copied.append(MANIFEST_DST.name)
    return copied


def check() -> int:
    if not DST.exists():
        print("fleet/kernel/_migrations 不存在：先运行 python scripts/sync_migrations.py", file=sys.stderr)
        return 1
    src_files = {p.name: p for p in SRC.glob("*.sql")}
    dst_files = {p.name: p for p in DST.glob("*.sql")}
    if set(src_files) != set(dst_files):
        print(f"迁移副本与源不一致: 源={sorted(src_files)} 副本={sorted(dst_files)}", file=sys.stderr)
        return 1
    for name in src_files:
        if not filecmp.cmp(src_files[name], dst_files[name], shallow=False):
            print(f"迁移副本内容过期: {name}", file=sys.stderr)
            return 1
    if MANIFEST_SRC.is_file():
        if not MANIFEST_DST.is_file() or not filecmp.cmp(MANIFEST_SRC, MANIFEST_DST, shallow=False):
            print("fleet/setup/_manifest.json 缺失或过期：先运行 python scripts/sync_migrations.py",
                  file=sys.stderr)
            return 1
    print("OK 迁移副本与唯一源一致")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="kernel.db 迁移打包同步")
    parser.add_argument("--check", action="store_true", help="只校验不复制")
    args = parser.parse_args()
    if args.check:
        return check()
    changed = sync()
    print("updated:", ", ".join(changed) if changed else "（无变化）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
