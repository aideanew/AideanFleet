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


def _looks_like_secret_value(value: str) -> bool:
    if re.search(r"sk-[A-Za-z0-9]{20,}", value):
        return True
    # 长度 ≥20 且高熵（大小写+数字混杂）视为疑似密钥
    if len(value) >= 20 and re.search(r"[a-z]", value) and re.search(r"[A-Z0-9]", value):
        unique = len(set(value))
        return unique >= max(8, len(value) // 2)
    return False


# ---------------------------------------------------------------------------
# config.fleet.get / put（owner 会话由 server 中间件保证——管理面 B3）
# ---------------------------------------------------------------------------


def config_fleet_get(request: Request):
    if not _loopback_ok(request):
        return JSONResponse({"ok": False, "error": "只能在安装 AideanFleet 的电脑上打开控制台",
                             "reason": "FORBIDDEN_NON_LOOPBACK"}, status_code=403)
    cfg = fleet_toml.load_config()
    payload = {
        "ok": True,
        "config": {
            "workspace": {"allowed_roots": cfg.allowed_roots},
            "models": {
                name: {"base_url": m.base_url, "model_id": m.model_id,
                       "api_key_env": m.api_key_env, "priority": m.priority}
                for name, m in cfg.models.items()
            },
            "roles": {name: {"harness": r.harness, "models": r.models}
                      for name, r in cfg.roles.items()},
            "runtime": {"scheduler": cfg.scheduler, "lease_minutes": cfg.lease_minutes},
        },
        "sources": cfg.sources,
    }
    return payload


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
        base_url = str(entry.get("base_url") or "")
        if not base_url.startswith(("http://", "https://")):
            return _error("VALIDATION_FAILED", f"{name}.base_url 必须以 http(s):// 开头", 422,
                          {"field": "base_url"})
        api_key_env = str(entry.get("api_key_env") or "")
        if not ENV_NAME_RE.match(api_key_env):
            return _error("VALIDATION_FAILED", f"{name}.api_key_env 形如 [A-Z][A-Z0-9_]", 422,
                          {"field": "api_key_env"})
        if _looks_like_secret_value(str(entry.get("model_id") or "")) or \
                _looks_like_secret_value(base_url):
            return _error("PLAINTEXT_SECRET", "拒绝形似密钥的值写入 fleet.toml", 422)

    allowed_roots = [str(r) for r in (body.get("workspace") or {}).get("allowed_roots", [])]
    if not allowed_roots:
        allowed_roots = fleet_toml.load_config().allowed_roots or []
    runtime = body.get("runtime") or {}
    scheduler = str(runtime.get("scheduler") or fleet_toml.load_config().scheduler)
    if scheduler not in ("auto", "step", "off"):
        return _error("VALIDATION_FAILED", "runtime.scheduler 只允许 auto/step/off", 422)
    lease_minutes = int(runtime.get("lease_minutes") or fleet_toml.load_config().lease_minutes)

    current = fleet_toml.load_config()
    new_cfg = fleet_toml.FleetConfig(
        path=None, allowed_roots=allowed_roots,
        models={
            str(name): fleet_toml.ModelCfg(
                name=str(name), base_url=str(entry.get("base_url", "")),
                model_id=str(entry.get("model_id", "")),
                api_key_env=str(entry.get("api_key_env", "")),
                priority=int(entry.get("priority", 10)),
            ) for name, entry in (models or {}).items()
        },
        roles={
            str(name): fleet_toml.RoleCfg(name=str(name),
                                          harness=[str(h) for h in entry.get("harness", [])],
                                          models=[str(m) for m in entry.get("models", [])])
            for name, entry in (body.get("roles") or {}).items()
        },
        scheduler=scheduler, lease_minutes=lease_minutes, sources={},
    )
    # 保持 workspace 白名单语义：至少一条
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
    return {"ok": True, "config": config_fleet_get()["config"],
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


