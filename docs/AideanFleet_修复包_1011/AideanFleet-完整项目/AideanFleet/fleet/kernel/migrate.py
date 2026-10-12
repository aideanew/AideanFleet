"""这是什么：kernel.db 迁移执行器（TASK-101）。
怎么用：由 fleet/kernel/store.py 的 init_db 在建表后调用 run(conn)。
设计：
- schema_version(version INTEGER PRIMARY KEY, applied_at TEXT) 记录已应用版本；
- 唯一源 = 仓库 database/migrations/*.sql（开发模式）；wheel 内打包副本 fleet/kernel/_migrations/
  由 scripts/sync_migrations.py 从唯一源同步（构建期生成物，gitignore，内容一致性由 Guard 校验）；
- 每个迁移在事务内执行；幂等：已应用版本跳过；
- 只依赖标准库（import 边界：fleet.kernel 不 import fleet.*）。
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

_PKG_MIGRATIONS = Path(__file__).resolve().parent / "_migrations"
_REPO_MIGRATIONS = Path(__file__).resolve().parents[2] / "database" / "migrations"


def migrations_dir() -> Path:
    """迁移目录：优先仓库唯一源，打包环境（无 database/）退回 _migrations 副本。"""
    if _REPO_MIGRATIONS.is_dir() and any(_REPO_MIGRATIONS.glob("*.sql")):
        return _REPO_MIGRATIONS
    return _PKG_MIGRATIONS


def applied_versions(conn: sqlite3.Connection) -> set[int]:
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_version ("
        "version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)"
    )
    rows = conn.execute("SELECT version FROM schema_version").fetchall()
    return {int(row["version"]) for row in rows}


def run(conn: sqlite3.Connection) -> list[int]:
    """应用所有未执行的迁移，返回本次应用的版本号列表（幂等，可重复调用）。"""
    done = applied_versions(conn)
    applied_now: list[int] = []
    for sql_path in sorted(migrations_dir().glob("*.sql")):
        stem = sql_path.stem
        head = stem.split("_", 1)[0]
        if not head.isdigit():
            continue
        version = int(head)
        if version in done:
            continue
        # 审计修复：executescript 会先 COMMIT 再以自动提交逐句执行，外层 `with conn` 并不包住脚本；
        # 中途失败会留下“半个迁移”且无 schema_version 记录，下次启动因重复列永久失败。
        # 这里把脚本与版本记录放进同一个显式事务，失败整体回滚。
        script = sql_path.read_text(encoding="utf-8")
        # PRAGMA（journal_mode 等）不能在事务内生效，先在事务外执行
        pragmas = [ln for ln in script.splitlines() if ln.strip().upper().startswith("PRAGMA")]
        script = "\n".join(ln for ln in script.splitlines()
                           if not ln.strip().upper().startswith("PRAGMA"))
        for pragma in pragmas:
            conn.execute(pragma.strip().rstrip(";"))
        stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
        try:
            conn.executescript(
                "BEGIN;\n" + script + "\n;INSERT INTO schema_version (version, applied_at) VALUES ("
                + str(version) + ", '" + stamp + "');\nCOMMIT;"
            )
        except Exception:
            if conn.in_transaction:
                conn.rollback()
            raise
        applied_now.append(version)
    return applied_now
