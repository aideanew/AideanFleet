"""这是什么：Harness 执行器（P3）：按 profile 组命令 → 流式收输出 → 解析成统一事件 → TurnResult。
怎么用：
    outcome = run_profile(profile, packet_prompt, workspace, model="", renew=callable)
    outcome.ok / outcome.output / outcome.session_id / outcome.tokens_in|out / outcome.exit_code
要点：
- C1/C4 修复：命令一律先 resolve_cli()（Windows .cmd shim）；流式读行并每行回调 renew（续约）；
- 空闲超时：timeout_idle_s 内无新输出判卡死 → kill_tree → ok=False(TIMEOUT)；
- 模型池桥接：仅 model_protocol=openai 的 profile 接受池模型（注入 OPENAI_BASE_URL/OPENAI_API_KEY）；
  anthropic 协议（claude）忽略模型参数，用宿主自身凭据（C3 修复口径）；
- prompt_via=stdin：prompt 全文走 stdin（规避 Windows 命令行长度限制）。
"""

from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from ..executors.base import kill_tree, resolve_cli
from .parsers import HarnessEvent, get_parser
from .profile import HarnessProfile

_ERROR_HINTS = ("not found", "not logged in", "unauthorized", "enoent", "no such file")


@dataclass
class HarnessOutcome:
    ok: bool
    output: str = ""
    error_code: str | None = None
    error_msg: str = ""
    exit_code: int | None = None
    session_id: str = ""
    tokens_in: int = 0
    tokens_out: int = 0
    events: list[HarnessEvent] = field(default_factory=list)

    def to_turn_kwargs(self) -> dict[str, Any]:
        return {
            "exit_code": self.exit_code,
            "tokens_in": self.tokens_in,
            "tokens_out": self.tokens_out,
            "session_id": self.session_id,
        }


def _build_command(profile: HarnessProfile, model: str, resume_session: str = "") -> list[str]:
    cmd = [resolve_cli(profile.invoke[0])] + list(profile.invoke[1:])
    if resume_session and profile.session_resume:
        cmd += [part.replace("{session_id}", resume_session) for part in profile.session_resume]
    # 模型传递：仅 openai 协议吃模型池；model 为宿主别名（空 = 默认模型）
    if model and profile.model_flag and profile.model_protocol == "openai":
        cmd += [profile.model_flag, model]
    return cmd


def _bridge_env(profile: HarnessProfile, model: str) -> dict[str, str]:
    """模型池桥接环境（仅 openai 协议）：从模型池取 base_url/key 注入子进程。"""
    if profile.model_protocol != "openai" or not model:
        return {}
    try:
        from fleet.executors.codex import pool_bridge_env

        return dict(pool_bridge_env(model))
    except Exception:
        return {}


def run_profile(
    profile: HarnessProfile,
    prompt: str,
    workspace: str,
    *,
    model: str = "",
    resume_session: str = "",
    on_chunk: Callable[[str], None] | None = None,
    renew: Callable[[], None] | None = None,
    hard_timeout_s: int = 3600,
) -> HarnessOutcome:
    """跑一次 harness 调用；流式解析输出，每收到一行就 renew()（租约续期心跳）。"""
    cmd = _build_command(profile, model, resume_session)
    outcome = HarnessOutcome(ok=False)
    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    env.update(_bridge_env(profile, model))
    creationflags = subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0
    try:
        proc = subprocess.Popen(
            cmd,
            cwd=workspace or None,
            env=env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=creationflags,
        )
    except FileNotFoundError as exc:
        outcome.error_code, outcome.error_msg = "HARNESS_MISSING", str(exc)
        return outcome
    except OSError as exc:
        outcome.error_code, outcome.error_msg = "HARNESS_SPAWN_FAIL", str(exc)
        return outcome

    parser = get_parser(profile.output_parser)
    started = time.monotonic()

    def _feed_stdin() -> None:
        try:
            if proc.stdin:
                proc.stdin.write(prompt)
                proc.stdin.close()
        except Exception:
            pass

    threading.Thread(target=_feed_stdin, daemon=True).start()

    def _pump() -> None:
        assert proc.stdout is not None
        for raw_line in iter(proc.stdout.readline, ""):
            if renew is not None:
                try:
                    renew()
                except Exception:
                    pass
            outcome.events.extend(parser(iter([raw_line])))
            for event in outcome.events[-4:]:
                if event.type == "text" and on_chunk is not None:
                    try:
                        on_chunk(event.text)
                    except Exception:
                        pass
        proc.stdout.close()

    pump_thread = threading.Thread(target=_pump, daemon=True)
    pump_thread.start()

    idle_last = time.monotonic()
    while proc.poll() is None:
        time.sleep(0.2)
        if renew is not None and time.monotonic() - idle_last >= 5.0:
            idle_last = time.monotonic()
            try:
                renew()
            except Exception:
                pass
        if time.monotonic() - started > hard_timeout_s:
            kill_tree(proc.pid)
            outcome.error_code, outcome.error_msg = "TIMEOUT", f"hard timeout {hard_timeout_s}s"
            break
    pump_thread.join(timeout=5)
    outcome.exit_code = proc.poll()

    texts = [e.text for e in outcome.events if e.type in ("text", "result") and e.text]
    raws = [e.text for e in outcome.events if e.type == "raw" and e.text]
    outcome.output = "\n".join(texts or raws).strip()
    for event in outcome.events:
        if event.type == "session" and event.text:
            outcome.session_id = event.text
        if event.type == "usage":
            outcome.tokens_in = int(event.data.get("tokens_in") or 0)
            outcome.tokens_out = int(event.data.get("tokens_out") or 0)
    if outcome.exit_code == 0:
        outcome.ok = True
    else:
        outcome.error_code = outcome.error_code or f"EXIT_{outcome.exit_code}"
        joined = (outcome.output or "").lower()
        if any(hint in joined for hint in _ERROR_HINTS):
            outcome.error_code = outcome.error_code or "HARNESS_ERROR"
        outcome.error_msg = outcome.error_msg or outcome.output[-500:]
    return outcome


def detect(profile: HarnessProfile) -> tuple[bool, str]:
    """C5 修复：真实探测已安装（detect 命令退出码 0 = 已安装）。"""
    if not profile.detect:
        return True, "no detect command"
    cmd = [resolve_cli(profile.detect[0])] + list(profile.detect[1:])
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=30,
            encoding="utf-8", errors="replace",
            creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0,
        )
        if proc.returncode == 0:
            return True, (proc.stdout or "").strip().splitlines()[0] if proc.stdout.strip() else "ok"
        return False, f"exit {proc.returncode}: {(proc.stderr or proc.stdout or '').strip()[:200]}"
    except FileNotFoundError:
        return False, f"未安装: {profile.detect[0]}"
    except subprocess.TimeoutExpired:
        return False, f"detect 超时（30s）: {' '.join(cmd)}"


def auth_check(profile: HarnessProfile) -> tuple[bool, str]:
    """C5 修复：探测已登录/可用（auth_check 退出码 0 = 可用）。"""
    if not profile.auth_check:
        return True, "no auth_check command"
    cmd = [resolve_cli(profile.auth_check[0])] + list(profile.auth_check[1:])
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=60,
            encoding="utf-8", errors="replace",
            creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0,
        )
        if proc.returncode == 0:
            return True, "ok"
        return False, f"exit {proc.returncode}: {(proc.stderr or proc.stdout or '').strip()[:200]}"
    except FileNotFoundError:
        return False, f"未安装: {profile.auth_check[0]}"
    except subprocess.TimeoutExpired:
        return False, f"auth_check 超时（60s）: {' '.join(cmd)}"
