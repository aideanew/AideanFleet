"""这是什么：配置与密钥 API（TASK-301，契约 api.json config.fleet.* / setup.secret.put /
setup.model.test / setup.login）。
安全边界（identity.json B2）：secret 值只进不出——无读取接口、响应/日志/事件永不回显。
"""

from __future__ import annotations

import re
import time
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from fleet.core import fleet_toml
from fleet.core.paths import paths
from fleet.executors.base import resolve_cli
from fleet.harness import load_profile
from fleet.console.loopback import is_loopback as _loopback_ok

router = APIRouter(tags=["setup-config"])

ENV_NAME_RE = re.compile(r"^[A-Z][A-Z0-9_]{1,63}$")


def _error(reason: str, message: str, status: int, details: dict | None = None):
    body: dict = {"ok": False, "error": message, "reason": reason}
    if details:
        body["details"] = details
    return JSONResponse(body, status_code=status)


def _secrets_file() -> Path:
    """secrets/.env：<data_dir>/../secrets/.env（resources.json 口径，TASK-301 实测一致）。"""
    return paths().data_dir.parent / "secrets" / ".env"


def _declared_key_envs() -> set[str]:
    try:
        cfg = fleet_toml.load_config()
        return {m.api_key_env for m in cfg.models.values() if m.api_key_env}
    except Exception:
        return set()


def _write_secret(env_name: str, value: str) -> None:
    """写入 secrets/.env（原子替换同名键；权限 600 尽力而为）。"""
    file = _secrets_file()
    file.parent.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []
    if file.exists():
        lines = [line for line in file.read_text(encoding="utf-8").splitlines()
                 if line.strip() and not line.strip().startswith(f"{env_name}=")]
    lines.append(f"{env_name}={value}")
    import os
    import tempfile

    fd, tmp = tempfile.mkstemp(dir=str(file.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write("\n".join(lines) + "\n")
        os.replace(tmp, file)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    try:
        os.chmod(file, 0o600)
    except OSError:
        pass


_SECRET_SHAPE_RE = re.compile(r"sk-[A-Za-z0-9]{20,}")


def _plaintext_secret_shaped(value: str) -> bool:
    """窄口径密钥形态（与 fleet_toml._reject_secret 同源）：sk- 20+ 或私钥块。

    P1.1 修复：原高熵启发式（_looks_like_secret_value）误伤真实 base_url / model_id
    （如 https://api.openai.com/v1、claude-sonnet-4-20250514 均被误判），真实用户保存必 422。
    """
    if _SECRET_SHAPE_RE.search(value):
        return True
    return "-----BEGIN" in value and "PRIVATE KEY-----" in value


# ---------------------------------------------------------------------------
# config.fleet.get / put（owner 会话由 server 中间件保证——管理面 B3）
# ---------------------------------------------------------------------------


def _config_payload(cfg: fleet_toml.FleetConfig) -> dict:
    """config.fleet.get/put 共用的配置投影（P1.1 修复：put 成功路径曾误调
    config_fleet_get() 缺 request 参数，成功保存必 TypeError 500——从未被测试覆盖）。"""
    return {
        "workspace": {"allowed_roots": cfg.allowed_roots},
        "models": {
            name: {"base_url": m.base_url, "model_id": m.model_id,
                   "api_key_env": m.api_key_env, "priority": m.priority}
            for name, m in cfg.models.items()
        },
        "roles": {name: {"harness": r.harness, "models": r.models}
                  for name, r in cfg.roles.items()},
        "runtime": {"scheduler": cfg.scheduler, "lease_minutes": cfg.lease_minutes},
    }


def config_fleet_get(request: Request):
    if not _loopback_ok(request):
        return JSONResponse({"ok": False, "error": "只能在安装 AideanFleet 的电脑上打开控制台",
                             "reason": "FORBIDDEN_NON_LOOPBACK"}, status_code=403)
    cfg = fleet_toml.load_config()
    return {"ok": True, "config": _config_payload(cfg), "sources": cfg.sources}


async def config_fleet_put(request: Request):
    if not _loopback_ok(request):
        return JSONResponse({"ok": False, "error": "只能在安装 AideanFleet 的电脑上打开控制台",
                             "reason": "FORBIDDEN_NON_LOOPBACK"}, status_code=403)
    try:
        body = await request.json()
    except Exception:
        return _error("VALIDATION_FAILED", "请求体必须是 JSON 对象", 422)
    if not isinstance(body, dict):
        return _error("VALIDATION_FAILED", "请求体必须是 JSON 对象", 422)

    models = body.get("models") or {}
    if not isinstance(models, dict):
        return _error("VALIDATION_FAILED", "models 必须是对象", 422)
    for name, entry in models.items():
        if not re.match(r"^[a-z0-9][a-z0-9_-]{0,31}$", str(name)):
            return _error("VALIDATION_FAILED", f"模型名不合法: {name}", 422)
        if entry is None:  # P1.1 merge 语义：null = 删除标记，跳过校验
            continue
        base_url = str(entry.get("base_url") or "")
        if not base_url.startswith(("http://", "https://")):
            return _error("VALIDATION_FAILED", f"{name}.base_url 必须以 http(s):// 开头", 422,
                          {"field": "base_url"})
        api_key_env = str(entry.get("api_key_env") or "")
        if not ENV_NAME_RE.match(api_key_env):
            return _error("VALIDATION_FAILED", f"{name}.api_key_env 形如 [A-Z][A-Z0-9_]", 422,
                          {"field": "api_key_env"})
        if _plaintext_secret_shaped(str(entry.get("model_id") or "")) or \
                _plaintext_secret_shaped(base_url):
            return _error("PLAINTEXT_SECRET", "拒绝形似密钥的值写入 fleet.toml", 422)

    allowed_roots = [str(r) for r in (body.get("workspace") or {}).get("allowed_roots", [])]
    if not allowed_roots:
        # P1.3 单源回退：toml（含 env 覆盖）→ 旧 .env basic → <data_dir>/workspaces，
        # 新装机器不带 workspace 字段保存模型不再 422。
        from fleet.core import roots as workspace_roots

        allowed_roots = workspace_roots.current()
    runtime = body.get("runtime") or {}
    scheduler = str(runtime.get("scheduler") or fleet_toml.load_config().scheduler)
    if scheduler not in ("auto", "step", "off"):
        return _error("VALIDATION_FAILED", "runtime.scheduler 只允许 auto/step/off", 422)
    lease_minutes = int(runtime.get("lease_minutes") or fleet_toml.load_config().lease_minutes)

    current = fleet_toml.load_config()

    # —— P1.1 merge 语义：字段提及的对象 upsert；null = 删除；未提及 = 保留 ——
    # 修复：旧实现全量替换，前端只提交单个模型时清空其余配置、roles:{} 抹掉 planner 绑定。
    merged_models: dict[str, fleet_toml.ModelCfg] = {
        name: fleet_toml.ModelCfg(
            name=m.name, base_url=m.base_url, model_id=m.model_id,
            api_key_env=m.api_key_env, priority=m.priority)
        for name, m in current.models.items()
    }
    for name, entry in models.items():
        if entry is None:  # null = 删除该模型
            merged_models.pop(str(name), None)
            continue
        merged_models[str(name)] = fleet_toml.ModelCfg(
            name=str(name), base_url=str(entry.get("base_url", "")),
            model_id=str(entry.get("model_id", "")),
            api_key_env=str(entry.get("api_key_env", "")),
            priority=int(entry.get("priority", 10)),
        )
    removed_models = set(current.models) - set(merged_models)

    merged_roles: dict[str, fleet_toml.RoleCfg] = {
        name: fleet_toml.RoleCfg(name=r.name, harness=list(r.harness), models=list(r.models))
        for name, r in current.roles.items()
    }
    for name, entry in (body.get("roles") or {}).items():
        if entry is None:  # null = 删除该角色
            merged_roles.pop(str(name), None)
            continue
        merged_roles[str(name)] = fleet_toml.RoleCfg(
            name=str(name), harness=[str(h) for h in entry.get("harness", [])],
            models=[str(m) for m in entry.get("models", [])])
    # 删除模型时同步清理角色引用，防止悬空模型名
    if removed_models:
        for role in merged_roles.values():
            role.models = [m for m in role.models if m not in removed_models]

    # —— P1.1 planner 保底绑定：规划角色无可用模型时自动绑最高优先级模型 ——
    # 保证"保存模型 → 可建目标"金线（小白零操作）；显式配置过 planner.models 的不动。
    planner = merged_roles.get("planner")
    if merged_models and (planner is None or not planner.models):
        best = min(merged_models.values(), key=lambda m: m.priority)
        if planner is None:
            planner = fleet_toml.RoleCfg(name="planner")
            merged_roles["planner"] = planner
        planner.models = [best.name]

    new_cfg = fleet_toml.FleetConfig(
        path=None, allowed_roots=allowed_roots,
        models=merged_models,
        roles=merged_roles,
        scheduler=scheduler, lease_minutes=lease_minutes, sources={},
    )
    # 防御性兜底：roots.current() 理论上永不返回空
    if not new_cfg.allowed_roots:
        return _error("VALIDATION_FAILED", "workspace.allowed_roots 至少一条", 422)

    try:
        target = fleet_toml.save(new_cfg)
    except Exception as exc:
        from fleet.core.config import PlaintextSecretRejected

        if isinstance(exc, PlaintextSecretRejected):
            return _error("PLAINTEXT_SECRET", str(exc), 422)
        return _error("INTERNAL", f"写入 fleet.toml 失败：{exc}", 500)
    reloaded = fleet_toml.load_config()
    return {"ok": True, "config": _config_payload(reloaded),
            "path": str(target),
            "sources": {**reloaded.sources, "allowed_roots": "toml"}}


# ---------------------------------------------------------------------------
# setup.secret.put（回环 + 只写）
# ---------------------------------------------------------------------------


async def secret_put(request: Request, env_name: str):
    if not _loopback_ok(request):
        return JSONResponse({"ok": False, "error": "只能在安装 AideanFleet 的电脑上打开控制台",
                             "reason": "FORBIDDEN_NON_LOOPBACK"}, status_code=403)
    if not ENV_NAME_RE.match(env_name or ""):
        return _error("VALIDATION_FAILED", "env_name 形如 [A-Z][A-Z0-9_]{1,63}", 422)
    declared = _declared_key_envs()
    if env_name not in declared:
        return _error("SECRET_NAME_NOT_DECLARED",
                      f"{env_name} 未在 fleet.toml models.*.api_key_env 中声明（先在第 2 步添加模型）", 422)
    try:
        body = await request.json()
    except Exception:
        return _error("VALIDATION_FAILED", "请求体必须是 JSON 对象", 422)
    value = str((body or {}).get("value") or "")
    if not value or len(value) > 512:
        return _error("VALIDATION_FAILED", "value 必填且 ≤512 字符", 422)
    _write_secret(env_name, value)
    return {"ok": True, "env_name": env_name, "key_present": True}


# ---------------------------------------------------------------------------
# setup.model.test（回环）
# ---------------------------------------------------------------------------


def model_test(request: Request, name: str):
    if not _loopback_ok(request):
        return JSONResponse({"ok": False, "error": "只能在安装 AideanFleet 的电脑上打开控制台",
                             "reason": "FORBIDDEN_NON_LOOPBACK"}, status_code=403)
    cfg = fleet_toml.load_config()
    model = cfg.models.get(name)
    if model is None:
        return _error("MODEL_NOT_FOUND", f"模型 {name} 未配置", 404)
    key = ""
    if model.api_key_env:
        key = __import__("os").environ.get(model.api_key_env, "")
    if not key:
        return _error("SECRET_MISSING", f"{model.api_key_env or 'API key'} 未配置", 409)

    from fleet.models.pool import ModelEntry
    from fleet.models.transport import http_chat_transport

    entry = ModelEntry(name=model.name, level=model.priority, base_url=model.base_url,
                       model_id=model.model_id, api_key=key)
    started = time.monotonic()
    result = http_chat_transport(entry, "ping（连通性测试，请忽略）", timeout=10)
    latency_ms = int((time.monotonic() - started) * 1000)
    detail = "" if result.ok else f"{result.error_code} {result.error_msg}"[:300]
    return {"ok": True, "reachable": bool(result.ok), "latency_ms": latency_ms, "detail": detail}


# ---------------------------------------------------------------------------
# setup.login（回环；MN-02：只拉起官方登录命令，不代填凭据）
# ---------------------------------------------------------------------------


def harness_login(request: Request, harness: str):
    if not _loopback_ok(request):
        return JSONResponse({"ok": False, "error": "只能在安装 AideanFleet 的电脑上打开控制台",
                             "reason": "FORBIDDEN_NON_LOOPBACK"}, status_code=403)
    try:
        profile = load_profile(harness)
    except FileNotFoundError:
        return _error("HARNESS_NOT_FOUND", f"执行体 profile 不存在: {harness}", 404)
    if not profile.login:
        return _error("HARNESS_NOT_FOUND", f"profile {harness} 未声明 login 命令", 404)
    resolved = resolve_cli(profile.login[0])
    if profile.login[0] != resolved and not Path(resolved).exists():
        return _error("HARNESS_NOT_INSTALLED", f"{harness} 未安装，请先在第一步安装", 409)

    import subprocess

    flags = subprocess.CREATE_NEW_CONSOLE if hasattr(subprocess, "CREATE_NEW_CONSOLE") else 0
    try:
        subprocess.Popen(profile.login, creationflags=flags)
    except OSError as exc:
        return _error("HARNESS_NOT_INSTALLED", f"拉起登录终端失败：{exc}", 409)
    return {"ok": True, "launched": True, "command": " ".join(profile.login)}


