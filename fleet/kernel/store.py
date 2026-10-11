"""这是什么：Fleet Kernel 的 SQLite 存储层（P1 内核，对标 LoopX 薄内核思路）。
怎么用：from fleet.kernel.store import connect, init_db
设计铁律：
- 单写者：所有状态变更必须经 kernel.Kernel 的方法，本模块只管连接与建表；
- SQLite WAL：多进程读 + 单写，busy_timeout 兜底并发；
- events 表即 outbox：先落库再发布，JSONL 只是导出产物；
- 本包不 import fleet 的任何上层包（runner/harness/planner/api/console/manager），
  由 tests/architecture/test_import_boundaries.py 守门。
"""

from __future__ import annotations

import sqlite3
import threading
from pathlib import Path

_SCHEMA = """
CREATE TABLE IF NOT EXISTS goals (
  id         TEXT PRIMARY KEY,
  title      TEXT NOT NULL,
  status     TEXT NOT NULL DEFAULT 'active',
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS todos (
  id                TEXT PRIMARY KEY,
  goal_id           TEXT NOT NULL REFERENCES goals(id),
  kind              TEXT NOT NULL DEFAULT 'exec',
  title             TEXT NOT NULL,
  role              TEXT NOT NULL DEFAULT '',
  depends_on        TEXT NOT NULL DEFAULT '[]',
  allowed_files     TEXT NOT NULL DEFAULT '',
  verify            TEXT NOT NULL DEFAULT '[]',
  done_when         TEXT NOT NULL DEFAULT '',
  packet            TEXT NOT NULL DEFAULT '',
  workspace         TEXT NOT NULL DEFAULT '',
  status            TEXT NOT NULL DEFAULT 'open',
  lineage           TEXT NOT NULL DEFAULT '',
  attempt_count     INTEGER NOT NULL DEFAULT 0,
  successor_of      TEXT NOT NULL DEFAULT '',
  claimed_by        TEXT NOT NULL DEFAULT '',
  claim_expires_at  REAL NOT NULL DEFAULT 0,
  created_at        TEXT NOT NULL,
  updated_at        TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_todos_goal   ON todos(goal_id, status);
CREATE INDEX IF NOT EXISTS idx_todos_status ON todos(status);
CREATE INDEX IF NOT EXISTS idx_todos_lineage ON todos(lineage);

CREATE TABLE IF NOT EXISTS attempts (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  todo_id       TEXT NOT NULL,
  harness       TEXT NOT NULL DEFAULT '',
  model         TEXT NOT NULL DEFAULT '',
  started_at    TEXT NOT NULL,
  ended_at      TEXT,
  exit_code     INTEGER,
  tokens_in     INTEGER NOT NULL DEFAULT 0,
  tokens_out    INTEGER NOT NULL DEFAULT 0,
  evidence_path TEXT NOT NULL DEFAULT '',
  turn_result   TEXT NOT NULL DEFAULT '',
  session_id    TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_attempts_todo ON attempts(todo_id);

CREATE TABLE IF NOT EXISTS events (
  seq       INTEGER PRIMARY KEY AUTOINCREMENT,
  ts        TEXT NOT NULL,
  kind      TEXT NOT NULL,
  todo_id   TEXT NOT NULL DEFAULT '',
  goal_id   TEXT NOT NULL DEFAULT '',
  payload   TEXT NOT NULL DEFAULT '{}',
  published INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_events_published ON events(published);

CREATE TABLE IF NOT EXISTS quota (
  key            TEXT PRIMARY KEY,
  used           INTEGER NOT NULL DEFAULT 0,
  limit_per_day  INTEGER NOT NULL DEFAULT 0,
  day            TEXT NOT NULL DEFAULT ''
);
"""

_local = threading.local()


def connect(db_path: str | Path) -> sqlite3.Connection:
    """打开（并初始化）kernel 数据库连接：WAL、busy_timeout、行工厂。

    每线程一条连接（sqlite3 连接不能跨线程共享）。
    """
    conn = getattr(_local, "conn", None)
    if conn is not None and getattr(_local, "conn_path", None) == str(db_path):
        return conn
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    # IMMEDIATE：首次写语句即取写锁，配合 `with conn:` 让 transition 多语句原子提交
    conn = sqlite3.connect(str(path), timeout=30, isolation_level="IMMEDIATE")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=10000")
    _local.conn = conn
    _local.conn_path = str(db_path)
    return conn


def init_db(db_path: str | Path) -> None:
    """建表（幂等）。"""
    conn = connect(db_path)
    conn.executescript(_SCHEMA)


def close() -> None:
    """关闭当前线程的连接（测试清理用）。"""
    conn = getattr(_local, "conn", None)
    if conn is not None:
        try:
            conn.close()
        except Exception:
            pass
    _local.conn = None
    _local.conn_path = None
