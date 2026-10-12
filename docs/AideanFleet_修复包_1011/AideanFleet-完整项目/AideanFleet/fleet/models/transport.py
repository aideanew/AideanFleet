"""这是什么：模型请求的传输层（标准库 urllib 实现的 OpenAI 兼容 /chat/completions 调用）。
怎么用：from fleet.models import transport;  transport.set_transport(transport.http_chat_transport)
为什么单独一层：router 只管"选哪个模型、什么时候切换"，真正发请求放在这里，单测可注入假实现。
安全：Key 只从环境变量现取，进日志/事件前必须过 config.mask()。
"""

from __future__ import annotations

import json
import socket
import threading
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Callable

from fleet.core import config

from .pool import ModelEntry

#: usage 四键（契约 v1.2 §13.2，字段冻结）
USAGE_FIELDS: tuple[str, ...] = ("prompt_tokens", "cached_tokens", "completion_tokens", "total_tokens")


@dataclass
class TransportResult:
    """一次请求的结果。ok=False 时 error_code 必须是可分类的信号（429/401/timeout…）。"""

    ok: bool
    text: str = ""
    error_code: str | None = None
    error_msg: str = ""
    usage: dict[str, Any] | None = None

    @staticmethod
    def success(text: str, usage: dict[str, Any] | None = None) -> "TransportResult":
        return TransportResult(ok=True, text=text, usage=usage)

    @staticmethod
    def failure(error_code: str, error_msg: str = "") -> "TransportResult":
        return TransportResult(ok=False, error_code=error_code, error_msg=error_msg)


#: 传输函数签名：给一个模型和提示词，返回 TransportResult
Transport = Callable[..., TransportResult]

_TRANSPORT: Transport | None = None


def set_transport(transport: Transport | None) -> Transport | None:
    """注入传输实现（返回旧实现，便于测试恢复）。"""
    global _TRANSPORT
    previous = _TRANSPORT
    _TRANSPORT = transport
    return previous


def get_transport() -> Transport:
    """当前传输实现；未注入时用内置 HTTP 实现。"""
    return _TRANSPORT or http_chat_transport


# ---------------------------------------------------------------------------
# usage 归一（CORE-04 契约 v1.2 §13.2：四键必须齐全，取不到如实填 0，不估算冒充）
# ---------------------------------------------------------------------------


def _as_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def normalize_usage(raw: Any) -> dict[str, int]:
    """把各服务商的 usage 归一成四键。

    cached_tokens 口径：OpenAI 兼容取 prompt_tokens_details.cached_tokens；
    DeepSeek 口径取 prompt_cache_hit_tokens；其余取不到时为 0（如实降级）。
    """
    raw = raw if isinstance(raw, dict) else {}
    prompt_tokens = _as_int(raw.get("prompt_tokens"))
    completion_tokens = _as_int(raw.get("completion_tokens"))
    cached = 0
    details = raw.get("prompt_tokens_details")
    if isinstance(details, dict):
        cached = _as_int(details.get("cached_tokens"))
    if not cached:
        cached = _as_int(raw.get("prompt_cache_hit_tokens"))  # DeepSeek 口径
    if not cached:
        cached = _as_int(raw.get("cached_tokens"))  # 已归一形态直接透传
    total = _as_int(raw.get("total_tokens")) or prompt_tokens + completion_tokens
    return {
        "prompt_tokens": prompt_tokens,
        "cached_tokens": cached,
        "completion_tokens": completion_tokens,
        "total_tokens": total,
    }


# ---------------------------------------------------------------------------
# 稳定前缀注册表（CORE-04 契约 v1.2 §13.6）
# 前缀段 = system_prompt + memory_header，同角色同项目内字节级稳定；
# 内容变化即版本号 +1 重建（provider 前缀缓存要求字节级不变才能命中）。
# ---------------------------------------------------------------------------

_PREFIX_LOCK = threading.Lock()
_PREFIX_CACHE: dict[tuple[str, str], tuple[int, str]] = {}


def set_stable_prefix(role: str, project: str, prefix: str) -> int:
    """登记/更新稳定前缀，返回当前版本号（内容字节级不变则版本号不变）。"""
    key = (str(role or ""), str(project or ""))
    with _PREFIX_LOCK:
        current = _PREFIX_CACHE.get(key)
        if current is not None and current[1] == prefix:
            return current[0]
        version = (current[0] + 1) if current is not None else 1
        _PREFIX_CACHE[key] = (version, prefix)
        return version


def get_stable_prefix(role: str, project: str) -> tuple[int, str]:
    """读取 (版本号, 前缀)；未登记过返回 (0, "")。"""
    with _PREFIX_LOCK:
        return _PREFIX_CACHE.get((str(role or ""), str(project or "")), (0, ""))


def reset_prefix_cache() -> None:
    """测试清理用。"""
    with _PREFIX_LOCK:
        _PREFIX_CACHE.clear()


def _build_messages(entry: ModelEntry, prompt: str, system_prompt: str | None) -> list[dict[str, Any]]:
    """组装 messages：稳定前缀（system）在前，动态后缀（user）在后；开启 CACHE 时透传启用标记。"""
    messages: list[dict[str, Any]] = []
    if system_prompt:
        system_message: dict[str, Any] = {"role": "system", "content": system_prompt}
        if entry.cache:
            # 透传启用标记（Anthropic cache_control 口径）；OpenAI 兼容自动前缀缓存
            # 无需标记也可命中，不识别该字段的服务会忽略（不支持则 cached_tokens 如实为 0）
            system_message["cache_control"] = {"type": "ephemeral"}
        messages.append(system_message)
    messages.append({"role": "user", "content": prompt})
    return messages


def _classify_http_error(status: int, body: str) -> str:
    """把 HTTP 状态码 + 响应体翻译成可分类的信号。"""
    lowered = (body or "").lower()
    if "model_not_found" in lowered or ("model" in lowered and "not found" in lowered):
        return "model_not_found"
    if status == 402 or "quota" in lowered or "insufficient" in lowered or "额度" in body:
        return "quota_exhausted"
    return str(status)


def _build_opener(entry: ModelEntry) -> urllib.request.OpenerDirector:
    """按模型配置的代理建 opener（如 B.AI 需要本地 10808 代理）。"""
    proxies: dict[str, str] = {}
    if entry.http_proxy:
        proxies["http"] = entry.http_proxy
    if entry.https_proxy:
        proxies["https"] = entry.https_proxy
    if proxies:
        return urllib.request.build_opener(urllib.request.ProxyHandler(proxies))
    return urllib.request.build_opener()


def http_chat_transport(
    entry: ModelEntry,
    prompt: str,
    timeout: int = 600,
    system_prompt: str | None = None,
) -> TransportResult:
    """调用 OpenAI 兼容接口。任何异常都转成 TransportResult.failure，不向上抛。"""
    key = config.unmask(entry.api_key)
    if not key:
        return TransportResult.failure("no_key", f"{entry.name} 的 api_key 仍是占位（未配置环境变量）")

    messages = _build_messages(entry, prompt, system_prompt)

    payload = json.dumps({"model": entry.model_id, "messages": messages, "stream": False}).encode("utf-8")
    request = urllib.request.Request(
        url=f"{entry.base_url.rstrip('/')}/chat/completions",
        data=payload,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {key}",
        },
    )

    opener = _build_opener(entry)
    try:
        with opener.open(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as error:
        body = ""
        try:
            body = error.read().decode("utf-8", "replace")[:1000]
        except Exception:  # 读不到 body 也不能让流程崩
            body = ""
        return TransportResult.failure(_classify_http_error(error.code, body), f"HTTP {error.code}: {body}")
    except (socket.timeout, TimeoutError):
        return TransportResult.failure("timeout", f"{entry.name} 请求超时（{timeout}s）")
    except urllib.error.URLError as error:
        return TransportResult.failure("timeout", f"{entry.name} 连接失败：{error.reason}")
    except OSError as error:
        return TransportResult.failure("timeout", f"{entry.name} 网络错误：{error}")

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return TransportResult.failure("bad_response", raw[:500])

    text = _extract_text(data)
    if text is None:
        return TransportResult.failure("bad_response", raw[:500])
    # usage 归一：cached_tokens 如实记录（支持则 >0，不支持为 0，不做假装缓存）
    return TransportResult.success(text, usage=normalize_usage(data.get("usage")))


def _extract_text(data: dict[str, Any]) -> str | None:
    """从 OpenAI 兼容响应里取正文（兼容 choices/message 与 output_text 两种形态）。"""
    choices = data.get("choices")
    if isinstance(choices, list) and choices:
        first = choices[0] or {}
        message = first.get("message") or {}
        content = message.get("content")
        if isinstance(content, str):
            return content
        if isinstance(content, list):  # 部分服务商返回分段内容
            return "".join(str(part.get("text", "")) for part in content if isinstance(part, dict))
        if isinstance(first.get("text"), str):
            return first["text"]
    if isinstance(data.get("output_text"), str):
        return data["output_text"]
    return None