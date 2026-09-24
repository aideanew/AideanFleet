"""这是什么：模型池。把 .env 的"模型池"段读成列表，按 level 升序排（数字小=优先）。
怎么用：from fleet.models import pool;  cands = pool.load_pool();  chain = pool.chain_for("be-1")
关键：api_key 只保存 ${VAR} 占位；真值要用 pool.resolve_key(entry) 现取，绝不写日志。
测试环境（TEST_FLEET_ENV=1）会自动剔除 env_scope=prod 的模型（如 v3/gpt-6-astra）。
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from fleet.core import config


@dataclass(frozen=True)
class ModelEntry:
    """一个候选模型。字段与 .env 模型池段一一对应。"""

    name: str
    level: int
    base_url: str
    model_id: str
    api_key: str  # 永远是 ${VAR} 占位，不是真值
    http_proxy: str = ""
    https_proxy: str = ""
    env_scope: str = "all"
    resolved: bool = False
    cache: bool = False  # Prompt Cache 开关（契约 v1.2 §13.6，FLEET_MODEL_<i>_CACHE，默认 false）


def app_env() -> str:
    """当前运行环境：test / prod。测试环境禁用 env_scope=prod 的模型。"""
    if os.environ.get("TEST_FLEET_ENV") == "1" or os.environ.get("FLEET_ENV", "").lower() == "test":
        return "test"
    return "prod"


def _to_entry(item: dict) -> ModelEntry:
    return ModelEntry(
        name=str(item.get("name", "")),
        level=int(item.get("level", 999)),
        base_url=str(item.get("base_url", "")),
        model_id=str(item.get("model_id", "")),
        api_key=str(item.get("api_key", "")),
        http_proxy=str(item.get("http_proxy", "") or ""),
        https_proxy=str(item.get("https_proxy", "") or ""),
        env_scope=str(item.get("env_scope", "all") or "all"),
        resolved=bool(item.get("resolved")),
        cache=config._as_bool(item.get("cache")),
    )


def load_pool(include_prod: bool | None = None) -> list[ModelEntry]:
    """读取模型池，按 level 升序（数字小=优先）。

    include_prod=None 表示按当前环境自动判定：test 环境不含 env_scope=prod 的模型。
    """
    if include_prod is None:
        include_prod = app_env() != "test"
    entries = [_to_entry(item) for item in config.load("model_pool").get("models", [])]
    if not include_prod:
        entries = [entry for entry in entries if entry.env_scope.lower() != "prod"]
    return sorted(entries, key=lambda entry: (entry.level, entry.name))


def pool_by_name(include_prod: bool | None = None) -> dict[str, ModelEntry]:
    """名字 -> 模型 的字典。"""
    return {entry.name: entry for entry in load_pool(include_prod=include_prod)}


def resolve_key(entry: ModelEntry) -> str | None:
    """取出 api_key 真值；仍是占位（未配置）时返回 None。"""
    return config.unmask(entry.api_key)


def is_available(entry: ModelEntry) -> bool:
    """该模型是否可用于请求（需要 base_url 与可用 key）。"""
    return bool(entry.base_url and entry.resolved)


def role_chain(role_name: str) -> list[str]:
    """角色绑定的模型名链（bind_model_name 顺序即尝试顺序）。"""
    for role in config.load("roles").get("roles", []):
        if role.get("name") == role_name:
            return list(role.get("bind_model_name") or [])
    return []


def chain_for(role_name: str, include_prod: bool | None = None) -> list[ModelEntry]:
    """角色 -> 候选模型列表（按绑定顺序，未绑定的模型名会被跳过）。"""
    catalogue = pool_by_name(include_prod=include_prod)
    chain: list[ModelEntry] = []
    for name in role_chain(role_name):
        entry = catalogue.get(name)
        if entry is not None and entry not in chain:
            chain.append(entry)
    return chain


def describe(entries: list[ModelEntry] | None = None) -> list[dict]:
    """给控制台/日志用的安全描述（不含真值）。"""
    return [
        {
            "name": entry.name,
            "level": entry.level,
            "platform": entry.name,
            "model_id": entry.model_id,
            "env_scope": entry.env_scope,
            "cache": entry.cache,
            "available": is_available(entry),
        }
        for entry in (entries if entries is not None else load_pool())
    ]