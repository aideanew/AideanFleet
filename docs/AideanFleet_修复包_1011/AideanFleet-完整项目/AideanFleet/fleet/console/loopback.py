"""回环来源判定（identity.json B1）：所有管理面/setup 接口共用。

审计修复（audit/verify-6c40830）：仅凭 TCP 来源是回环不足以证明“是本机用户在操作”——
用户浏览器里任意网站都能向 http://127.0.0.1:3100 发 text/plain 的跨站 POST（无需 CORS 预检，
request.json() 不看 Content-Type），或经 DNS rebinding 以外部域名访问本机端口。免会话的
setup.* / config.fleet.* 因此可被网页改写 fleet.toml 的 base_url 并触发模型连通测试，把密钥
发往第三方。这里追加浏览器来源校验：
- Host 头（若有）必须是回环主机名 → 挡 DNS rebinding；
- Origin 头（若有）必须是回环源 → 挡跨站请求；
- Sec-Fetch-Site 为 cross-site 一律拒绝。
非浏览器客户端（CLI/curl）通常不带 Origin，不受影响。
"""

from __future__ import annotations

from urllib.parse import urlsplit

from fastapi import Request

LOOPBACK_HOSTS = {"127.0.0.1", "::1", "localhost"}


def client_host(request: Request) -> str:
    return str(getattr(request.client, "host", "") or "")


def _hostname(value: str) -> str:
    value = (value or "").strip().lower()
    if not value:
        return ""
    try:
        return (urlsplit(value if "//" in value else f"//{value}").hostname or "").strip("[]")
    except ValueError:
        return "\x00invalid"


def browser_context_ok(request: Request) -> bool:
    headers = request.headers
    host = headers.get("host")
    if host is not None and _hostname(host) not in LOOPBACK_HOSTS:
        return False
    origin = headers.get("origin")
    if origin is not None and origin != "null" and _hostname(origin) not in LOOPBACK_HOSTS:
        return False
    if origin == "null":
        return False
    if (headers.get("sec-fetch-site") or "").lower() == "cross-site":
        return False
    return True


def is_loopback(request: Request) -> bool:
    return client_host(request) in LOOPBACK_HOSTS and browser_context_ok(request)
