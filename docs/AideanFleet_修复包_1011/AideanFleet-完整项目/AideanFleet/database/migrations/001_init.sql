-- database/migrations/001_init.sql
-- AideanFleet kernel.db 数据模型基线（规划快照 c22fa43 时的真实结构，逐字取自 fleet/kernel/store.py _SCHEMA）
-- 现状：无版本表，store.init_db 每次以 CREATE ... IF NOT EXISTS 幂等建表。
-- 本文件只记录基线，不新增任何表或列（AGENTS 模板 §13-13：禁止为未来预建表）。
-- 后续迁移（002 起）由 TASK-101 串行引入 schema_version 表与迁移执行器，版本号编排见 docs/04_planning/current-plan.md §5。
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;
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
