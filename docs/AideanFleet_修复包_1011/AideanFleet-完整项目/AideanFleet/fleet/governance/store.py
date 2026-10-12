"""治理层 SQLite 存储（独立表 governance_usage / governance_approvals）"""

from __future__ import annotations

import sqlite3
import threading
from pathlib import Path
from typing import Any

_lock = threading.Lock()
_db_path: Path | None = None


def _get_conn() -> sqlite3.Connection:
    global _db_path
    if _db_path is None:
        from fleet.core.paths import paths
        _db_path = paths().data_dir / "governance.db"
        _db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(_db_path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    """初始化治理层表结构"""
    conn = _get_conn()
    with _lock:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS governance_usage (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id TEXT,
                project_id TEXT,
                role TEXT DEFAULT '',
                model TEXT DEFAULT '',
                prompt_tokens INTEGER DEFAULT 0,
                cached_tokens INTEGER DEFAULT 0,
                completion_tokens INTEGER DEFAULT 0,
                total_tokens INTEGER DEFAULT 0,
                call_count INTEGER DEFAULT 1,
                unknown_usage INTEGER DEFAULT 0,
                timestamp TEXT,
                source TEXT DEFAULT 'event'
            );

            CREATE TABLE IF NOT EXISTS governance_budget (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                level TEXT NOT NULL,
                scope TEXT NOT NULL,
                used_tokens INTEGER DEFAULT 0,
                limit_tokens INTEGER DEFAULT 0,
                action TEXT DEFAULT 'pause',
                blocked_at TEXT,
                reset_at TEXT,
                reset_by TEXT
            );

            CREATE TABLE IF NOT EXISTS governance_approvals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                approval_id TEXT UNIQUE NOT NULL,
                action_type TEXT NOT NULL,
                description TEXT,
                task_id TEXT,
                project_id TEXT,
                requested_by TEXT DEFAULT 'system',
                status TEXT DEFAULT 'pending',
                decision TEXT,
                decided_by TEXT,
                decided_at TEXT,
                created_at TEXT NOT NULL,
                expires_at TEXT
            );

            CREATE INDEX IF NOT EXISTS idx_usage_task ON governance_usage(task_id);
            CREATE INDEX IF NOT EXISTS idx_usage_project ON governance_usage(project_id);
            CREATE INDEX IF NOT EXISTS idx_usage_timestamp ON governance_usage(timestamp);
            CREATE INDEX IF NOT EXISTS idx_budget_level ON governance_budget(level, scope);
            CREATE INDEX IF NOT EXISTS idx_approval_status ON governance_approvals(status);
        """)
        columns = {row[1] for row in conn.execute("PRAGMA table_info(governance_usage)")}
        if "event_key" not in columns:
            conn.execute("ALTER TABLE governance_usage ADD COLUMN event_key TEXT")
        conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_usage_event_key "
            "ON governance_usage(event_key)"
        )
        conn.commit()


def record_usage(
    *,
    task_id: str = "",
    project_id: str = "",
    role: str = "",
    model: str = "",
    prompt_tokens: int = 0,
    cached_tokens: int = 0,
    completion_tokens: int = 0,
    total_tokens: int = 0,
    call_count: int = 1,
    unknown_usage: int = 0,
    timestamp: str = "",
    source: str = "event",
    event_key: str | None = None,
) -> bool:
    """写入用量，返回是否新增；事件键去重，手工记录不去重。"""
    conn = _get_conn()
    try:
        with _lock, conn:
            cursor = conn.execute(
                """INSERT INTO governance_usage
                   (task_id, project_id, role, model, prompt_tokens, cached_tokens,
                    completion_tokens, total_tokens, call_count, unknown_usage, timestamp, source, event_key)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(event_key) DO NOTHING""",
                (task_id, project_id, role, model, prompt_tokens, cached_tokens,
                 completion_tokens, total_tokens, call_count, unknown_usage, timestamp, source, event_key),
            )
            return cursor.rowcount == 1
    finally:
        conn.close()


def query_usage(
    *,
    task_id: str | None = None,
    project_id: str | None = None,
    since: str | None = None,
    until: str | None = None,
) -> list[dict[str, Any]]:
    """查询用量记录"""
    conn = _get_conn()
    conditions = []
    params: list[Any] = []
    if task_id:
        conditions.append("task_id = ?")
        params.append(task_id)
    if project_id:
        conditions.append("project_id = ?")
        params.append(project_id)
    if since:
        conditions.append("timestamp >= ?")
        params.append(since)
    if until:
        conditions.append("timestamp <= ?")
        params.append(until)

    where = " AND ".join(conditions) if conditions else "1=1"
    with _lock:
        rows = conn.execute(
            f"SELECT * FROM governance_usage WHERE {where} ORDER BY timestamp", params
        ).fetchall()
    return [dict(r) for r in rows]


def sum_usage(
    *,
    group_by: str = "task_id",
    task_id: str | None = None,
    project_id: str | None = None,
    since: str | None = None,
) -> list[dict[str, Any]]:
    """聚合查询用量"""
    conn = _get_conn()
    valid_groups = {"task_id", "project_id", "role", "model", "date"}
    if group_by not in valid_groups:
        group_by = "task_id"

    if group_by == "date":
        select_expr = "SUBSTR(timestamp, 1, 10) as period"
    else:
        select_expr = f"{group_by} as period"

    conditions = []
    params: list[Any] = []
    if task_id:
        conditions.append("task_id = ?")
        params.append(task_id)
    if project_id:
        conditions.append("project_id = ?")
        params.append(project_id)
    if since:
        conditions.append("timestamp >= ?")
        params.append(since)

    where = " AND ".join(conditions) if conditions else "1=1"
    with _lock:
        rows = conn.execute(
            f"""SELECT {select_expr},
                       SUM(prompt_tokens) as prompt_tokens,
                       SUM(cached_tokens) as cached_tokens,
                       SUM(completion_tokens) as completion_tokens,
                       SUM(total_tokens) as total_tokens,
                       SUM(call_count) as call_count,
                       SUM(unknown_usage) as unknown_usage
                FROM governance_usage
                WHERE {where}
                GROUP BY period
                ORDER BY total_tokens DESC""",
            params,
        ).fetchall()
    return [dict(r) for r in rows]


def get_budget(level: str, scope: str) -> dict[str, Any] | None:
    """获取预算记录"""
    conn = _get_conn()
    with _lock:
        row = conn.execute(
            "SELECT * FROM governance_budget WHERE level = ? AND scope = ?",
            (level, scope),
        ).fetchone()
    return dict(row) if row else None


def upsert_budget(
    level: str,
    scope: str,
    used_tokens: int | None = None,
    limit_tokens: int | None = None,
    action: str | None = None,
    **kwargs,
) -> None:
    """更新或插入预算记录"""
    conn = _get_conn()
    with _lock:
        existing = conn.execute(
            "SELECT id FROM governance_budget WHERE level = ? AND scope = ?",
            (level, scope),
        ).fetchone()
        if existing:
            sets = []
            vals = []
            for k, v in {"used_tokens": used_tokens, "limit_tokens": limit_tokens,
                         "action": action, **kwargs}.items():
                if v is not None:
                    sets.append(f"{k} = ?")
                    vals.append(v)
            if sets:
                vals.extend([level, scope])
                conn.execute(
                    f"UPDATE governance_budget SET {', '.join(sets)} WHERE level = ? AND scope = ?",
                    vals,
                )
        else:
            conn.execute(
                """INSERT INTO governance_budget
                   (level, scope, used_tokens, limit_tokens, action)
                   VALUES (?, ?, ?, ?, ?)""",
                (level, scope, used_tokens if used_tokens is not None else 0,
                 limit_tokens if limit_tokens is not None else 0, action or "pause"),
            )
        conn.commit()
    conn.close()


def consume_budgets(tokens: int, scopes: list[tuple[str, str]],
                    defaults: dict[str, int], action: str) -> None:
    """三层扣款在同一写事务内完成；数据库增量避免多实例缓存丢账。"""
    if isinstance(tokens, bool) or not isinstance(tokens, int) or tokens < 0:
        raise ValueError("tokens 必须是非负整数")
    conn = _get_conn()
    try:
        with _lock, conn:
            conn.execute("BEGIN IMMEDIATE")
            for level, scope in scopes:
                row = conn.execute(
                    "SELECT id FROM governance_budget WHERE level = ? AND scope = ?",
                    (level, scope),
                ).fetchone()
                if row is None:
                    conn.execute(
                        "INSERT INTO governance_budget (level, scope, used_tokens, limit_tokens, action) "
                        "VALUES (?, ?, ?, ?, ?)",
                        (level, scope, tokens, defaults[level], action),
                    )
                else:
                    conn.execute(
                        "UPDATE governance_budget SET used_tokens = used_tokens + ? WHERE id = ?",
                        (tokens, row["id"]),
                    )
    finally:
        conn.close()


def create_approval(
    approval_id: str,
    action_type: str,
    description: str = "",
    task_id: str = "",
    project_id: str = "",
    requested_by: str = "system",
    created_at: str = "",
    expires_at: str = "",
) -> None:
    """创建审批请求"""
    conn = _get_conn()
    with _lock:
        conn.execute(
            """INSERT INTO governance_approvals
               (approval_id, action_type, description, task_id, project_id,
                requested_by, status, created_at, expires_at)
               VALUES (?, ?, ?, ?, ?, ?, 'pending', ?, ?)""",
            (approval_id, action_type, description, task_id, project_id,
             requested_by, created_at, expires_at),
        )
        conn.commit()


def get_approval(approval_id: str) -> dict[str, Any] | None:
    """获取审批请求"""
    conn = _get_conn()
    with _lock:
        row = conn.execute(
            "SELECT * FROM governance_approvals WHERE approval_id = ?",
            (approval_id,),
        ).fetchone()
    return dict(row) if row else None


def list_pending_approvals() -> list[dict[str, Any]]:
    """列出所有待审批请求"""
    conn = _get_conn()
    with _lock:
        rows = conn.execute(
            "SELECT * FROM governance_approvals WHERE status = 'pending' ORDER BY created_at"
        ).fetchall()
    return [dict(r) for r in rows]


def decide_approval(
    approval_id: str,
    decision: str,
    decided_by: str = "user",
    decided_at: str = "",
) -> bool:
    """决定审批（approve/reject）"""
    if decision not in ("approve", "reject"):
        return False
    conn = _get_conn()
    with _lock:
        cur = conn.execute(
            """UPDATE governance_approvals
               SET status = ?, decision = ?, decided_by = ?, decided_at = ?
               WHERE approval_id = ? AND status = 'pending'""",
            (decision, decision, decided_by, decided_at, approval_id),
        )
        conn.commit()
        return cur.rowcount > 0
