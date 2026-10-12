"""这是什么：Harness 流式输出解析器（P3）。把 CLI 的 stdout 行解析成统一事件流。
统一事件（dataclass HarnessEvent）：type ∈ text | result | session | usage | raw
  claude_stream_json  每行一个 JSON：assistant 消息里的 text 块 → text；
                      result 类型行 → result（含 usage/session_id）
  codex_jsonl         每行一个 JSON：msg.type==agent_message → text；task_complete → result
  opencode_json       整体一个 JSON 或按行 JSON：取 parts 里的 text
  plain               全部按 raw 文本透传，进程正常退出时整段作为 result
解析器只做容错解析：单行解析失败降级为 raw 事件，绝不抛异常中断执行。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Iterator


@dataclass
class HarnessEvent:
    type: str  # text | result | session | usage | raw
    text: str = ""
    data: dict[str, Any] = field(default_factory=dict)


def _safe_json(line: str) -> dict[str, Any] | None:
    line = line.strip()
    if not line.startswith("{"):
        return None
    try:
        data = json.loads(line)
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def parse_claude_stream_json(lines: Iterator[str]) -> Iterator[HarnessEvent]:
    for line in lines:
        data = _safe_json(line)
        if data is None:
            if line.strip():
                yield HarnessEvent(type="raw", text=line.rstrip("\n"))
            continue
        mtype = str(data.get("type") or "")
        if mtype == "assistant":
            message = data.get("message") or {}
            for block in (message.get("content") or []):
                if isinstance(block, dict) and block.get("type") == "text":
                    yield HarnessEvent(type="text", text=str(block.get("text") or ""))
        elif mtype == "result":
            yield HarnessEvent(type="result", text=str(data.get("result") or ""), data=data)
            usage = data.get("usage") or {}
            if usage:
                yield HarnessEvent(type="usage", data={
                    "tokens_in": int(usage.get("input_tokens") or 0),
                    "tokens_out": int(usage.get("output_tokens") or 0),
                })
            if data.get("session_id"):
                yield HarnessEvent(type="session", text=str(data["session_id"]))


def parse_codex_jsonl(lines: Iterator[str]) -> Iterator[HarnessEvent]:
    for line in lines:
        data = _safe_json(line)
        if data is None:
            if line.strip():
                yield HarnessEvent(type="raw", text=line.rstrip("\n"))
            continue
        msg = data.get("msg") if isinstance(data.get("msg"), dict) else data
        mtype = str(msg.get("type") or data.get("type") or "")
        if mtype in ("agent_message", "agent_message_delta"):
            text = msg.get("message") or msg.get("text") or ""
            if text:
                yield HarnessEvent(type="text", text=str(text))
        elif mtype in ("task_complete", "complete"):
            yield HarnessEvent(type="result", text=str(msg.get("last_agent_message") or ""), data=msg)
            usage = msg.get("usage") or {}
            if usage:
                yield HarnessEvent(type="usage", data={
                    "tokens_in": int(usage.get("input_tokens") or usage.get("prompt_tokens") or 0),
                    "tokens_out": int(usage.get("output_tokens") or usage.get("completion_tokens") or 0),
                })
        elif data.get("session_id") or msg.get("session_id"):
            yield HarnessEvent(type="session", text=str(data.get("session_id") or msg.get("session_id")))


def parse_opencode_json(lines: Iterator[str]) -> Iterator[HarnessEvent]:
    for line in lines:
        data = _safe_json(line)
        if data is None:
            if line.strip():
                yield HarnessEvent(type="raw", text=line.rstrip("\n"))
            continue
        # opencode run --format json 输出 JSON 对象；parts 里是文本块
        yield from _opencode_object(data)


def _opencode_object(data: dict[str, Any]) -> Iterator[HarnessEvent]:
    parts = data.get("parts")
    if isinstance(parts, list):
        for part in parts:
            if isinstance(part, dict) and part.get("type") == "text":
                yield HarnessEvent(type="text", text=str(part.get("text") or ""))
    session_id = data.get("sessionID") or data.get("session_id")
    if session_id:
        yield HarnessEvent(type="session", text=str(session_id))
    usage = data.get("usage")
    if not isinstance(usage, dict):
        info = data.get("info")
        usage = info.get("usage") if isinstance(info, dict) else None
    if isinstance(usage, dict) and usage:
        yield HarnessEvent(type="usage", data={
            "tokens_in": int(usage.get("input_tokens") or usage.get("promptTokens") or 0),
            "tokens_out": int(usage.get("output_tokens") or usage.get("completionTokens") or 0),
        })


def parse_plain(lines: Iterator[str]) -> Iterator[HarnessEvent]:
    for line in lines:
        if line.strip():
            yield HarnessEvent(type="raw", text=line.rstrip("\n"))


PARSERS = {
    "claude_stream_json": parse_claude_stream_json,
    "codex_jsonl": parse_codex_jsonl,
    "opencode_json": parse_opencode_json,
    "plain": parse_plain,
}


def get_parser(name: str):
    parser = PARSERS.get(name)
    if parser is None:
        raise ValueError(f"未知 output_parser: {name}（允许 {sorted(PARSERS)}）")
    return parser
