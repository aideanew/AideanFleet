"""这是什么：卡死检测与升级（REL-01 §9.3）。只管"还活着吗"，与 Machine Gate（做对了吗）正交。
口径：
  · 任务在 DOING 超过 task 级超时（.env [settings] FLEET_SETTINGS_TASK_STUCK_SECONDS，默认 1800）
    -> 写事件 task:stuck（本轮 DOING 周期内幂等，只发一次）。
  · 超过 2 倍阈值 -> DOING -> BLOCKED（blocked_reason=stuck_timeout），等人工释放回派工轨道。
  · 模型调用重试口径（10s×10）已在 fleet/models/retry.py，本模块绝不重复实现，也不替代适配器超时。
计时基准：最后一次 task:doing 事件的 timestamp（没有则退回 updated_at/created_at）。
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from fleet.core import config, db, events

#: 卡死阈值默认（秒）
DEFAULT_TASK_STUCK_SECONDS = 1800

#: 升级倍率：stuck 超过 阈值×2 -> BLOCKED
ESCALATE_MULTIPLIER = 2


def task_stuck_seconds() -> int:
    """读 .env [settings] task_stuck_seconds；非法/缺省一律回默认 1800。"""
    try:
        section = config.load("settings")
    except Exception:  # 配置不可读不能让守望停摆
        section = {}
    try:
        value = int(section.get("task_stuck_seconds", DEFAULT_TASK_STUCK_SECONDS))
    except (TypeError, ValueError):
        return DEFAULT_TASK_STUCK_SECONDS
    return value if value > 0 else DEFAULT_TASK_STUCK_SECONDS


def _doing_anchor(rows: list[dict[str, Any]], task_id: str) -> tuple[str | None, int]:
    """该任务最后一次 task:doing 的 (timestamp, seq)；没有返回 (None, 0)。"""
    anchor: dict[str, Any] | None = None
    for row in rows:
        if row.get("action") == "task:doing" and row.get("taskId") == task_id:
            anchor = row
    if anchor is None:
        return None, 0
    return str(anchor.get("timestamp") or ""), int(anchor.get("seq") or 0)


def _stuck_marked_since(rows: list[dict[str, Any]], task_id: str, doing_seq: int) -> bool:
    """本轮 DOING 周期内是否已发过 task:stuck（seq 必须晚于最后一次 task:doing）。"""
    return any(
        row.get("action") == "task:stuck"
        and row.get("taskId") == task_id
        and int(row.get("seq") or 0) > doing_seq
        for row in rows
    )


def scan(
    project_id: str | None = None,
    *,
    now: datetime | None = None,
    db_file: str | Path | None = None,
    stuck_seconds: int | None = None,
) -> list[dict[str, Any]]:
    """扫一遍 DOING 任务：到阈值发 task:stuck；到 2 倍阈值升级 BLOCKED。返回动作清单。"""
    limit = int(stuck_seconds) if stuck_seconds else task_stuck_seconds()
    now_dt = now or datetime.now().astimezone()
    rows = events.read(project=project_id)
    actions: list[dict[str, Any]] = []

    for task in db.list_tasks(project_id, db_file=db_file):
        if task.get("exec_status") != "DOING":
            continue
        task_id = str(task["task_id"])
        started_at, doing_seq = _doing_anchor(rows, task_id)
        raw = started_at or task.get("updated_at") or task.get("created_at")
        try:
            started_dt = datetime.fromisoformat(str(raw))
        except (TypeError, ValueError):
            continue
        elapsed = (now_dt - started_dt).total_seconds()
        if elapsed < limit:
            continue

        if elapsed >= limit * ESCALATE_MULTIPLIER:
            db.transition_and_log(
                task_id,
                "BLOCKED",
                actor="rel",
                summary=f"{task_id} 卡死升级：DOING 已持续 {int(elapsed)}s（阈值 {limit}s 的 {ESCALATE_MULTIPLIER} 倍）",
                blocked_reason="stuck_timeout",
                extra={"stuck_seconds": int(elapsed), "threshold_seconds": limit, "multiplier": ESCALATE_MULTIPLIER},
                db_file=db_file,
            )
            events.append(
                actor="rel",
                action="task:stuck_escalated",
                task_id=task_id,
                summary=f"{task_id} 卡死升级为 BLOCKED，等人工释放",
                url=f"/tasks/{task_id}",
                project=task.get("project_id"),
                extra={"stuck_seconds": int(elapsed), "threshold_seconds": limit},
            )
            actions.append({"task_id": task_id, "action": "escalated_blocked", "elapsed_seconds": int(elapsed)})
        elif not _stuck_marked_since(rows, task_id, doing_seq):
            events.append(
                actor="rel",
                action="task:stuck",
                task_id=task_id,
                summary=f"{task_id} 疑似卡死：DOING 已持续 {int(elapsed)}s（阈值 {limit}s）",
                url=f"/tasks/{task_id}",
                project=task.get("project_id"),
                extra={"stuck_seconds": int(elapsed), "threshold_seconds": limit},
            )
            actions.append({"task_id": task_id, "action": "marked_stuck", "elapsed_seconds": int(elapsed)})

    return actions
