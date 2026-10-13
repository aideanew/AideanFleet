"""这是什么：模型直写执行路径（P4）：执行体链（CLI harness）全不可用时的回退。
注入的 planner 客户端直接对话模型，模型按 JSON ops 协议回复文件改动，本模块校验后落盘。
怎么用（由 worker.run_once 内部接线，外部不直接调用）：
    outcome = run_model_write(prompt, workspace, client,
                              allowed_files=["src/**"], renew=callable)
    outcome.ok / .output / .error_code / .error_msg / .to_turn_kwargs()  # 与 HarnessOutcome 同形
协议（由本模块追加在 packet 提示词之后，不污染 harness 路径）：
    {"ops": [{"op": "write", "path": "<workspace 相对路径>", "content": "<完整文件全文>"}],
     "report": "<改动摘要/模型自述>"}
要点：
- JSON 提取复用 planner.extract_json（容忍围栏与前后闲话）；协议不符 → MODEL_PROTOCOL；
- 边界三重校验，任一违规整批拒绝（原子，不写半套）→ MODEL_OUT_OF_SCOPE：
  ① 路径必须相对、无 ..，resolve 后必须落在 workspace 内（symlink 逃逸一并拦截）；
  ② 必须命中 allowed_files 模式（fnmatch 语义；未配置 = 一律拒绝，安全默认）；
  ③ 目标本身是 symlink 时拒写（不穿透软链）；
- 模型调用是单次阻塞调用（无流式心跳）：前后各续约一次，lease_seconds 需覆盖最长单次调用。
"""

from __future__ import annotations

from dataclasses import dataclass
from fnmatch import fnmatch
from pathlib import Path, PurePosixPath
from typing import Any, Callable

PROTOCOL_BLOCK = """
## 写回协议（必须严格遵守）
你不接任何文件系统 CLI；只按以下 JSON 格式回复全部改动（一个 JSON 对象，可包 ```json 围栏）：
{"ops": [{"op": "write", "path": "<workspace 相对路径>", "content": "<完整文件全文>"}],
 "report": "<改动摘要：改了什么/为什么/自查>"}
规则：只支持 op="write"；path 必须是 workspace 相对路径（禁止绝对路径与 .. 越界）；
必须命中「允许改动的文件」模式；content 必须是完整文件内容（非 diff 片段）；
越界或不允许的改动一个都不要写——任何违规将导致整批拒绝。
"""


@dataclass
class ModelWriteOutcome:
    """模型直写一轮的结果；字段与 harness.runner.HarnessOutcome 同形（worker 共用 gate/写回尾段）。"""

    ok: bool
    output: str = ""
    error_code: str | None = None
    error_msg: str = ""
    exit_code: int | None = None
    session_id: str = ""
    tokens_in: int = 0
    tokens_out: int = 0

    def to_turn_kwargs(self) -> dict[str, Any]:
        return {
            "exit_code": self.exit_code,
            "tokens_in": self.tokens_in,
            "tokens_out": self.tokens_out,
            "session_id": self.session_id,
        }


def _protocol_error(reply: str, msg: str) -> ModelWriteOutcome:
    return ModelWriteOutcome(ok=False, output=reply, error_code="MODEL_PROTOCOL", error_msg=msg)


def _scope_error(reply: str, msg: str) -> ModelWriteOutcome:
    return ModelWriteOutcome(ok=False, output=reply, error_code="MODEL_OUT_OF_SCOPE", error_msg=msg)


def _normalize_rel(path: str) -> str:
    """归一化模型给的路径：反斜杠→/；返回 posix 相对路径；非法（绝对/../盘符）抛 ValueError。"""
    raw = (path or "").strip().replace("\\", "/")
    if not raw:
        raise ValueError("path 为空")
    head = raw.split("/", 1)[0]
    if raw.startswith("/") or PurePosixPath(raw).is_absolute() or ":" in head:
        raise ValueError(f"禁止绝对路径: {path!r}")
    parts = [p for p in raw.split("/") if p not in ("", ".")]
    if any(p == ".." for p in parts):
        raise ValueError(f"禁止 .. 越界: {path!r}")
    return "/".join(parts)


def _allowed(rel: str, allowed_files: list[str] | None) -> bool:
    """是否命中 allowed_files（fnmatch 语义，`**`/`src/**` 均可）；未配置 = 一律拒绝（安全默认）。"""
    patterns = [p for p in (allowed_files or []) if p]
    if not patterns:
        return False
    return any(fnmatch(rel, p) for p in patterns)


def _parse_ops(reply: str) -> list[dict]:
    """解析模型回复 → ops 列表。协议不符抛 ValueError（统一映射 MODEL_PROTOCOL）。"""
    from ..planner import extract_json

    try:
        data = extract_json(reply)
    except ValueError as exc:  # PlanValidationError / JSONDecodeError 均为 ValueError 子类
        raise ValueError(f"回复中无合法 JSON：{exc}") from exc
    if not isinstance(data, dict):
        raise ValueError("JSON 必须是对象")
    ops = data.get("ops")
    if not isinstance(ops, list) or not ops:
        raise ValueError("ops 必须是非空数组")
    for i, op in enumerate(ops):
        if not isinstance(op, dict) or op.get("op") != "write":
            got = op.get("op") if isinstance(op, dict) else type(op).__name__
            raise ValueError(f'ops[{i}] 只支持 op="write"，收到 {got!r}')
        if not isinstance(op.get("path"), str) or not isinstance(op.get("content"), str):
            raise ValueError(f"ops[{i}] 的 path/content 必须是字符串")
    return ops


def run_model_write(
    prompt: str,
    workspace: str,
    client: Callable[[str], str],
    *,
    allowed_files: list[str] | None = None,
    renew: Callable[[], None] | None = None,
) -> ModelWriteOutcome:
    """跑一轮模型直写：提示词+协议 → 模型回复 → 解析 → 三重边界校验 → 原子落盘。"""
    if renew is not None:
        renew()
    try:
        reply = client(prompt + PROTOCOL_BLOCK)
    except Exception as exc:  # 客户端异常不外溢：转 MODEL_PROTOCOL，blocked 可观测
        return _protocol_error("", f"模型客户端调用失败：{exc}")
    if renew is not None:
        renew()

    try:
        ops = _parse_ops(reply)
    except ValueError as exc:
        return _protocol_error(reply, str(exc))

    ws = Path(workspace).resolve()
    plan: list[tuple[Path, str]] = []
    for i, op in enumerate(ops):
        try:
            rel = _normalize_rel(op["path"])
        except ValueError as exc:
            return _scope_error(reply, f"ops[{i}] {exc}")
        if not _allowed(rel, allowed_files):
            return _scope_error(reply, f"ops[{i}] 未命中 allowed_files：{rel}")
        joined = ws / rel
        if joined.is_symlink():  # 必须在 resolve 之前判定：resolve 会解引用软链
            return _scope_error(reply, f"ops[{i}] 目标是 symlink，拒写：{op['path']!r}")
        target = joined.resolve()
        if not target.is_relative_to(ws):
            return _scope_error(reply, f"ops[{i}] 解析后越出 workspace：{op['path']!r}")
        plan.append((target, op["content"]))

    for target, content in plan:  # 全部校验通过才落盘（原子：不写半套）
        target.parent.mkdir(parents=True, exist_ok=True)
        with open(target, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(content)
    return ModelWriteOutcome(ok=True, output=reply, exit_code=0)
