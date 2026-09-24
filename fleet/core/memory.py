"""这是什么：Project Memory（CORE-04 · 契约 v1.2 §13.3）。项目级结构化记忆存储。
怎么用：from fleet.core import memory
        memory.record_decision("P-001", title="…", summary="…", task_id="T-001")
        memory.distill_from_report("P-001", task_id="T-001", title="…", report_path="…/report.md")
        memory.record_correction("P-001", title="用户纠正", summary="…")
        header = memory.build_memory_header("P-001", ["M-0001", "M-0002"])
约定：
  - 存储 data/memory/<project_id>.json，原子写（临时文件 + os.replace），只落本地 data/，不上传任何外部服务；
  - 条目 schema 冻结：{id, kind(decision|artifact|fact), title, summary(≤200字), refs[], created_at, task_id}；
  - build_memory_header 每条只渲染 ≤200 字摘要，绝不内嵌全文/全代码；refs 为空时返回空串；
  - id 形如 M-0001，按项目内出现顺序递增，永不复用（只追加，不删除历史条目）。
"""

from __future__ import annotations

import json
import os
import threading
from typing import Any

from . import events
from .db import iso_now
from .paths import paths

#: 条目 kind 枚举（冻结）
KINDS: tuple[str, ...] = ("decision", "artifact", "fact")

#: 摘要上限（字符）
SUMMARY_LIMIT = 200
TITLE_LIMIT = 80

#: 记忆条目 schema（冻结，供 GOV/测试比对）
ENTRY_FIELDS: tuple[str, ...] = ("id", "kind", "title", "summary", "refs", "created_at", "task_id")

_LOCK = threading.Lock()


class MemoryError(Exception):
    """记忆写入相关错误（kind 非法等）。"""


def _store_file(project_id: str):
    return paths().memory_file(str(project_id))


def _read_store(project_id: str) -> dict[str, Any]:
    """读取某项目的记忆存储；不存在/损坏时返回空结构（损坏不抛，保证派工链路不被脏数据卡死）。"""
    target = _store_file(project_id)
    if not target.exists():
        return {"entries": []}
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"entries": []}
    if not isinstance(data, dict) or not isinstance(data.get("entries"), list):
        return {"entries": []}
    return data


def _write_store(project_id: str, data: dict[str, Any]) -> None:
    """原子写：临时文件 + os.replace（Windows 下同目录同名替换，规避 WinError 32 由调用方持锁串行化）。"""
    target = _store_file(project_id)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.parent / f".{target.name}.tmp"
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, target)


def _next_id(entries: list[dict[str, Any]]) -> str:
    return f"M-{len(entries) + 1:04d}"


def _clean_summary(summary: str) -> str:
    """压成单行并截到 200 字（绝不内嵌全文）。"""
    text = " ".join(str(summary or "").split())
    return text[:SUMMARY_LIMIT]


def add_entry(
    project_id: str,
    *,
    kind: str,
    title: str,
    summary: str,
    refs: list[str] | None = None,
    task_id: str | None = None,
    source: str = "decision",
) -> dict[str, Any]:
    """写入一条记忆（append-only），并发 memory:recorded 事件（契约 §13.2）。"""
    if kind not in KINDS:
        raise MemoryError(f"记忆 kind 非法：{kind}（只允许 {'/'.join(KINDS)}）")
    with _LOCK:
        store = _read_store(project_id)
        entries = store.setdefault("entries", [])
        entry = {
            "id": _next_id(entries),
            "kind": kind,
            "title": str(title or "").strip()[:TITLE_LIMIT],
            "summary": _clean_summary(summary),
            "refs": [str(item) for item in (refs or []) if str(item).strip()],
            "created_at": iso_now(),
            "task_id": task_id,
        }
        entries.append(entry)
        _write_store(project_id, store)
    events.append(
        actor="manager",
        action="memory:recorded",
        task_id=task_id,
        summary=f"项目记忆 {entry['id']}（{kind}）：{entry['title'][:60]}",
        project=project_id,
        extra={"memory_id": entry["id"], "kind": kind, "task_id": task_id, "source": source},
    )
    return entry


def record_decision(project_id: str, *, title: str, summary: str, refs: list[str] | None = None,
                    task_id: str | None = None) -> dict[str, Any]:
    """来源①：Manager 重大决策。"""
    return add_entry(project_id, kind="decision", title=title, summary=summary,
                     refs=refs, task_id=task_id, source="decision")


def record_correction(project_id: str, *, title: str, summary: str, refs: list[str] | None = None,
                      task_id: str | None = None) -> dict[str, Any]:
    """来源③：用户在对话中的显式修正。"""
    return add_entry(project_id, kind="fact", title=title, summary=summary,
                     refs=refs, task_id=task_id, source="correction")


def distill_from_report(project_id: str, *, task_id: str, title: str, report_path: str | None,
                        refs: list[str] | None = None) -> dict[str, Any] | None:
    """来源②：任务 DONE 时从六节报告自动提炼 1 条记忆。

    summary = 改动清单 + 关键决策（四要素/模型自述不进摘要），压到 ≤200 字。
    报告缺失或无有效内容时返回 None（不写空记忆、不发事件）。
    """
    from pathlib import Path

    text = ""
    if report_path:
        try:
            text = Path(report_path).read_text(encoding="utf-8", errors="replace")
        except OSError:
            text = ""
    summary = _summarize_report(text)
    if not summary:
        return None
    return add_entry(project_id, kind="artifact", title=title or f"任务 {task_id} 产出",
                     summary=summary, refs=refs or [task_id], task_id=task_id, source="distill")


def _summarize_report(text: str) -> str:
    """从六节报告提取摘要：优先「改动清单」节；无节结构时退化为全文首段。"""
    if not text.strip():
        return ""
    try:
        from fleet.manager import report as report_parser

        sections = report_parser.parse(text)
        parts = [sections.get("改动清单", ""), sections.get("四要素", "")]
    except Exception:
        parts = [text]
    joined = "；".join(" ".join(part.split()) for part in parts if part and part.strip())
    return joined[:SUMMARY_LIMIT]


def load_entries(project_id: str) -> list[dict[str, Any]]:
    """全部条目（按写入顺序）。"""
    return list(_read_store(project_id).get("entries", []))


def get_entries(project_id: str, memory_refs: list[str] | None) -> list[dict[str, Any]]:
    """按 memory_refs 取条目（保持 refs 给定顺序；未知 id 忽略；refs 为空 = 不引用任何记忆）。"""
    if not memory_refs:
        return []
    wanted = [str(item) for item in memory_refs if str(item).strip()]
    if not wanted:
        return []
    by_id = {str(entry.get("id")): entry for entry in load_entries(project_id)}
    return [by_id[ref] for ref in wanted if ref in by_id]


def build_memory_header(project_id: str, memory_refs: list[str] | None) -> str:
    """把引用的记忆条目渲染为 prompt 头部；每条 ≤200 字摘要，绝不内嵌全文/全代码。

    refs 为空或全部未知时返回空串（派工侧据此跳过记忆段，与 v1.1 行为一致）。
    """
    entries = get_entries(project_id, memory_refs)
    if not entries:
        return ""
    lines = ["[PROJECT MEMORY] 项目记忆（摘要，详细内容按需向 Manager 索取）："]
    for entry in entries:
        refs_text = ",".join(entry.get("refs") or []) or "-"
        lines.append(f"- [{entry['id']}|{entry['kind']}] {entry['title']}：{entry['summary']}（refs: {refs_text}）")
    return "\n".join(lines)
