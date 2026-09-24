"""用量聚合器：从 events.jsonl 中解析 token/usage 数据并写入 SQLite"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from .store import record_usage, init_db


def _parse_ts(ts_str: str) -> str:
    """将事件时间戳规范化为 ISO 8601 格式"""
    if not ts_str:
        return datetime.utcnow().isoformat()
    # 尝试解析毫秒格式 2026-09-15T16:26:19.391284+00:00
    for fmt in ("%Y-%m-%dT%H:%M:%S.%f%z", "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S"):
        try:
            dt = datetime.fromisoformat(ts_str)
            return dt.isoformat()
        except (ValueError, TypeError):
            continue
    return ts_str


def _extract_usage_from_event(event: dict[str, Any]) -> dict[str, Any] | None:
    """
    从单条事件中提取 usage 字段。
    仅处理 action=model:call 的事件（携带 usage 对象）。
    """
    action = event.get("action", "")
    if action != "model:call":
        return None

    extra = event.get("extra")
    extra = extra if isinstance(extra, dict) else {}
    usage = extra.get("usage", event.get("usage"))
    if usage is None:
        # 没有 usage 字段视为 0
        return {
            "prompt_tokens": 0,
            "cached_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "call_count": 1,
            "unknown_usage": 1,
        }

    prompt = usage.get("prompt_tokens", 0) or 0
    cached = usage.get("cached_tokens", 0) or 0
    completion = usage.get("completion_tokens", 0) or 0
    total = usage.get("total_tokens", 0) or 0

    if total == 0 and prompt > 0:
        total = prompt + completion

    return {
        "prompt_tokens": prompt,
        "cached_tokens": cached,
        "completion_tokens": completion,
        "total_tokens": total,
        "call_count": 1,
        "unknown_usage": 0,
    }


def scan_events_file(events_path: Path | None = None) -> int:
    """
    扫描 events.jsonl 并将 usage 记录写入 SQLite。
    返回写入的记录数。
    """
    if events_path is None:
        from fleet.core.paths import paths
        events_path = paths().data_dir / "events.jsonl"

    if not events_path.exists():
        return 0

    init_db()
    count = 0

    with open(events_path, "r", encoding="utf-8") as f:
        for line_no, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue

            usage_data = _extract_usage_from_event(event)
            if usage_data is None:
                continue

            ts = _parse_ts(event.get("timestamp", ""))
            meta = event.get("meta")
            meta = meta if isinstance(meta, dict) else {}
            extra = event.get("extra")
            extra = extra if isinstance(extra, dict) else {}
            # core.events 的冻结字段优先；保留旧 meta/顶层格式兼容。
            task_id = event.get("taskId", meta.get("task_id", event.get("task_id", "")))
            project_id = event.get("project", meta.get("project_id", event.get("project_id", "")))
            role = extra.get("role", meta.get("role", ""))
            model = extra.get("model", meta.get("model", event.get("model", "")))

            # 冻结流的seq在轮转后仍稳定；旧格式以文件路径+行号区分。
            identity = (
                ["seq", event["seq"]] if event.get("seq") is not None
                else ["legacy", str(events_path.resolve()), line_no]
            )
            event_key = json.dumps(identity, ensure_ascii=False)
            inserted = record_usage(
                task_id=task_id,
                project_id=project_id,
                role=role,
                model=model,
                timestamp=ts,
                source=f"events.jsonl:{line_no}",
                event_key=event_key,
                **usage_data,
            )
            count += int(inserted)

    return count


def record_manual_usage(
    *,
    task_id: str = "",
    project_id: str = "",
    role: str = "",
    model: str = "",
    prompt_tokens: int = 0,
    cached_tokens: int = 0,
    completion_tokens: int = 0,
    total_tokens: int = 0,
    timestamp: str = "",
) -> None:
    """手动记录一条用量（用于 adapter 回写）"""
    init_db()
    if total_tokens == 0 and prompt_tokens > 0:
        total_tokens = prompt_tokens + completion_tokens
    record_usage(
        task_id=task_id,
        project_id=project_id,
        role=role,
        model=model,
        prompt_tokens=prompt_tokens,
        cached_tokens=cached_tokens,
        completion_tokens=completion_tokens,
        total_tokens=total_tokens,
        call_count=1,
        unknown_usage=0,
        timestamp=timestamp or datetime.utcnow().isoformat(),
        source="manual",
    )


class UsageAggregator:
    """用量聚合器，提供查询和汇总接口"""

    def __init__(self):
        init_db()

    def scan(self, events_path: Path | None = None) -> int:
        """扫描事件文件并聚合用量"""
        return scan_events_file(events_path)

    def by_task(self, task_id: str) -> dict[str, Any]:
        """按任务聚合用量"""
        from .store import sum_usage
        rows = sum_usage(group_by="task_id", task_id=task_id)
        if rows:
            return rows[0]
        return {"period": task_id, "prompt_tokens": 0, "completion_tokens": 0,
                "total_tokens": 0, "call_count": 0, "unknown_usage": 0}

    def by_project(self, project_id: str) -> dict[str, Any]:
        """按项目聚合用量"""
        from .store import sum_usage
        rows = sum_usage(group_by="project_id", project_id=project_id)
        if rows:
            return rows[0]
        return {"period": project_id, "prompt_tokens": 0, "completion_tokens": 0,
                "total_tokens": 0, "call_count": 0, "unknown_usage": 0}

    def by_date(self, since: str | None = None) -> list[dict[str, Any]]:
        """按日期聚合用量"""
        from .store import sum_usage
        return sum_usage(group_by="date", since=since)

    def by_model(self, since: str | None = None) -> list[dict[str, Any]]:
        """按模型聚合用量"""
        from .store import sum_usage
        return sum_usage(group_by="model", since=since)

    def total(self, since: str | None = None) -> dict[str, Any]:
        """获取总用量"""
        from .store import query_usage
        rows = query_usage(since=since)
        total_prompt = sum(r.get("prompt_tokens", 0) for r in rows)
        total_completion = sum(r.get("completion_tokens", 0) for r in rows)
        total_tokens = sum(r.get("total_tokens", 0) for r in rows)
        total_calls = sum(r.get("call_count", 0) for r in rows)
        return {
            "prompt_tokens": total_prompt,
            "completion_tokens": total_completion,
            "total_tokens": total_tokens,
            "call_count": total_calls,
        }
