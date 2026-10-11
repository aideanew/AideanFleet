"""这是什么：events outbox → JSONL 导出（SQLite 是唯一事实源，JSONL 只做导出/对接旧链路）。"""

from __future__ import annotations

import json
from pathlib import Path

from .kernel import Kernel


def export_events(kernel: Kernel, target: str | Path, *, limit: int = 5000) -> int:
    """把未发布事件追加写到 JSONL 并标记已发布；返回导出条数。"""
    events = kernel.pending_events(limit=limit)
    if not events:
        return 0
    path = Path(target)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as fh:
        for row in events:
            payload = json.loads(row["payload"] or "{}")
            record = {
                "seq": row["seq"],
                "ts": row["ts"],
                "kind": row["kind"],
                "todoId": row["todo_id"],
                "goalId": row["goal_id"],
                "extra": payload,
            }
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    kernel.mark_events_published([row["seq"] for row in events])
    return len(events)
