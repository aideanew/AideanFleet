"""这是什么：fleet.toml 单一配置层（F3/F4 修复：嵌套结构取代编号扁平键，来源优先级唯一）。
优先级（一条规则）：环境变量 > fleet.toml > 内置默认。
怎么用：
    cfg = load_config()                  # FleetConfig dataclass（含来源标注）
    cfg.roles["fe-1"].harness            # ["codex", "opencode"]
    print_config_source()                # doctor --config 打印生效值和来源
格式（密钥只写环境变量名，绝不写值——延续安全铁律）：
    [workspace]
    allowed_roots = ["E:/Demo"]
    [models.agnes]
    base_url = "https://apihub.agnes-ai.com/v1"
    model_id = "agnes-3.0-flash"
    api_key_env = "AGNES_API_KEY"
    priority = 5
    [roles.fe-1]
    harness = ["codex", "opencode"]
    models  = ["agnes", "modelscope"]
    [runtime]
    scheduler = "auto"
解析用 Python 3.11 内置 tomllib，零新增依赖。
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
import re
from pathlib import Path
from typing import Any

from .paths import paths

CONFIG_NAME = "fleet.toml"


@dataclass
class ModelCfg:
    name: str
    base_url: str = ""
    model_id: str = ""
    api_key_env: str = ""
    priority: int = 10

    def key_present(self) -> bool:
        """密钥是否已配置：os.environ 优先，回退 secrets/.env（P1.2 热更新）。

        控制台/worker 进程启动早于用户写钥，环境变量未见时从密钥文件
        调用期解析——/setup 的 key_present 指示与 doctor 无需重启即正确。
        """
        if not self.api_key_env:
            return False
        if os.environ.get(self.api_key_env):
            return True
        from .config import secrets_env_values

        return self.api_key_env in secrets_env_values()


@dataclass
class RoleCfg:
    name: str
    harness: list[str] = field(default_factory=list)
    models: list[str] = field(default_factory=list)


@dataclass
class FleetConfig:
    path: Path | None
    allowed_roots: list[str] = field(default_factory=list)
    models: dict[str, ModelCfg] = field(default_factory=dict)
    roles: dict[str, RoleCfg] = field(default_factory=dict)
    scheduler: str = "auto"
    lease_minutes: int = 15
    sources: dict[str, str] = field(default_factory=dict)  # 生效键 -> env|toml|default


def _source(sources: dict[str, str], key: str, where: str) -> None:
    sources[key] = where


def _load_toml(explicit: str | Path | None) -> tuple[dict[str, Any], Path | None]:
    if explicit:
        path = Path(explicit)
        if not path.is_file():
            raise FileNotFoundError(f"fleet.toml 不存在: {path}")
        return tomllib.loads(path.read_text(encoding="utf-8")), path
    env_path = os.environ.get("FLEET_TOML")
    if env_path:
        path = Path(env_path)
        if path.is_file():
            return tomllib.loads(path.read_text(encoding="utf-8")), path
        return {}, None
    candidate = paths().root / CONFIG_NAME
    if candidate.is_file():
        return tomllib.loads(candidate.read_text(encoding="utf-8")), candidate
    return {}, None


def _env_overrides() -> dict[str, str]:
    """进程环境变量里可覆盖的键（F4：优先级只有一条，env > toml > 默认）。"""
    overrides: dict[str, str] = {}
    if os.environ.get("FLEET_ALLOWED_ROOTS"):
        overrides["allowed_roots"] = os.environ["FLEET_ALLOWED_ROOTS"]
    if os.environ.get("FLEET_SCHEDULER"):
        overrides["scheduler"] = os.environ["FLEET_SCHEDULER"]
    return overrides


def load_config(path: str | Path | None = None) -> FleetConfig:
    """加载并合并配置：默认 < fleet.toml < 环境变量；每个生效键记录来源。"""
    data, source_path = _load_toml(path)
    sources: dict[str, str] = {}

    allowed = [str(r) for r in (data.get("workspace") or {}).get("allowed_roots", [])]
    _source(sources, "allowed_roots", "toml" if allowed else "default")
    scheduler = str((data.get("runtime") or {}).get("scheduler", "auto"))
    _source(sources, "scheduler", "toml" if "runtime" in data else "default")
    lease_minutes = int((data.get("runtime") or {}).get("lease_minutes", 15))
    _source(sources, "lease_minutes", "toml" if "runtime" in data else "default")

    models: dict[str, ModelCfg] = {}
    for name, raw in (data.get("models") or {}).items():
        models[str(name)] = ModelCfg(
            name=str(name),
            base_url=str(raw.get("base_url", "")),
            model_id=str(raw.get("model_id", "")),
            api_key_env=str(raw.get("api_key_env", "")),
            priority=int(raw.get("priority", 10)),
        )
        _source(sources, f"models.{name}", "toml")
    roles: dict[str, RoleCfg] = {}
    for name, raw in (data.get("roles") or {}).items():
        roles[str(name)] = RoleCfg(
            name=str(name),
            harness=[str(h) for h in raw.get("harness", [])],
            models=[str(m) for m in raw.get("models", [])],
        )
        _source(sources, f"roles.{name}", "toml")

    overrides = _env_overrides()
    if "allowed_roots" in overrides:
        allowed = [r.strip() for r in overrides["allowed_roots"].split(",") if r.strip()]
        _source(sources, "allowed_roots", "env")
    if "scheduler" in overrides:
        scheduler = overrides["scheduler"]
        _source(sources, "scheduler", "env")

    return FleetConfig(
        path=source_path,
        allowed_roots=allowed,
        models=models,
        roles=roles,
        scheduler=scheduler,
        lease_minutes=lease_minutes,
        sources=sources,
    )


def lease_seconds_or_default() -> int:
    """[runtime].lease_minutes（分钟，设置页 UI 旋钮）→ 内核租约秒数。

    修复断链9：此前 5 处 Kernel 构造点全部不传 lease_seconds，内核恒用
    DEFAULT_LEASE_SECONDS（900s），设置页的 lease_minutes 旋钮空转。
    默认 15min → 900s，与 fleet/kernel/kernel.py DEFAULT_LEASE_SECONDS
    一致（tests/core/test_lease_wiring.py 锁定该等式）。
    """
    try:
        return int(load_config().lease_minutes) * 60
    except Exception:
        return 900


def print_config_source(cfg: FleetConfig) -> str:
    """doctor --config 输出：生效值 + 来源（env/toml/default）。"""
    lines = [f"fleet.toml: {cfg.path if cfg.path else '（未找到，使用默认 + 环境变量）'}", ""]
    lines.append(f"allowed_roots = {cfg.allowed_roots}  [{cfg.sources.get('allowed_roots', '?')}]")
    lines.append(f"scheduler   = {cfg.scheduler}  [{cfg.sources.get('scheduler', '?')}]")
    lines.append(f"lease_minutes = {cfg.lease_minutes}  [{cfg.sources.get('lease_minutes', '?')}]")
    if cfg.models:
        lines.append("")
        lines.append("[models]")
        for name, m in cfg.models.items():
            key_state = f"key={m.api_key_env}: {'已配置' if m.key_present() else '未配置'}"
            lines.append(f"  {name}: {m.base_url} / {m.model_id} (priority={m.priority}, {key_state})")
    if cfg.roles:
        lines.append("")
        lines.append("[roles]")
        for name, r in cfg.roles.items():
            lines.append(f"  {name}: harness={r.harness} models={r.models}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# save（TASK-302）：按 FleetConfig 校验后原子写 fleet.toml（零依赖 TOML 序列化）
# ---------------------------------------------------------------------------


def _toml_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    return json_dumps(value)


def json_dumps(value: Any) -> str:
    import json as _json

    return _json.dumps(value, ensure_ascii=False)


def _reject_secret(value: str) -> None:
    """拒绝形似明文密钥的值（复用旧链路 config 的密钥形态检测语义）。"""
    import re

    if re.search(r"sk-[A-Za-z0-9]{20,}", value):
        from .config import PlaintextSecretRejected

        raise PlaintextSecretRejected("疑似明文 API key（sk- 开头），只允许 ${VAR} 占位或环境变量名")
    if re.search(r"-----BEGIN [A-Z ]*PRIVATE KEY-----", value):
        from .config import PlaintextSecretRejected

        raise PlaintextSecretRejected("疑似私钥内容，拒绝写入 fleet.toml")


def save(cfg: FleetConfig, path: str | Path | None = None) -> Path:
    """FleetConfig → fleet.toml（临时文件 + os.replace 原子写）。写后可 load_config 回读。"""
    import os
    import tempfile

    target = Path(path) if path else (cfg.path or paths().root / CONFIG_NAME)
    lines: list[str] = []

    if cfg.allowed_roots:
        lines.append("[workspace]")
        lines.append(f"allowed_roots = {_toml_value(cfg.allowed_roots)}")
        lines.append("")
    if cfg.models:
        for name in cfg.models:
            m = cfg.models[name]
            lines.append(f"[models.{name}]")
            lines.append(f'base_url = "{m.base_url}"')
            lines.append(f'model_id = "{m.model_id}"')
            lines.append(f'api_key_env = "{m.api_key_env}"')
            lines.append(f"priority = {m.priority}")
            lines.append("")
    if cfg.roles:
        for name in cfg.roles:
            r = cfg.roles[name]
            lines.append(f"[roles.{name}]")
            lines.append(f"harness = {_toml_value(r.harness)}")
            lines.append(f"models = {_toml_value(r.models)}")
            lines.append("")
    lines.append("[runtime]")
    lines.append(f'scheduler = "{cfg.scheduler}"')
    lines.append(f"lease_minutes = {cfg.lease_minutes}")
    lines.append("")

    content = "\n".join(lines)
    for line_value in re.findall(r'"([^"]*)"', content):
        _reject_secret(line_value)

    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=str(target.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(content)
        os.replace(tmp_name, target)
    except Exception:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise
    return target
