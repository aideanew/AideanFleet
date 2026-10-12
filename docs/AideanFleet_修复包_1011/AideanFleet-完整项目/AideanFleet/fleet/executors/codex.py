"""Codex CLI执行体适配器"""

import os
import subprocess
import json
from pathlib import Path
from typing import Optional

from .base import BaseAdapter, AgentResult, ErrorCode, Capabilities, register_adapter, save_evidence, current_task_id, detect_error, run_subprocess_tree_safe, pool_entry_for, resolve_cli, extract_session_id


def _parse_codex_usage(stdout: str) -> dict[str, int] | None:
    """从 codex --json JSONL 输出里提取 token 用量。

    codex 的 turn.completed 事件携带 usage 字段：
    {"type":"turn.completed","usage":{"input_tokens":N,"output_tokens":N,"reasoning_output_tokens":N}}
    取最后一条 turn.completed（多轮对话里最后一次才是完整汇总）。
    """
    usage: dict[str, int] | None = None
    for line in (stdout or "").splitlines():
        line = line.strip()
        if not line or "turn.completed" not in line:
            continue
        try:
            event = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            continue
        if not isinstance(event, dict):
            continue
        raw = event.get("usage")
        if not isinstance(raw, dict):
            continue
        prompt = int(raw.get("input_tokens") or 0)
        completion = int(raw.get("output_tokens") or 0)
        reasoning = int(raw.get("reasoning_output_tokens") or 0)
        usage = {
            "prompt_tokens": prompt,
            "completion_tokens": completion,
            "reasoning_tokens": reasoning,
            "total_tokens": prompt + completion + reasoning,
        }
    return usage


def pool_bridge_env(model_id: str) -> dict | None:
    """模型池 -> CLI 子进程环境桥接。

    按 model_id 反查模型池条目；命中且有 base_url + 可用 key 时，
    注入 OPENAI_BASE_URL / OPENAI_API_KEY（OpenAI 兼容端点统一桥接）。
    未命中/未配置返回 None（子进程继承父环境，用 CLI 自带凭据）。
    """
    entry = pool_entry_for(model_id)
    if entry is None:
        return None
    from fleet.models import pool as pool_mod

    key = pool_mod.resolve_key(entry)
    if entry.base_url and key:
        env = dict(os.environ)
        env["OPENAI_BASE_URL"] = entry.base_url
        env["OPENAI_API_KEY"] = key
        return env
    return None


@register_adapter
class CodexAdapter(BaseAdapter):
    """Codex CLI适配器"""

    name = "codex"

    def capabilities(self) -> Capabilities:
        """探测Codex能力"""
        try:
            result = subprocess.run(
                [resolve_cli("codex"), "--help"],
                capture_output=True,
                text=True,
                timeout=10,
                creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0,
            )
            help_text = result.stdout + result.stderr

            return Capabilities(
                streaming=False,
                structured_output="--json" in help_text,
                mcp=False,
                native_skills=False,
                sandbox=False,
                usage_reporting=True,
            )
        except Exception:
            return Capabilities()

    def run(
        self,
        prompt: str,
        workdir: str,
        model: str,
        timeout: int = 600,
    ) -> AgentResult:
        """执行Codex任务"""
        bridge = pool_bridge_env(model)
        cli = resolve_cli("codex")
        # -s workspace-write：允许执行体在工作区写入文件（默认只读沙箱会导致"回执成功但零产出"）；
        # prompt 走 stdin：多行派工提示词经 argv/cmd shim 会被截断到首行（实测模型只收到 system_prompt）。
        cmd = [cli, "exec", "--json", "--skip-git-repo-check", "-s", "workspace-write", "-m", model]

        try:
            creationflags = subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0
            p = run_subprocess_tree_safe(
                cmd,
                cwd=workdir,
                timeout=timeout,
                creationflags=creationflags,
                env=bridge,
                input_text=prompt,
            )

            # 保存证据（按 task_id 落盘，从 registry 上下文取；无上下文回落适配器名）
            evidence_content = f"=== STDOUT ===\n{p.stdout}\n\n=== STDERR ===\n{p.stderr}"
            save_evidence(current_task_id() or "codex", 1, evidence_content)
            # session_id：codex --json 输出 JSONL 事件流（thread.started 等行携带会话 id）
            session_id = extract_session_id(p.stdout) or extract_session_id(p.stderr)

            if p.returncode != 0:
                error_code = detect_error(p.stderr, p.stdout)
                return AgentResult(
                    ok=False,
                    output="",
                    error_code=error_code,
                    error_msg=(p.stderr or p.stdout)[-2000:],
                    session_id=session_id,
                )

            # 尝试解析JSON输出
            parsed_usage = _parse_codex_usage(p.stdout)
            try:
                data = json.loads(p.stdout)
                return AgentResult(ok=True, output=data.get("output", p.stdout), session_id=session_id, usage=parsed_usage)
            except json.JSONDecodeError:
                return AgentResult(ok=True, output=p.stdout, session_id=session_id, usage=parsed_usage)

        except subprocess.TimeoutExpired as e:
            # 超时也要落证据（与 opencode.py:144 对齐）：此前超时静默导致"无证据空转"不可定位
            save_evidence(current_task_id() or "codex", 1, f"=== TIMEOUT after {timeout}s ===\n{str(e)[-1000:]}")
            return AgentResult(
                ok=False,
                output="",
                error_code=ErrorCode.TIMEOUT,
                error_msg=str(e)[-2000:],
            )
        except FileNotFoundError:
            return AgentResult(
                ok=False,
                output="",
                error_code=ErrorCode.UNAVAILABLE,
                error_msg="Codex CLI未安装",
            )
        except Exception as e:
            # 取证：异常路径此前不落 evidence，导致连败根因不可见（实测教训）
            try:
                save_evidence(current_task_id() or "codex", 1, f"=== EXCEPTION ===\n{type(e).__name__}: {e}")
            except Exception:
                pass
            return AgentResult(
                ok=False,
                output="",
                error_code=ErrorCode.TOOL_FAIL,
                error_msg=str(e)[-2000:],
            )


# 别名：resolve() 需要模块级 Adapter 属性
Adapter = CodexAdapter
