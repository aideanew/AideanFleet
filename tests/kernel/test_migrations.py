"""kernel.db 迁移测试（TASK-101）：空库升级、001 旧库升级、幂等重放。"""

from __future__ import annotations

import sqlite3

import pytest

from fleet.kernel import migrate
from fleet.kernel.store import close, connect, init_db


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    monkeypatch.setenv("FLEET_DATA_DIR", str(tmp_path / "data"))
    yield
    close()


def test_fresh_db_has_migration_columns_and_version(tmp_path):
    db_path = tmp_path / "kernel.db"
    init_db(db_path)
    conn = connect(db_path)
    cols_goals = _columns(conn, "goals")
    cols_todos = _columns(conn, "todos")
    assert {"requirements", "workspace"} <= cols_goals
    assert "plan_decision" in cols_todos
    versions = {row["version"] for row in conn.execute("SELECT version FROM schema_version")}
    assert versions >= {2}


def test_old_001_db_upgrades_losslessly(tmp_path):
    """用 001 基线结构造旧库 + 预置数据行 → init_db 升级 → 新列存在且数据行数不变。"""
    db_path = tmp_path / "old.db"
    sql = (migrate.migrations_dir() / "001_init.sql").read_text(encoding="utf-8")
    conn = sqlite3.connect(str(db_path))
    conn.executescript(sql)
    conn.execute(
        "INSERT INTO goals (id, title, status, created_at) VALUES ('G-1', '旧目标', 'active', '2026-01-01T00:00:00Z')"
    )
    conn.execute(
        "INSERT INTO todos (id, goal_id, kind, title, status, lineage, created_at, updated_at)"
        " VALUES ('T-1', 'G-1', 'exec', '旧任务', 'open', 'T-1', '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z')"
    )
    conn.commit()
    conn.close()

    init_db(db_path)
    conn = connect(db_path)
    assert {"requirements", "workspace"} <= _columns(conn, "goals")
    assert "plan_decision" in _columns(conn, "todos")
    assert conn.execute("SELECT COUNT(*) AS n FROM goals").fetchone()["n"] == 1
    assert conn.execute("SELECT COUNT(*) AS n FROM todos").fetchone()["n"] == 1
    row = conn.execute("SELECT requirements, workspace FROM goals WHERE id='G-1'").fetchone()
    assert row["requirements"] == "" and row["workspace"] == ""
    todo = conn.execute("SELECT plan_decision FROM todos WHERE id='T-1'").fetchone()
    assert todo["plan_decision"] == "none"


def test_repeated_init_is_idempotent(tmp_path):
    db_path = tmp_path / "kernel.db"
    init_db(db_path)
    init_db(db_path)
    init_db(db_path)
    conn = connect(db_path)
    rows = conn.execute("SELECT COUNT(*) AS n FROM schema_version WHERE version=2").fetchone()
    assert rows["n"] == 1


def test_migrations_packaged_copy_matches_source():
    """Guard：fleet/kernel/_migrations 打包副本与 database/migrations 唯一源一致。"""
    import subprocess

    root = migrate.migrations_dir().parents[2]
    source = sorted(p.name for p in (root / "database" / "migrations").glob("*.sql"))
    packaged_dir = root / "fleet" / "kernel" / "_migrations"
    if not packaged_dir.exists():
        pytest.skip("_migrations 尚未生成（运行 python scripts/sync_migrations.py）")
    packaged = sorted(p.name for p in packaged_dir.glob("*.sql"))
    assert packaged == source
    for name in source:
        assert (packaged_dir / name).read_text(encoding="utf-8") == \
               (root / "database" / "migrations" / name).read_text(encoding="utf-8"), name


def test_failed_migration_rolls_back_atomically(tmp_path, monkeypatch):
    """审计回归：迁移脚本中途失败必须整体回滚（不留半个迁移、不记版本）。"""
    import sqlite3

    import pytest

    from fleet.kernel import migrate

    mig = tmp_path / "migs"
    mig.mkdir()
    (mig / "001_base.sql").write_text("CREATE TABLE t (a TEXT);\n", encoding="utf-8")
    (mig / "002_bad.sql").write_text(
        "ALTER TABLE t ADD COLUMN b TEXT;\nALTER TABLE no_such_table ADD COLUMN x TEXT;\n",
        encoding="utf-8")
    monkeypatch.setattr(migrate, "migrations_dir", lambda: mig)
    conn = sqlite3.connect(tmp_path / "k.db")
    conn.row_factory = sqlite3.Row
    with pytest.raises(sqlite3.OperationalError):
        migrate.run(conn)
    cols = [r["name"] for r in conn.execute("PRAGMA table_info(t)")]
    assert cols == ["a"], cols  # 002 的第一句也被回滚
    assert migrate.applied_versions(conn) == {1}
    (mig / "002_bad.sql").write_text("ALTER TABLE t ADD COLUMN b TEXT;\n", encoding="utf-8")
    assert migrate.run(conn) == [2]
    conn.close()
