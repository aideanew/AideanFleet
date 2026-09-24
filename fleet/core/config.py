"""这是什么：配置中心。把 .env 分成七段读取/写回，是"读 .env 驱动全部行为"的唯一入口。
怎么用：from fleet.core import config;  config.ensure_env_file();  cfg = config.load("notify")
要点：每次 load 都看文件 mtime，文件变了就重新解析（无缓存语义）；save 用临时文件 + os.replace 原子写；
     只有控制台进程允许写，引擎侧只读（调 save 会抛 ConfigWriteDenied）。
安全：文件里只允许 ${VAR} 占位，真值从系统环境变量取；save 会拒绝明文密钥写入。
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .paths import paths

# ---------------------------------------------------------------------------
# secrets/.env 真值注入（模块导入时一次性执行，幂等 setdefault）：
# ${VAR} 解析依赖 os.environ；把 secrets/.env 的真值设为系统环境变量数据源，
# 使 server/watch/launcher/测试等所有进程无需各自加载。外部显式设置的变量优先。
# ---------------------------------------------------------------------------
_SECRETS_FILE = Path(
    os.environ.get(
        "FLEET_SECRETS_PATH",
        str(Path(__file__).resolve().parent.parent.parent / "secrets" / ".env"),
    )
)
if _SECRETS_FILE.exists():
    for _line in _SECRETS_FILE.read_text(encoding="utf-8").splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _k, _, _v = _line.partition("=")
            os.environ.setdefault(_k.strip(), _v.strip())

# ---------------------------------------------------------------------------
# 常量：七段（字段名冻结，见 docs/契约/控制台API.md §5）
# ---------------------------------------------------------------------------

SECTIONS: tuple[str, ...] = ("basic", "model_pool", "roles", "executors", "email", "notify", "request", "settings")

#: 列表型段（值以索引组织：FLEET_MODEL_1_NAME ...）
LIST_SECTIONS: tuple[str, ...] = ("model_pool", "roles", "executors")

#: 各列表段的前缀与字段顺序（写回 .env 时按此顺序输出，保证 diff 稳定）
LIST_LAYOUT: dict[str, tuple[str, tuple[str, ...]]] = {
    "model_pool": (
        "MODEL",
        ("NAME", "LEVEL", "BASE_URL", "MODEL_ID", "API_KEY", "HTTP_PROXY", "HTTPS_PROXY", "ENV_SCOPE", "CACHE"),
    ),
    "roles": ("ROLE", ("NAME", "SYSTEM_PROMPT", "BIND_MODEL_NAME", "ADAPTER")),
    "executors": ("EXECUTOR", ("NAME", "COMMAND", "TIMEOUT")),
}

#: 标量段的键令牌（去掉 FLEET_ 与令牌后小写即为对外键名）
SECTION_TOKEN: dict[str, str] = {"basic": "", "email": "SMTP_", "notify": "NOTIFY_", "request": "REQUEST_", "settings": "SETTINGS_"}  # REL-01：settings 段（可靠性参数）

#: 立刻失败的错误信号（工作包 §9.4-2：不空耗 10 次）
HARD_FAIL_SIGNALS: tuple[str, ...] = ("401", "402", "403", "quota_exhausted", "model_not_found")

_SECTION_RE = re.compile(r"^\s*#\s*=+\s*\[SECTION:\s*([A-Za-z_]+)\]\s*(.*?)\s*=+\s*$")
_PLACEHOLDER_RE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")
_SECRET_SHAPES = (re.compile(r"\bsk-[A-Za-z0-9_\-]{8,}"), re.compile(r"^[A-Z0-9]{16}$"))
_TRUE_WORDS = {"1", "true", "yes", "on", "enable", "enabled"}


class ConfigError(Exception):
    """配置相关错误的基类。"""


class UnknownSection(ConfigError):
    """段名不在七段之内。"""


class ConfigWriteDenied(ConfigError):
    """引擎侧（非控制台进程）试图写配置。"""


class PlaintextSecretRejected(ConfigError):
    """试图把明文密钥写进 .env；只允许写 ${VAR} 占位。"""


# ---------------------------------------------------------------------------
# 小工具：类型转换 / 占位解析 / 脱敏
# ---------------------------------------------------------------------------


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value != 0
    return str(value).strip().lower() in _TRUE_WORDS


def _as_int(value: Any, default: int = 0) -> int:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return default


def _as_list(value: Any) -> list[str]:
    if isinstance(value, (list, tuple)):
        return [str(v).strip() for v in value if str(v).strip()]
    return [item.strip() for item in str(value or "").split(",") if item.strip()]


def is_placeholder(value: str | None) -> bool:
    """判断是不是 ${VAR} 形态的占位。"""
    return bool(value) and _PLACEHOLDER_RE.search(str(value)) is not None


def resolve_placeholders(value: str, env: dict[str, str] | None = None, depth: int = 0) -> str:
    """把 ${VAR} 换成真值：先查传入的 env（.env 自身），再查系统环境变量。

    两处都取不到时**原样保留占位**，调用方据此判断"未配置"。
    """
    env = env or {}

    def _sub(match: re.Match[str]) -> str:
        name = match.group(1)
        if name in env:
            inner = env[name]
            return resolve_placeholders(inner, env, depth + 1) if depth < 1 else inner
        if name in os.environ:
            return os.environ[name]
        return match.group(0)

    return _PLACEHOLDER_RE.sub(_sub, value)


def unmask(value: str | None) -> str | None:
    """解析出真值；仍是占位则返回 None（表示"未配置"）。"""
    if value is None:
        return None
    resolved = resolve_placeholders(str(value))
    return None if _PLACEHOLDER_RE.search(resolved) else resolved


def mask(value: str | None) -> str:
    """日志/API 输出用：绝不打印真值。占位原样返回，其他一律 `***`。"""
    if value is None or value == "":
        return ""
    return value if is_placeholder(value) else "***"


def looks_like_plaintext_secret(value: Any) -> bool:
    """判断值是否像明文密钥（save 时用于拒绝写盘）。"""
    text = str(value or "").strip()
    if not text or is_placeholder(text):
        return False
    return any(pattern.search(text) for pattern in _SECRET_SHAPES)


# ---------------------------------------------------------------------------
# 解析：.env 文本 -> (键值, 键->段名)
# ---------------------------------------------------------------------------


def parse_env_text(text: str) -> tuple[dict[str, str], dict[str, str]]:
    """解析 .env 内容；返回 (键值, 键->段名)。段外的键归入 basic。"""
    values: dict[str, str] = {}
    section_of: dict[str, str] = {}
    current = "basic"
    for line in text.splitlines():
        marker = _SECTION_RE.match(line)
        if marker:
            current = marker.group(1).strip().lower()
            continue
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, _, raw = stripped.partition("=")
        key = key.strip()
        if not key:
            continue
        values[key] = raw.strip()
        section_of[key] = current
    return values, section_of


def _normalize_key(env_key: str, section: str) -> str:
    """标量键规范化：FLEET_NOTIFY_ON_TASK_START -> on_task_start。"""
    name = env_key[len("FLEET_") :] if env_key.startswith("FLEET_") else env_key
    token = SECTION_TOKEN.get(section, "")
    if token and name.upper().startswith(token):
        name = name[len(token) :]
    return name.lower()


def _scalar_key(section: str, name: str) -> str:
    """反向：对外键名 -> .env 键名。"""
    return f"FLEET_{SECTION_TOKEN.get(section, '')}{name.upper()}"


def _indexed_key(section: str, index: int, field_name: str) -> str:
    token, _ = LIST_LAYOUT[section]
    return f"FLEET_{token}_{index}_{field_name.upper()}"


def _group_indexed(values: dict[str, str], section: str) -> list[dict[str, str]]:
    """把 FLEET_MODEL_1_NAME / FLEET_MODEL_1_LEVEL ... 聚合成 [{name, level, ...}, ...]。"""
    token, fields = LIST_LAYOUT[section]
    prefix = f"FLEET_{token}_"
    buckets: dict[int, dict[str, str]] = {}
    for key, raw in values.items():
        if not key.startswith(prefix):
            continue
        rest = key[len(prefix) :]
        head, _, tail = rest.partition("_")
        if not head.isdigit() or tail.upper() not in fields:
            continue
        buckets.setdefault(int(head), {})[tail.lower()] = raw
    out: list[dict[str, str]] = []
    for index in sorted(buckets):
        item = {"index": str(index)}
        item.update(buckets[index])
        out.append(item)
    return out


# ---------------------------------------------------------------------------
# 读取：ensure_env_file / load / raw / mtime 缓存
# ---------------------------------------------------------------------------


@dataclass
class _Cache:
    """只按 mtime 失效的解析缓存（"无缓存语义"指永远以磁盘为准）。"""

    mtime_ns: int | None = None
    values: dict[str, str] = field(default_factory=dict)
    section_of: dict[str, str] = field(default_factory=dict)


_CACHE = _Cache()


def ensure_env_file(target: Path | None = None) -> Path:
    """首次运行检测 .env 不存在 → 从 .env.example 原样复制。

    已存在时**绝不覆盖**（用户改过的配置不能被模板冲掉）。
    返回 .env 路径；.env.example 缺失时抛 ConfigError。
    """
    p = paths()
    env_file = Path(target) if target else p.env_file
    if env_file.exists():
        return env_file
    template = p.env_example_file
    if not template.exists():
        raise ConfigError(f".env.example 不存在，无法初始化配置：{template}")
    env_file.parent.mkdir(parents=True, exist_ok=True)
    env_file.write_text(template.read_text(encoding="utf-8"), encoding="utf-8")
    return env_file


def _load_raw() -> tuple[dict[str, str], dict[str, str]]:
    """按 mtime 判断是否重新解析；返回 (键值, 键->段)。"""
    env_file = ensure_env_file()
    stat = env_file.stat()
    if _CACHE.mtime_ns != stat.st_mtime_ns:
        values, section_of = parse_env_text(env_file.read_text(encoding="utf-8"))
        _CACHE.mtime_ns = stat.st_mtime_ns
        _CACHE.values = values
        _CACHE.section_of = section_of
    return _CACHE.values, _CACHE.section_of


def raw() -> dict[str, str]:
    """返回 .env 的全部键值（含 ${VAR} 占位，未解析）。"""
    values, _ = _load_raw()
    return dict(values)


def env_setting(name: str, default: str = "") -> str:
    """读主 .env 的单个通用开关键（不属于七段的顶层 KEY=VALUE，如 FLEET_SCHEDULER_MODE）。

    模块级注入只处理 secrets/.env，主 .env 的顶层键不会进 os.environ，进程级开关需显式读取。
    键缺失回退 default；${VAR} 占位经 resolve_placeholders 解析。
    """
    value = raw().get(name, "")
    if not value:
        return default
    resolved = resolve_placeholders(value)
    return resolved or default


def env_source() -> Path:
    """当前 .env 文件路径。"""
    return ensure_env_file()


def env_mtime() -> str | None:
    """当前 .env 的 mtime（ISO-8601 带时区）；不存在返回 None。"""
    env_file = ensure_env_file()
    if not env_file.exists():
        return None
    return _iso_from_epoch(env_file.stat().st_mtime)


def _iso_from_epoch(epoch: float) -> str:
    from datetime import datetime, timezone

    return datetime.fromtimestamp(epoch, tz=timezone.utc).astimezone().isoformat(timespec="seconds")


def load(section: str) -> dict[str, Any]:
    """读取某一段，返回结构化字典（字段口径见 docs/契约/控制台API.md §5）。"""
    section = str(section or "").strip().lower()
    if section not in SECTIONS:
        raise UnknownSection(f"未知配置段：{section}；合法段：{', '.join(SECTIONS)}")

    values, section_of = _load_raw()
    if section in LIST_SECTIONS:
        items = [_build_list_item(section, item, values) for item in _group_indexed(values, section)]
        return {_list_key(section): items}

    mine = {k: v for k, v in values.items() if section_of.get(k) == section}
    return _build_scalar_section(section, mine)


def _list_key(section: str) -> str:
    return {"model_pool": "models", "roles": "roles", "executors": "executors"}[section]


def _build_list_item(section: str, item: dict[str, str], values: dict[str, str]) -> dict[str, Any]:
    """把索引桶转成对外结构；model_pool 的 api_key 永远是占位串，绝不返回真值。"""
    if section == "model_pool":
        api_key = item.get("api_key", "")
        resolved = resolve_placeholders(api_key, values) if api_key else ""
        return {
            "name": item.get("name", ""),
            "level": _as_int(item.get("level"), 999),
            "base_url": item.get("base_url", ""),
            "model_id": item.get("model_id", ""),
            "api_key": api_key,
            "http_proxy": item.get("http_proxy", ""),
            "https_proxy": item.get("https_proxy", ""),
            "env_scope": item.get("env_scope", "all") or "all",
            "resolved": bool(resolved) and "$" not in resolved,
            "cache": _as_bool(item.get("cache")),  # v1.2：Prompt Cache 开关，非 true 值一律 false（默认关）
        }
    if section == "roles":
        return {
            "name": item.get("name", ""),
            "system_prompt": item.get("system_prompt", ""),
            "bind_model_name": _as_list(item.get("bind_model_name", "")),
            "adapter": item.get("adapter", ""),
        }
    return {
        "name": item.get("name", ""),
        "command": item.get("command", ""),
        "timeout": _as_int(item.get("timeout"), 600),
    }


#: 标量段结构：(对外键名, 类型, 缺省值)。类型为 bool/int/list/str。
_SCALAR_SPECS: dict[str, tuple[tuple[str, Any, Any], ...]] = {
    "basic": (
        ("project_name", str, "AideanFleet"),
        ("console_host", str, "127.0.0.1"),
        ("console_port", int, 5000),
        ("manager_port", int, 9900),
        ("ui_port", int, 3333),
        ("allowed_roots", list, []),
        ("default_project", str, "AideanFleet"),
        ("timezone", str, "Asia/Shanghai"),
        ("lock_ttl_minutes", int, 60),
    ),
    "email": (
        ("enabled", bool, False),
        ("sender", str, ""),
        ("receiver", str, ""),
        ("host", str, ""),
        ("port", int, 465),
        ("auth_code", str, ""),
        ("use_ssl", bool, True),
    ),
    "notify": (
        ("on_task_start", bool, False),
        ("on_task_end", bool, True),
        ("on_manager_quota", bool, True),
        ("on_role_quota", bool, True),
    ),
    "request": (
        ("timeout", int, 600),
        ("retry_max", int, 10),
        ("retry_delay", int, 10),
    ),
    # REL-01：settings 段（可靠性参数），键名冻结见契约 v1.2 增补注记 §14.4
    "settings": (
        ("task_stuck_seconds", int, 1800),
    ),
}

#: 只允许写 ${VAR} 占位的键（写入明文直接拒绝）
PLACEHOLDER_ONLY_FIELDS: frozenset[str] = frozenset({"api_key", "auth_code", "sender", "receiver", "host"})


def _build_scalar_section(section: str, mine: dict[str, str]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for name, kind, default in _SCALAR_SPECS.get(section, ()):
        env_key = _scalar_key(section, name)
        if env_key not in mine:
            out[name] = default
            continue
        value = mine[env_key]
        if kind is bool:
            out[name] = _as_bool(value)
        elif kind is int:
            out[name] = _as_int(value, default)
        elif kind is list:
            out[name] = _as_list(value)
        else:
            out[name] = value
    return out


def known_scalar_keys(section: str) -> set[str]:
    """该段已知的对外键名集合（save 时用于判定 ignored）。"""
    return {name for name, _, _ in _SCALAR_SPECS.get(section, ())}


# ---------------------------------------------------------------------------
# 写入：只有控制台进程允许写；原子写（临时文件 + os.replace）
# ---------------------------------------------------------------------------

_WRITER_ENABLED = False


def allow_write(enabled: bool = True) -> bool:
    """由控制台进程启动时调用（工作包 §9.2-5：引擎侧只读）。

    返回设置前的状态，便于测试里恢复。
    """
    global _WRITER_ENABLED
    previous = _WRITER_ENABLED
    _WRITER_ENABLED = bool(enabled)
    return previous


def write_enabled() -> bool:
    """当前进程是否有写权限（环境变量 FLEET_CONFIG_WRITE=1 可显式放行）。"""
    if os.environ.get("FLEET_CONFIG_WRITE") == "1":
        return True
    return _WRITER_ENABLED


def _format_value(value: Any) -> str:
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, (list, tuple)):
        return ",".join(str(item).strip() for item in value)
    return str(value).replace("\r", " ").replace("\n", " ").strip()


def _existing_list_indices(section: str) -> list[int]:
    values, _ = _load_raw()
    return [int(item["index"]) for item in _group_indexed(values, section)]


def _build_patches(section: str, data: dict[str, Any]) -> tuple[dict[str, str], list[str], set[str]]:
    """把请求体翻译成 .env 键值补丁；返回 (补丁, 被忽略的键, 需删除的键)。"""
    patches: dict[str, str] = {}
    ignored: list[str] = []
    deletes: set[str] = set()

    if section in LIST_SECTIONS:
        list_key = _list_key(section)
        raw_items = data.get(list_key)
        _, fields = LIST_LAYOUT[section]
        if raw_items is not None:
            if not isinstance(raw_items, (list, tuple)):
                ignored.append(list_key)
            else:
                known_fields = {f.lower() for f in fields}
                for index, item in enumerate(raw_items, start=1):
                    if not isinstance(item, dict):
                        ignored.append(f"{list_key}[{index}]")
                        continue
                    for field_name, value in item.items():
                        if field_name == "index":
                            continue
                        if field_name not in known_fields:
                            ignored.append(f"{list_key}[{index}].{field_name}")
                            continue
                        if field_name in PLACEHOLDER_ONLY_FIELDS and looks_like_plaintext_secret(value):
                            raise PlaintextSecretRejected(
                                f"{list_key}[{index}].{field_name} 含明文密钥，只允许写 ${{VAR}} 占位"
                            )
                        patches[_indexed_key(section, index, field_name)] = _format_value(value)
                for stale in _existing_list_indices(section)[len(raw_items) :]:
                    for field_name in fields:
                        deletes.add(_indexed_key(section, stale, field_name))
        for key in data:
            if key != list_key:
                ignored.append(key)
        return patches, ignored, deletes

    known = known_scalar_keys(section)
    for name, value in data.items():
        if name not in known:
            ignored.append(name)
            continue
        if name in PLACEHOLDER_ONLY_FIELDS and looks_like_plaintext_secret(value):
            raise PlaintextSecretRejected(f"{name} 含明文密钥，只允许写 ${{VAR}} 占位")
        patches[_scalar_key(section, name)] = _format_value(value)
    return patches, ignored, deletes


def _apply_patches(text: str, patches: dict[str, str], deletes: set[str]) -> str:
    """按行改写 .env：已存在的键就地替换，新键追加到所属段末尾。"""
    lines = text.splitlines()
    missing = set(patches)
    out: list[str] = []
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            out.append(line)
            continue
        key = stripped.split("=", 1)[0].strip()
        if key in deletes:
            continue
        if key in patches:
            out.append(f"{key}={patches[key]}")
            missing.discard(key)
        else:
            out.append(line)

    for key in sorted(missing):
        insert_at = _section_end(out, _section_of_env_key(key))
        out.insert(insert_at, f"{key}={patches[key]}")
    return "\n".join(out) + "\n"


def _section_of_env_key(key: str) -> str:
    """由 .env 键名反推段名（用于把新键插到正确的段里）。

    注意顺序：basic 的 token 是空串，必须放在最后兜底，否则会吞掉所有 FLEET_* 键。
    """
    for section, (token, _) in LIST_LAYOUT.items():
        if key.startswith(f"FLEET_{token}_"):
            return section
    for section, token in SECTION_TOKEN.items():
        if token and key.startswith(f"FLEET_{token}"):
            return section
    return "basic"


def _section_end(lines: list[str], section: str) -> int:
    """返回该段最后一行之后的位置（下一个段标题之前）。"""
    start = len(lines)
    for index, line in enumerate(lines):
        marker = _SECTION_RE.match(line)
        if marker and marker.group(1).strip().lower() == section:
            start = index + 1
            break
    end = len(lines)
    for index in range(start, len(lines)):
        if _SECTION_RE.match(lines[index]):
            end = index
            break
    while end > start and not lines[end - 1].strip():
        end -= 1
    return end


def save(section: str, data: dict[str, Any]) -> dict[str, Any]:
    """写回某段：原子写（临时文件 + os.replace），返回 {applied, ignored, mtime}。

    只有控制台进程允许写；引擎侧抛 ConfigWriteDenied（工作包 §9.2-5）。
    """
    section = str(section or "").strip().lower()
    if section not in SECTIONS:
        raise UnknownSection(f"未知配置段：{section}；合法段：{', '.join(SECTIONS)}")
    if not write_enabled():
        raise ConfigWriteDenied("当前进程为只读（引擎侧）；只有控制台进程允许写配置")
    if not isinstance(data, dict):
        raise ConfigError("配置写入体必须是 JSON 对象")

    env_file = ensure_env_file()
    patches, ignored, deletes = _build_patches(section, data)
    new_text = _apply_patches(env_file.read_text(encoding="utf-8"), patches, deletes)

    tmp = env_file.parent / f".{env_file.name}.tmp"
    tmp.write_text(new_text, encoding="utf-8")
    os.replace(tmp, env_file)

    _CACHE.mtime_ns = None  # 强制下次 load 重新解析
    applied: Any = data.get(_list_key(section)) if section in LIST_SECTIONS else {
        name: value for name, value in data.items() if name not in ignored
    }
    return {"applied": applied, "ignored": ignored, "mtime": env_mtime()}

