"""回环来源判定（identity.json B1）：所有管理面/setup 接口共用。"""

from __future__ import annotations

from fastapi import Request

LOOPBACK_HOSTS = {"127.0.0.1", "::1", "localhost"}


def client_host(request: Request) -> str:
    return str(getattr(request.client, "host", "") or "")


def is_loopback(request: Request) -> bool:
    return client_host(request) in LOOPBACK_HOSTS
