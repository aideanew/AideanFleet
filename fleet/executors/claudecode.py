"""Claude Code执行体适配器"""

import subprocess
import json
from pathlib import Path
from typing import Optional

from .base import BaseAdapter, AgentResult, ErrorCode, Capabilities, register_adapter, save_evidence, detect_error, run_subprocess_tree_safe, pool_entry_for, resolve_cli, extract_session_id


@register_adapter
class ClaudeCodeAdapter(BaseAdapter):
    """Claude Code适配器"""

    name = "claudecode"

    def capabilities(self) -> Capabilities:
        """探测Claude Code能力"""
        try:
            result = subprocess.run(
                [resolve_cli("claude"), "--help"],
                capture_output=True,
                text=True,
                timeout=10,
                creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0,
            )
            help_text = result.stdout + result.stderr

            return Capabilities(
                streaming="--stream" in help_text,
                structured_output="--output-format" in help_text,
                mcp=True,
                native_skills=True,
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
        """执行Claude Code任务"""
        # 模型池条目是 OpenAI 兼容协议，claude CLI（Anthropic 协议）无法直连；
        # 统一降级为 claude 原生凭据默认模型（--model 传任意非 Anthropic 模型名会挂起超时）。
        cli = resolve_cli("claude")
        # prompt 走 stdin（-p 无位置参数时从 stdin 读）：多行派工提示词经 argv/cmd shim 会被截断
        cmd = [cli, "-p", "--output-format", "json"]

        try:
            creationflags = subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0
            p = run_subprocess_tree_safe(
                cmd,
                cwd=workdir,
                timeout=timeout,
                creationflags=creationflags,
                input_text=prompt,
            )

            # 保存证据
            evidence_content = f"=== STDOUT ===\n{p.stdout}\n\n=== STDERR ===\n{p.stderr}"
            save_evidence("claudecode", 1, evidence_content)
            # session_id：claude -p --output-format json 的结果对象自带 session_id 字段
            session_id = extract_session_id(p.stdout)

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
            try:
                data = json.loads(p.stdout)
                return AgentResult(
                    ok=True,
                    output=data.get("result", p.stdout),
                    session_id=(data.get("session_id") if isinstance(data, dict) else None) or session_id,
                )
            except json.JSONDecodeError:
                return AgentResult(ok=True, output=p.stdout, session_id=session_id)

        except subprocess.TimeoutExpired as e:
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
                error_msg="Claude Code未安装",
            )
        except Exception as e:
            return AgentResult(
                ok=False,
                output="",
                error_code=ErrorCode.TOOL_FAIL,
                error_msg=str(e)[-2000:],
            )


# 别名：resolve() 需要模块级 Adapter 属性
Adapter = ClaudeCodeAdapter
