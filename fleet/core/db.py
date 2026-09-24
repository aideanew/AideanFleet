"""这是什么：任务数据库（SQLite）。存"现在在哪"——任务进度表、项目表、状态持久化，支持断点恢复。
怎么用：from fleet.core import db;  db.init_db();  db.create_task({...});  db.transition_and_log(...)
约定：字段名见 docs/契约/任务进度表字段.md（前 15 个字段冻结）；状态非法迁移一律抛 InvalidTransition 且不落库。
配套：events.jsonl 记"发生过什么"，本模块只改状态；两者由 db.transition_and_log 按契约顺序一起写。
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator

from . import state_machine as sm
from .paths import paths

#: 契约字段（15 个，字段名与顺序冻结）—— 见 docs/契约/任务进度表字段.md §1
CONTROL_PLANE_CONTRACT_FIELDS: tuple[str, ...] = (
    "task_id",
    "role",
    "dispatcher_role",
    "receipt_role",
    "platform",
    "model",
    "task_type",
    "token",
    "duration_ms",
    "detail",
    "remark",
    "exec_status",
    "review_status",
    "created_at",
    "updated_at",
)

#: 扩展字段（TaskPack 与机器门需要）—— 见 docs/契约/任务进度表字段.md §2
#  dependencies（JSON 数组，依赖的 task_id）由 CORE-02 按 docs/规划总览.md L283 新增，
#  属于对扩展字段清单的“新增”，不动 15 个冻结字段。
#  context_budget / memory_refs / retry_context 由 CORE-04（契约 v1.2 §13.1）新增：
#  上下文成本三扩展列，见 任务进度表字段.md §2.1。
TASK_EXTENSION_FIELDS: tuple[str, ...] = (
    "project_id",
    "title",
    "assignee",
    "reviewer",
    "verify_cmd",
    "workspace",
    "allowed_files",
    "forbidden_files",
    "dependencies",
    "adapter",
    "evidence_path",
    "report_path",
    "baseline_path",
    "rework_count",
    "blocked_reason",
    "retry_limit",
    "context_budget",
    "memory_refs",
    "retry_context",
    # executor_session_id：每步派工的执行体会话 id（需求：控制端可回溯 CLI 原始会话）。
    # 属扩展列新增，不动 15 个冻结契约字段；旧库由 _MIGRATION_COLUMNS 轻量迁移补齐。
    "executor_session_id",
)

#: 轻量迁移：旧库缺失的扩展列（列名 -> DDL 片段），init_db 时逐个补齐
_MIGRATION_COLUMNS: dict[str, str] = {
    "dependencies": "TEXT",
    "context_budget": "INTEGER",
    "memory_refs": "TEXT",
    "retry_context": "TEXT",
    "executor_session_id": "TEXT",
}

TASK_FIELDS: tuple[str, ...] = CONTROL_PLANE_CONTRACT_FIELDS + TASK_EXTENSION_FIELDS

PROJECT_FIELDS: tuple[str, ...] = ("project_id", "name", "path", "port", "created_at", "updated_at")

#: 可写字段（其余只读：task_id/created_at 不参与 UPDATE）
_UPDATABLE_FIELDS: tuple[str, ...] = tuple(f for f in TASK_FIELDS if f not in ("task_id", "created_at"))

_TASKS_DDL = """
CREATE TABLE IF NOT EXISTS tasks (
    task_id         TEXT PRIMARY KEY,
    role            TEXT,
    dispatcher_role TEXT,
    receipt_role    TEXT,
    platform        TEXT,
    model           TEXT,
    task_type       INTEGER NOT NULL DEFAULT 2,
    token           INTEGER,
    duration_ms     INTEGER,
    detail          TEXT DEFAULT '',
    remark          TEXT DEFAULT '',
    exec_status     TEXT NOT NULL DEFAULT 'DRAFT',
    review_status   TEXT NOT NULL DEFAULT 'PENDING',
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL,
    project_id      TEXT,
    title           TEXT,
    assignee        TEXT,
    reviewer        TEXT,
    verify_cmd      TEXT,
    workspace       TEXT,
    allowed_files   TEXT,
    forbidden_files TEXT,
    dependencies    TEXT,
    adapter         TEXT,
    evidence_path   TEXT,
    report_path     TEXT,
    baseline_path   TEXT,
    rework_count    INTEGER NOT NULL DEFAULT 0,
    blocked_reason  TEXT DEFAULT '',
    retry_limit     INTEGER NOT NULL DEFAULT 3,
    context_budget  INTEGER,
    memory_refs     TEXT,
    retry_context   TEXT,
    executor_session_id TEXT
);
"""

_PROJECTS_DDL = """
CREATE TABLE IF NOT EXISTS projects (
    project_id TEXT PRIMARY KEY,
    name       TEXT NOT NULL,
    path       TEXT NOT NULL,
    port       INTEGER,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
"""

_INDEXES_DDL = (
    "CREATE INDEX IF NOT EXISTS idx_tasks_project ON tasks(project_id);",
    "CREATE INDEX IF NOT EXISTS idx_tasks_state ON tasks(exec_status);",
)


def iso_now() -> str:
    """本地时区的 ISO-8601 时间戳（带偏移），全项目统一用它打时间。"""
    return datetime.now().astimezone().isoformat(timespec="seconds")


def connect(db_file: str | Path | None = None) -> sqlite3.Connection:
    """打开一个连接（调用方负责关闭）。WAL 模式，便于控制台与引擎同时读。"""
    p = paths()
    target = Path(db_file) if db_file else p.db_file
    target.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(target), timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


@contextmanager
def session(db_file: str | Path | None = None) -> Iterator[sqlite3.Connection]:
    """事务上下文：正常提交，异常回滚。所有写操作都必须走它。"""
    conn = connect(db_file)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db(db_file: str | Path | None = None) -> Path:
    """建表 + 建索引 + 轻量迁移（幂等）。返回数据库文件路径。"""
    with session(db_file) as conn:
        conn.execute(_TASKS_DDL)
        conn.execute(_PROJECTS_DDL)
        for ddl in _INDEXES_DDL:
            conn.execute(ddl)
        # 轻量迁移：旧库缺少的扩展列逐个补齐（dependencies=CORE-02；
        # context_budget/memory_refs/retry_context=CORE-04 契约 v1.2）
        cols = {row["name"] for row in conn.execute("PRAGMA table_info(tasks)").fetchall()}
        for column, ddl_type in _MIGRATION_COLUMNS.items():
            if column not in cols:
                conn.execute(f"ALTER TABLE tasks ADD COLUMN {column} {ddl_type}")
    return Path(db_file) if db_file else paths().db_file


def health() -> bool:
    """db 健康检查：能打开、两张表都在。"""
    try:
        with session() as conn:
            rows = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        names = {row["name"] for row in rows}
        return {"tasks", "projects"}.issubset(names)
    except sqlite3.Error:
        return False


# ---------------------------------------------------------------------------
# 值转换
# ---------------------------------------------------------------------------


def _to_db(value: Any) -> Any:
    """写库前的规整：list/dict 转 JSON 字符串，bool 转 0/1。"""
    if isinstance(value, bool):
        return 1 if value else 0
    if isinstance(value, (list, tuple, dict)):
        return json.dumps(value, ensure_ascii=False)
    return value


def _row_to_task(row: sqlite3.Row) -> dict[str, Any]:
    return {key: row[key] for key in row.keys()}


# ---------------------------------------------------------------------------
# 任务读写
# ---------------------------------------------------------------------------


def create_task(fields: dict[str, Any], db_file: str | Path | None = None) -> dict[str, Any]:
    """建任务（默认状态 DRAFT）。返回落库后的完整行。"""
    data = dict(fields)
    if not data.get("task_id"):
        raise ValueError("create_task 需要 task_id")
    now = iso_now()
    data.setdefault("task_type", 2)
    data.setdefault("exec_status", "DRAFT")
    data.setdefault("review_status", "PENDING")
    data.setdefault("rework_count", 0)
    data.setdefault("retry_limit", 3)
    data.setdefault("detail", "")
    data.setdefault("remark", "")
    data.setdefault("blocked_reason", "")
    data.setdefault("created_at", now)
    data["updated_at"] = data.get("updated_at", now)

    if data["exec_status"] not in sm.STATES:
        raise sm.InvalidTransition("<new>", str(data["exec_status"]), "建任务时的初始状态非法")
    if data["review_status"] not in sm.REVIEW_STATUSES:
        raise ValueError(f"review_status 非法：{data['review_status']}")

    unknown = [key for key in data if key not in TASK_FIELDS]
    if unknown:
        raise ValueError(f"未知字段（字段名已冻结，见 docs/契约/任务进度表字段.md）：{unknown}")

    columns = [key for key in TASK_FIELDS if key in data]
    placeholders = ", ".join("?" for _ in columns)
    with session(db_file) as conn:
        conn.execute(
            f"INSERT INTO tasks ({', '.join(columns)}) VALUES ({placeholders})",
            [_to_db(data[key]) for key in columns],
        )
    return get_task(data["task_id"], db_file=db_file) or {}


def get_task(task_id: str, db_file: str | Path | None = None) -> dict[str, Any] | None:
    """按 id 取任务；不存在返回 None。"""
    with session(db_file) as conn:
        row = conn.execute("SELECT * FROM tasks WHERE task_id = ?", (task_id,)).fetchone()
    return _row_to_task(row) if row else None


def update_task(task_id: str, db_file: str | Path | None = None, **fields: Any) -> dict[str, Any]:
    """更新任务字段（自动刷新 updated_at）。状态请走 transition()，不要直接改 exec_status。"""
    unknown = [key for key in fields if key not in _UPDATABLE_FIELDS]
    if unknown:
        raise ValueError(f"不可更新字段：{unknown}")
    if not fields:
        return get_task(task_id, db_file=db_file) or {}
    data = dict(fields)
    data["updated_at"] = iso_now()
    assignments = ", ".join(f"{key} = ?" for key in data)
    with session(db_file) as conn:
        cursor = conn.execute(
            f"UPDATE tasks SET {assignments} WHERE task_id = ?",
            [*[_to_db(value) for value in data.values()], task_id],
        )
        if cursor.rowcount == 0:
            raise KeyError(f"任务不存在：{task_id}")
    return get_task(task_id, db_file=db_file) or {}


def list_tasks(project_id: str | None = None, db_file: str | Path | None = None) -> list[dict[str, Any]]:
    """按项目列出任务（按 created_at 升序）。"""
    sql = "SELECT * FROM tasks"
    params: list[Any] = []
    if project_id:
        sql += " WHERE project_id = ?"
        params.append(project_id)
    sql += " ORDER BY created_at ASC, task_id ASC"
    with session(db_file) as conn:
        rows = conn.execute(sql, params).fetchall()
    return [_row_to_task(row) for row in rows]


# ---------------------------------------------------------------------------
# 状态迁移（契约 §5 的四步顺序在这里落地）
# ---------------------------------------------------------------------------


def _default_review_status(state: str) -> str:
    """迁移后的 review_status 默认值（显式传入可覆盖）。"""
    return {
        "REVIEWING": "REVIEWING",
        "DONE": "PASS",
        "PARTIAL": "PARTIAL",
        "REWORK": "REWORK",
        "BLOCKED": "BLOCKED",
    }.get(state, "PENDING")


def transition(task_id: str, to_state: str, db_file: str | Path | None = None, **fields: Any) -> dict[str, Any]:
    """状态迁移（**先校验后落库**）。

    非法迁移抛 InvalidTransition，且不会写任何一行（契约 §2.2）。
    """
    task = get_task(task_id, db_file=db_file)
    if task is None:
        raise KeyError(f"任务不存在：{task_id}")
    sm.assert_transition(task["exec_status"], to_state)

    data = dict(fields)
    data["exec_status"] = to_state
    if to_state == "BLOCKED":
        data.setdefault("blocked_reason", str(data.get("remark", "") or ""))
    else:
        data.setdefault("blocked_reason", "")
    data.setdefault("review_status", _default_review_status(to_state))
    return update_task(task_id, db_file=db_file, **data)


def bump_rework(task_id: str, db_file: str | Path | None = None, **fields: Any) -> dict[str, Any]:
    """返工计数 +1，并落到 REWORK，或（超过 3 次时）直接 ESCALATED。

    返回落库后的任务行；读 exec_status 判断是"继续"还是"升级"。
    """
    task = get_task(task_id, db_file=db_file)
    if task is None:
        raise KeyError(f"任务不存在：{task_id}")
    count = int(task.get("rework_count") or 0) + 1
    data = dict(fields)
    data["rework_count"] = count
    if task["exec_status"] == "REVIEWING":
        sm.assert_transition("REVIEWING", "REWORK")
    data["exec_status"] = sm.resolve_rework_target(count)
    data["review_status"] = "REWORK"
    data["updated_at"] = iso_now()
    return update_task(task_id, db_file=db_file, **data)


def transition_and_log(
    task_id: str,
    to_state: str,
    *,
    actor: str,
    summary: str = "",
    url: str | None = None,
    action: str | None = None,
    extra: dict[str, Any] | None = None,
    db_file: str | Path | None = None,
    **fields: Any,
) -> dict[str, Any]:
    """契约 §5 的四步顺序：校验 → 落库 → 追加事件 → 重写 plan.json。

    第 1 步失败时事件流不会有任何新行（可被 tests/test_state_machine.py 断言）。
    """
    from . import events, plan  # 延迟导入，避免模块级循环

    task = get_task(task_id, db_file=db_file)
    if task is None:
        raise KeyError(f"任务不存在：{task_id}")

    sm.assert_transition(task["exec_status"], to_state)
    updated = transition(task_id, to_state, db_file=db_file, **fields)
    events.append(
        actor=actor,
        action=action or f"task:{to_state.lower()}",
        task_id=task_id,
        summary=summary or f"{task_id} -> {to_state}",
        url=url or f"/tasks/{task_id}",
        project=updated.get("project_id"),
        extra=extra,
    )
    if updated.get("project_id"):
        plan.sync_task_state(updated["project_id"], task_id, to_state)
    return updated


# ---------------------------------------------------------------------------
# 项目读写
# ---------------------------------------------------------------------------


def create_project(
    project_id: str,
    name: str,
    path: str,
    port: int | None = None,
    db_file: str | Path | None = None,
) -> dict[str, Any]:
    """注册项目（幂等：已存在则原样返回，不覆盖已有配置）。"""
    existing = get_project(project_id, db_file=db_file)
    if existing:
        return existing
    now = iso_now()
    with session(db_file) as conn:
        conn.execute(
            "INSERT INTO projects (project_id, name, path, port, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
            (project_id, name, path, port, now, now),
        )
    return get_project(project_id, db_file=db_file) or {}


def get_project(project_id: str, db_file: str | Path | None = None) -> dict[str, Any] | None:
    with session(db_file) as conn:
        row = conn.execute("SELECT * FROM projects WHERE project_id = ?", (project_id,)).fetchone()
    return {key: row[key] for key in row.keys()} if row else None


def find_project(key: str, db_file: str | Path | None = None) -> dict[str, Any] | None:
    """按 project_id 或 name 精确匹配项目（id 优先），供会话解锁/切换做身份解析。"""
    with session(db_file) as conn:
        row = conn.execute(
            "SELECT * FROM projects WHERE project_id = ? OR name = ? ORDER BY (project_id = ?) DESC LIMIT 1",
            (key, key, key),
        ).fetchone()
    return {col: row[col] for col in row.keys()} if row else None


def list_projects(db_file: str | Path | None = None) -> list[dict[str, Any]]:
    with session(db_file) as conn:
        rows = conn.execute("SELECT * FROM projects ORDER BY created_at ASC").fetchall()
    return [{key: row[key] for key in row.keys()} for row in rows]


def update_project(project_id: str, db_file: str | Path | None = None, **fields: Any) -> dict[str, Any]:
    """更新项目字段（name / path / port）。"""
    unknown = [key for key in fields if key not in ("name", "path", "port")]
    if unknown:
        raise ValueError(f"不可更新字段：{unknown}")
    data = dict(fields)
    data["updated_at"] = iso_now()
    assignments = ", ".join(f"{key} = ?" for key in data)
    with session(db_file) as conn:
        conn.execute(
            f"UPDATE projects SET {assignments} WHERE project_id = ?",
            [*data.values(), project_id],
        )
    return get_project(project_id, db_file=db_file) or {}
