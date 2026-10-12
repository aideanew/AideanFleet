"""这是什么：Task Context 预算裁剪（CORE-04 · 契约 v1.2 §13.4）。
怎么用：from fleet.manager import context_budget
        prompt = context_budget.assemble_prompt(pack, memory_header, context_files, pack.context_budget)
要点：
  - 固定顺序 = system_prompt + memory_header + 任务说明（DISPATCH 模板） + 上下文文件内容；
  - 每文件先取"文件头 + 尾部 + 与任务关键词命中段"，单文件上限与总预算双重约束；
  - 超预算按序截断，prompt 尾部附固定清单"（上下文已按预算裁剪，完整文件路径如下，可按需读取）"；
  - 每次组装发 prompt:assembled + budget:check（固定段本身超预算时加发 budget:exceeded），
    唯一出口是 events.jsonl（角色D 纯消费，本模块不做任何熔断决策）。
口径：tokens ≈ 字符数 ÷ 4（契约 §13.7，估算仅供预算裁剪，不冒充服务端计量）。
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from fleet.core import events

#: 截断清单固定句（契约 §13.4，字面冻结）
TRUNCATION_NOTICE = "（上下文已按预算裁剪，完整文件路径如下，可按需读取）"

#: 返工增量模板固定句（契约 §13.5，字面冻结）
REWORK_TEMPLATE_LINE = "这是第 {attempt} 轮返工，只需基于以下增量信息修复，不要重新调查全项目"

#: 单文件默认上限（token，估算口径，≈2000 字符）；可被 assemble_prompt 的 per_file_cap 覆盖。
#: v1.2 实测定稿：8000 预算下 3 个上下文文件场景，单文件 2000 token 过松（新任务降幅仅 54%），
#: 500 token 时总降幅 >80%，且头+尾+关键词命中段对任务执行已足够，完整文件可按清单按需读取。
DEFAULT_PER_FILE_CAP = 500

#: 上下文文件分隔头
_FILE_HEADER = "\n\n[CONTEXT FILE] {path}\n"
_FILE_MISSING = "（文件不存在或不可读）"
_FILE_HARD_TRUNCATED = "\n…（本文件超出本次配额，已截断）\n"

_WORD_RE = re.compile(r"[A-Za-z0-9_\u4e00-\u9fff]{2,}")
_STOPWORDS = frozenset({"什么", "以及", "或者", "但是", "然后", "这个", "那个", "并且", "要求", "任务"})


def estimate_tokens(text: str) -> int:
    """token 估算（契约 §13.7：chars ÷ 4）。"""
    return max(0, len(str(text or "")) // 4)


def extract_keywords(task: Any, limit: int = 8) -> list[str]:
    """从任务标题 + 说明里抽关键词（给段落命中用；简单起步，去停用词，保序去重）。"""
    text = " ".join([
        str(getattr(task, "title", "") or (task.get("title") if isinstance(task, dict) else "") or ""),
        str(getattr(task, "detail", "") or (task.get("detail") if isinstance(task, dict) else "") or ""),
    ])
    seen: list[str] = []
    for word in _WORD_RE.findall(text):
        if word.lower() in _STOPWORDS or word in seen:
            continue
        seen.append(word)
        if len(seen) >= limit:
            break
    return seen


def _trim_file(text: str, keywords: list[str], max_chars: int) -> str:
    """单文件裁剪：文件头 + 尾部 + 关键词命中段（按原文顺序），仍超限再硬截断。"""
    if len(text) <= max_chars:
        return text
    blocks = text.split("\n\n")
    lowered_keywords = [keyword.lower() for keyword in keywords]
    head = blocks[:1]
    tail = blocks[-1:] if len(blocks) > 1 else []
    middle = blocks[1:-1] if len(blocks) > 2 else []
    hits = [block for block in middle if any(keyword in block.lower() for keyword in lowered_keywords)]
    selected: list[str] = []
    for block in [*head, *hits, *tail]:
        if block in selected:
            continue
        selected.append(block)
    joined = "\n\n".join(selected)
    if len(joined) > max_chars:
        return joined[:max_chars] + _FILE_HARD_TRUNCATED
    return joined


def _read_file(path: str) -> str | None:
    try:
        return Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def _emit(
    *,
    project: str | None,
    task_id: str,
    budget: int,
    actual: int,
    fixed_tokens: int,
    files: list[str],
    trimmed: list[str],
    memory_refs: list[str],
    rework: bool,
) -> None:
    """发 prompt:assembled + budget:check（必要时 budget:exceeded），字段见契约 §13.2。"""
    common = {
        "budget": budget,
        "actual": actual,
        "fixed_tokens": fixed_tokens,
        "files": files,
        "trimmed": trimmed,
        "memory_refs": memory_refs,
        "rework": rework,
    }
    events.append(
        actor="manager",
        action="prompt:assembled",
        task_id=task_id,
        summary=f"prompt 组装完成：估算 {actual} tokens / 预算 {budget}（裁剪 {len(trimmed)} 个文件）",
        url=f"/tasks/{task_id}" if task_id else None,
        project=project,
        extra=common,
    )
    events.append(
        actor="manager",
        action="budget:check",
        task_id=task_id,
        summary=f"预算检查：{'未超' if actual <= budget else '超预算'}（{actual}/{budget} tokens）",
        project=project,
        extra={"budget": budget, "actual": actual, "within": actual <= budget},
    )
    if fixed_tokens > budget:
        events.append(
            actor="manager",
            action="budget:exceeded",
            task_id=task_id,
            summary=f"固定段本身超预算（{fixed_tokens}>{budget}），裁剪无法挽回，按原样派工（熔断决策归 GOV-01）",
            project=project,
            extra={"budget": budget, "actual": actual, "oversize_tokens": fixed_tokens - budget},
        )


def assemble_prompt(
    task: Any,
    memory_header: str = "",
    context_files: list[str] | None = None,
    budget: int | None = None,
    *,
    system_prompt: str = "",
    per_file_cap: int = DEFAULT_PER_FILE_CAP,
    emit: bool = True,
) -> str:
    """按契约 §13.4 固定顺序组装派工 prompt，并做预算裁剪。

    task 是 TaskPack（也兼容任务 dict）。返回组装后的完整 prompt 文本。
    """
    from .contracts import TaskPack

    pack = task if isinstance(task, TaskPack) else TaskPack.from_task(task)
    budget = budget if budget is not None else pack.context_budget

    fixed_parts = [part for part in (system_prompt, memory_header, pack.to_prompt()) if part]
    fixed = "\n\n".join(fixed_parts)
    fixed_tokens = estimate_tokens(fixed)
    remaining = budget - fixed_tokens

    files: list[str] = []
    trimmed: list[str] = []
    body_parts: list[str] = []
    for path in context_files or []:
        files.append(path)
        if remaining <= 0:
            trimmed.append(path)
            continue
        text = _read_file(path)
        if text is None:
            body_parts.append(_FILE_HEADER.format(path=path) + _FILE_MISSING)
            trimmed.append(path)
            continue
        allowed_chars = max(1, min(per_file_cap, remaining) * 4)
        content = _trim_file(text, extract_keywords(pack), allowed_chars)
        if len(content) < len(text):
            trimmed.append(path)
        body_parts.append(_FILE_HEADER.format(path=path) + content)
        remaining -= estimate_tokens(content)

    prompt = fixed
    if body_parts:
        prompt = prompt + "\n\n" + "".join(body_parts).lstrip("\n")
    if files:
        prompt = prompt + "\n\n" + TRUNCATION_NOTICE + "\n" + "\n".join(f"- {item}" for item in files)

    actual = estimate_tokens(prompt)
    if emit:
        _emit(
            project=pack.project_id,
            task_id=pack.id,
            budget=budget,
            actual=actual,
            fixed_tokens=fixed_tokens,
            files=files,
            trimmed=trimmed,
            memory_refs=list(pack.memory_refs),
            rework=False,
        )
    return prompt


def assemble_rework_prompt(
    task: Any,
    retry_context: dict[str, Any],
    *,
    fix_instructions: str = "",
    emit: bool = True,
) -> str:
    """返工增量 prompt（契约 §13.5）：只发 retry_context + 修复指令，不重发记忆与全量上下文。

    固定包含模板句"这是第 N 轮返工，只需基于以下增量信息修复，不要重新调查全项目"。
    """
    import json

    from .contracts import TaskPack

    pack = task if isinstance(task, TaskPack) else TaskPack.from_task(task)
    attempt = int(retry_context.get("attempt") or 0) or 1
    header = "\n\n".join([
        "[MANAGER REWORK DISPATCH]",
        f"任务 ID: {pack.id}",
        f"标题: {pack.title}",
        REWORK_TEMPLATE_LINE.format(attempt=attempt),
    ])
    parts = [
        header,
        "增量信息（retry_context，本轮全部已知事实）：",
        "```json",
        json.dumps(retry_context, ensure_ascii=False, indent=2),
        "```",
    ]
    if fix_instructions.strip():
        parts.append("修复指令：\n" + fix_instructions.strip())
    prompt = "\n\n".join(parts)
    if emit:
        _emit(
            project=pack.project_id,
            task_id=pack.id,
            budget=pack.context_budget,
            actual=estimate_tokens(prompt),
            fixed_tokens=estimate_tokens(prompt),
            files=list((retry_context.get("previous_diff") or {}).get("files") or []),
            trimmed=[],
            memory_refs=[],
            rework=True,
        )
    return prompt
