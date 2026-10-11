"""这是什么：Harness Profile（P3：声明式 YAML 取代手写适配器，对标 LoopX harness）。
怎么用：
    profile = load_profile("claude")           # 读 fleet/harness/profiles/claude.yaml
    profile.invoke                             # ["claude", "-p", "--output-format", "stream-json", ...]
字段语义：
    name           profile 名（与文件名一致）
    detect         探测安装：无异常退出即视为已安装
    auth_check     探测已登录/可用：退出码 0 视为可用（C5：探测不到登录态的旧 capabilities() 已废）
    invoke         无头调用命令骨架（prompt 经 stdin 注入或 {prompt} 占位）
    prompt_via     stdin | arg
    model_protocol anthropic | openai | none —— 只有 openai 协议的 harness 吃模型池（注入 OPENAI_BASE_URL/KEY）
    model_flag     模型参数名（如 -m）；空 = 不传模型
    output_parser  claude_stream_json | codex_jsonl | opencode_json | plain
    session_resume 断点续跑骨架，{session_id} 占位；空 = 不支持
    timeout_idle_s 流式空闲超时（秒）：超过即判卡死
角色 → 执行体链见 fleet.toml [roles.*] harness=[...]；不可用自动降级（fleet doctor 标红原因）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from . import yaml_min

PROFILES_DIR = Path(__file__).resolve().parent / "profiles"

KNOWN_FIELDS = {
    "name", "detect", "auth_check", "invoke", "prompt_via", "model_protocol",
    "model_flag", "output_parser", "session_resume", "timeout_idle_s",
}


@dataclass(frozen=True)
class HarnessProfile:
    name: str
    detect: list[str] = field(default_factory=list)
    auth_check: list[str] = field(default_factory=list)
    invoke: list[str] = field(default_factory=list)
    prompt_via: str = "stdin"
    model_protocol: str = "none"
    model_flag: str = ""
    output_parser: str = "plain"
    session_resume: list[str] = field(default_factory=list)
    timeout_idle_s: int = 180


def load_profile(name: str, profiles_dir: str | Path | None = None) -> HarnessProfile:
    """按名加载 profile；名字只允许 [a-z0-9_-]，防路径穿越。"""
    safe = "".join(ch for ch in name.lower() if ch in "abcdefghijklmnopqrstuvwxyz0123456789_-")
    if safe != name or not safe:
        raise ValueError(f"非法 profile 名: {name!r}")
    base = Path(profiles_dir) if profiles_dir else PROFILES_DIR
    path = base / f"{safe}.yaml"
    if not path.is_file():
        raise FileNotFoundError(f"profile 不存在: {path}")
    data = yaml_min.parse(path.read_text(encoding="utf-8"))
    unknown = set(data) - KNOWN_FIELDS
    if unknown:
        raise ValueError(f"profile {name} 含未知字段: {sorted(unknown)}")
    if data.get("name") != name:
        raise ValueError(f"profile {name} 的 name 字段与文件名不一致: {data.get('name')!r}")
    invoke = list(data.get("invoke") or [])
    if not invoke:
        raise ValueError(f"profile {name} 缺 invoke 命令骨架")
    for key in ("detect", "auth_check", "invoke", "session_resume"):
        if key in data and not isinstance(data.get(key), list):
            raise ValueError(f"profile {name} 的 {key} 必须是列表")
    return HarnessProfile(
        name=name,
        detect=[str(x) for x in data.get("detect") or []],
        auth_check=[str(x) for x in data.get("auth_check") or []],
        invoke=invoke,
        prompt_via=str(data.get("prompt_via") or "stdin"),
        model_protocol=str(data.get("model_protocol") or "none"),
        model_flag=str(data.get("model_flag") or ""),
        output_parser=str(data.get("output_parser") or "plain"),
        session_resume=[str(x) for x in data.get("session_resume") or []],
        timeout_idle_s=int(data.get("timeout_idle_s") or 180),
    )


def available_profiles(profiles_dir: str | Path | None = None) -> list[str]:
    base = Path(profiles_dir) if profiles_dir else PROFILES_DIR
    if not base.is_dir():
        return []
    return sorted(p.stem for p in base.glob("*.yaml"))
