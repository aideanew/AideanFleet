"""这是什么：事件总线。把"发生过什么"append-only 记到 data/events.jsonl，一行一个 JSON。
怎么用：from fleet.core import events;  events.append(actor="manager", action="task:assigned", task_id="T-001", summary="…")
铁律：seq 单调递增、从 1 开始；任何代码不得修改或删除历史行（本模块只以 "a" 模式打开文件）。
安全：所有字符串进文件前先过 scrub()，命中 Key 形态一律替换成 ${REDACTED}，防止把密钥写进审计流。
"""

from __future__ import annotations

import json
import re
import threading
from pathlib import Path
from typing import Any

from .paths import paths

#: 事件行字段（7 个冻结 + 2 个扩展），见 docs/契约/控制台API.md §3
EVENT_FIELDS: tuple[str, ...] = (
    "seq",
    "timestamp",
    "actor",
    "action",
    "taskId",
    "summary",
    "url",
    "project",
    "extra",
)

#: 脱敏规则：OpenAI 风格 sk- 密钥、40 位大写授权码、Bearer token
_SCRUB_PATTERNS = (
    (re.compile(r"\bsk-[A-Za-z0-9_\-]{6,}"), "${REDACTED}"),
    (re.compile(r"\b[A-Z0-9]{16}\b"), "${REDACTED}"),
    (re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._\-]{8,}"), "Bearer ${REDACTED}"),
)

_LOCK = threading.Lock()
_CACHE = {"size": -1, "seq": 0}


class EventWriteError(Exception):
    """事件写入失败。"""


def scrub(value: Any) -> Any:
    """把字符串里的密钥形态替换成占位；非字符串原样返回。"""
    if isinstance(value, str):
        text = value
        for pattern, replacement in _SCRUB_PATTERNS:
            text = pattern.sub(replacement, text)
        return text
    if isinstance(value, dict):
        return {key: scrub(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [scrub(item) for item in value]
    return value


def events_file() -> Path:
    """事件流文件路径（不存在也不创建；append 时才建）。"""
    return paths().events_file


def _iter_rows(target: Path) -> list[dict[str, Any]]:
    if not target.exists():
        return []
    rows: list[dict[str, Any]] = []
    with target.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows


def max_seq() -> int:
    """当前最大 seq（空文件为 0）。按文件大小做缓存，文件被截断时自动重算。"""
    target = events_file()
    size = target.stat().st_size if target.exists() else 0
    if size == _CACHE["size"]:
        return int(_CACHE["seq"])
    rows = _iter_rows(target)
    seq = max((int(row.get("seq") or 0) for row in rows), default=0)
    _CACHE["size"] = size
    _CACHE["seq"] = seq
    return seq


def append(
    *,
    actor: str,
    action: str,
    task_id: str | None = None,
    summary: str = "",
    url: str | None = None,
    project: str | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """追加一行事件，返回写入的行。seq 在当前最大值上 +1，单调递增。

    文件只以 "a" 模式打开，历史行不可能被本函数改写。
    """
    from .db import iso_now

    if not actor or not action:
        raise EventWriteError("事件必须带 actor 与 action")

    target = events_file()
    target.parent.mkdir(parents=True, exist_ok=True)
    line = {
        "seq": None,  # 占位，稍后填充
        "timestamp": iso_now(),
        "actor": scrub(actor),
        "action": scrub(action),
        "taskId": task_id,
        "summary": scrub(summary),
        "url": url,
        "project": project,
        "extra": scrub(extra) if extra else None,
    }

    with _LOCK:
        seq = max_seq() + 1
        line["seq"] = seq
        payload = json.dumps(line, ensure_ascii=False)
        with target.open("a", encoding="utf-8") as handle:
            handle.write(payload + "\n")
            handle.flush()
        _CACHE["size"] = target.stat().st_size
        _CACHE["seq"] = seq
    return line


def read(
    project: str | None = None,
    since: int = 0,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    """读取事件：只返回 seq > since 的行；可按项目过滤、可截断条数。"""
    rows = _iter_rows(events_file())
    threshold = int(since or 0)
    out = [
        row
        for row in rows
        if int(row.get("seq") or 0) > threshold and (project is None or row.get("project") == project)
    ]
    if limit is not None and limit >= 0:
        out = out[-int(limit) :] if limit else []
    return out


def current_cursor(project: str | None = None) -> int:
    """按项目给出当前游标（该项目的最大 seq；无项目参数则全局最大 seq）。"""
    if project is None:
        return max_seq()
    rows = [row for row in _iter_rows(events_file()) if row.get("project") == project]
    return max((int(row.get("seq") or 0) for row in rows), default=0)


def health() -> bool:
    """事件流健康检查：文件可读（不存在视为 true，首次追加时自动创建）。"""
    target = events_file()
    if not target.exists():
        return True
    try:
        with target.open("r", encoding="utf-8"):
            pass
        return True
    except OSError:
        return False