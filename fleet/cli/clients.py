"""这是什么：worker 的模型客户端装配层（ADR-004 选项 C：只在 fleet/cli 组装，runner 不动）。
怎么用：cmd_worker 从这里取 planner_client / model_for 注入 run_loop。
模型链读取顺序（A-12）：
  1. fleet.toml [roles.<role>].models → [models.<name>]（api_key_env 走环境变量）；
  2. fleet.toml 无 models 时回退旧 .env 模型池（fleet.models.pool.chain_for），保持兼容。
来源始终记录在候选上（供 attempt.model 与日志使用）。
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Callable

from fleet.core import fleet_toml


@dataclass(frozen=True)
class ModelCandidate:
    name: str
    base_url: str
    model_id: str
    api_key_env: str
    source: str  # fleet.toml | env_pool
    entry: object | None  # fleet.models.pool.ModelEntry（env_pool 时为真条目；toml 时为构造条目）

    def key_present(self) -> bool:
        if not self.api_key_env:
            return True
        if os.environ.get(self.api_key_env):
            return True
        # P1.2 热更新：worker/控制台进程启动早于写钥，回退 secrets/.env 调用期解析
        from fleet.core.config import secrets_env_values

        return self.api_key_env in secrets_env_values()


def _entry_from_toml(model_cfg) -> object:
    from fleet.models.pool import ModelEntry

    return ModelEntry(
        name=model_cfg.name,
        level=model_cfg.priority,
        base_url=model_cfg.base_url,
        model_id=model_cfg.model_id,
        api_key=f"${{{model_cfg.api_key_env}}}" if model_cfg.api_key_env else "",
    )


def _toml_chain(role: str) -> list[ModelCandidate]:
    try:
        cfg = fleet_toml.load_config()
    except Exception:
        return []
    role_cfg = cfg.roles.get(role)
    if not role_cfg or not role_cfg.models:
        return []
    out: list[ModelCandidate] = []
    for name in role_cfg.models:
        m = cfg.models.get(name)
        if m is None or not m.base_url:
            continue
        out.append(ModelCandidate(name=m.name, base_url=m.base_url, model_id=m.model_id,
                                  api_key_env=m.api_key_env, source="fleet.toml",
                                  entry=_entry_from_toml(m)))
    return out


def _env_pool_chain(role: str) -> list[ModelCandidate]:
    try:
        from fleet.models import pool

        return [ModelCandidate(name=e.name, base_url=e.base_url, model_id=e.model_id,
                               api_key_env="", source="env_pool", entry=e)
                for e in pool.chain_for(role)]
    except Exception:
        return []


def model_chain(role: str) -> list[ModelCandidate]:
    """角色 → 有序模型候选：fleet.toml 优先，缺失回退旧 .env 池（A-12）。"""
    return _toml_chain(role) or _env_pool_chain(role)


def model_for(role: str) -> str:
    """openai 协议 harness 的桥接模型 id：取链首候选；key 未配置返回空串（不桥接）。"""
    chain = model_chain(role)
    if not chain:
        return ""
    candidate = chain[0]
    return candidate.model_id if candidate.key_present() else ""


def planner_status(role: str = "planner") -> dict:
    """SETUP_INCOMPLETE 三态判定（P1.4）：goals.create 409 hint 的单源。

    返回 {"ready": bool, "state": str, "missing_keys": list, "message": str}：
    - ready：有可用候选（密钥就绪，P1.2 热更新口径）；
    - no_model：toml 与旧 .env 池均无模型 → 引导去设置第 2 步添加模型；
    - no_key：有候选但密钥未填 → 列出待填的 env 名；
    - no_binding：toml 有模型但规划角色未绑定（P1.1 保底后不应出现，防御态）。
    """
    chain = model_chain(role)
    if any(c.key_present() and c.base_url for c in chain):
        return {"ready": True, "state": "ready", "missing_keys": [], "message": ""}
    if chain:
        missing = sorted({c.api_key_env for c in chain
                          if c.api_key_env and not c.key_present()})
        if missing:
            return {"ready": False, "state": "no_key", "missing_keys": missing,
                    "message": f"模型已配置但密钥未填：请到设置填写 {'、'.join(missing)}"}
        return {"ready": False, "state": "no_key", "missing_keys": [],
                "message": "模型候选缺少可用地址，请检查设置里的模型配置"}
    # 链为空：区分"没模型"与"有模型没绑定"
    try:
        cfg = fleet_toml.load_config()
        if cfg.models and not (cfg.roles.get(role) and cfg.roles[role].models):
            return {"ready": False, "state": "no_binding", "missing_keys": [],
                    "message": "规划角色未绑定模型：请到设置重新保存模型配置"}
    except Exception:
        pass
    return {"ready": False, "state": "no_model", "missing_keys": [],
            "message": "还没有配置任何模型：请到设置第 2 步添加规划模型"}


def planner_ready(role: str = "planner") -> bool:
    """SETUP_INCOMPLETE 判定（布尔兼容版）：三态细节见 planner_status。"""
    return planner_status(role)["ready"]


def make_planner_client(role: str = "planner",
                        transport_fn: Callable | None = None) -> Callable[[str], str]:
    """构造 planner_client(prompt) -> str。逐候选尝试；全部失败抛 RuntimeError。

    P1.2 按需构建：链在每次调用时重建（model_chain），worker 启动后才添加的
    模型/角色绑定无需重启即可见；key_present 与 ${VAR} 解析同样走调用期。
    transport_fn 注入用于测试（fleet.models.transport.get_transport 的签名）。
    """
    transport = transport_fn
    if transport is None:
        from fleet.models import transport as transport_mod

        transport = transport_mod.get_transport()

    def client(prompt: str) -> str:
        chain = model_chain(role)
        if not chain:
            raise RuntimeError("规划模型不可用：无任何候选（fleet.toml roles/planner 与旧 .env 模型池均为空）")
        last_error = ""
        for candidate in chain:
            if not candidate.key_present():
                last_error = f"{candidate.name}: 未配置 {candidate.api_key_env}"
                continue
            result = transport(candidate.entry, prompt)
            if getattr(result, "ok", False):
                return result.text
            last_error = (f"{candidate.name}: {getattr(result, 'error_code', '')} "
                          f"{getattr(result, 'error_msg', '')}")[:200]
        raise RuntimeError(f"规划模型不可用（来源={chain[0].source}）：{last_error}")

    return client
