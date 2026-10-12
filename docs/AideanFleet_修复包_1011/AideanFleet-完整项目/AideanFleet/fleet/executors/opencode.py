"""OpenCode执行体适配器"""

import json
import os
import subprocess
from pathlib import Path
from typing import Any
from typing import Optional

from .base import BaseAdapter, AgentResult, ErrorCode, Capabilities, register_adapter, save_evidence, current_task_id, detect_error, run_subprocess_tree_safe, pool_entry_for, resolve_cli, extract_session_id


def parse_opencode_json_output(stdout: str) -> tuple[str, dict[str, Any] | None]:
    """解析 `opencode run --format json` 输出：拼接 text part，提取最后一个 step_finish 的 tokens。

    非 JSON / 缺 tokens 时降级为 (原样输出, None)，绝不因格式变化丢输出。
    """
    text_chunks: list[str] = []
    tokens: dict[str, Any] | None = None
    for line in (stdout or "").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            # 混入非 JSON 行（告警等）：无法拼接时整体降级为原文
            if not text_chunks:
                return stdout, None
            continue
        part = event.get("part") or {}
        if event.get("type") == "text" and isinstance(part.get("text"), str):
            text_chunks.append(part["text"])
        elif event.get("type") == "step_finish" and isinstance(part.get("tokens"), dict):
            tokens = part["tokens"]
    if not text_chunks:
        return stdout, None
    usage: dict[str, Any] | None = None
    if tokens:
        usage = {
            "prompt_tokens": int(tokens.get("input") or 0),
            "completion_tokens": int(tokens.get("output") or 0),
            "reasoning_tokens": int(tokens.get("reasoning") or 0),
            "total_tokens": int(tokens.get("total") or 0),
        }
    return "\n".join(text_chunks), usage


@register_adapter
class OpenCodeAdapter(BaseAdapter):
    """OpenCode适配器"""

    name = "opencode"

    def capabilities(self) -> Capabilities:
        """探测OpenCode能力"""
        try:
            result = subprocess.run(
                [resolve_cli("opencode"), "--help"],
                capture_output=True,
                text=True,
                timeout=10,
                creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0,
            )
            help_text = result.stdout + result.stderr

            return Capabilities(
                streaming=False,
                structured_output=False,
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
        """执行OpenCode任务"""
        # 假执行防线：空 prompt 或只剩派工标记（多行正文经 cmd shim 截断的残骸）时，
        # 直接判 unavailable，绝不空耗重试预算——真实任务必含正文。
        stripped = (prompt or "").strip()
        if not stripped or stripped.replace("[MANAGER REWORK DISPATCH]", "").strip() == "":
            return AgentResult(
                ok=False,
                output="",
                error_code=ErrorCode.UNAVAILABLE,
                error_msg="opencode prompt 为空或仅含派工标记（疑似 cmd shim 截断），拒绝假执行",
            )
        workspace = Path(workdir).expanduser()
        if not workdir or not workspace.is_absolute() or not workspace.is_dir():
            return AgentResult(ok=False, error_code=ErrorCode.UNAVAILABLE,
                               error_msg="OpenCode 工作区必须是已存在的绝对目录，拒绝回退到控制面目录")
        directory = workspace.resolve().as_posix()
        # cwd 不能替代 CLI 会话目录；继承的 PWD/INIT_CWD 也必须与目标一致。
        env = {**os.environ, "PWD": directory, "INIT_CWD": directory}
        env["OPENCODE_PERMISSION"] = json.dumps({"external_directory": "deny"})
        # 池模型由 OpenCode 自身默认 provider 执行，不传不兼容的池模型 ID。
        cli = resolve_cli("opencode")
        cmd = [cli, "run", "--format", "json", "--dir", directory]
        if model and pool_entry_for(model) is None:
            cmd.extend(["--model", model])

        try:
            creationflags = subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0
            p = run_subprocess_tree_safe(
                cmd,
                cwd=directory,
                timeout=timeout,
                creationflags=creationflags,
                env=env,
                input_text=prompt,
            )

            # 保存证据（按 task_id 落盘，从 registry 上下文取；无上下文回落适配器名）
            evidence_content = f"=== STDOUT ===\n{p.stdout}\n\n=== STDERR ===\n{p.stderr}"
            save_evidence(current_task_id() or "opencode", 1, evidence_content)

            if p.returncode != 0:
                error_code = detect_error(p.stderr, p.stdout)
                return AgentResult(
                    ok=False,
                    output="",
                    error_code=error_code,
                    error_msg=(p.stderr or p.stdout)[-2000:],
                )

            output, usage = parse_opencode_json_output(p.stdout or "")
            return AgentResult(
                ok=True,
                output=output,
                usage=usage,
                session_id=extract_session_id(p.stdout),
            )

        except subprocess.TimeoutExpired as e:
            # 超时也要落证据：此前超时静默失败导致"无证据空转 8 次"难以定位
            save_evidence(current_task_id() or "opencode", 1, f"=== TIMEOUT after {timeout}s ===\n{str(e)[-1000:]}")
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
                error_msg="OpenCode未安装",
            )
        except Exception as e:
            return AgentResult(
                ok=False,
                output="",
                error_code=ErrorCode.TOOL_FAIL,
                error_msg=str(e)[-2000:],
            )


# 别名：resolve() 需要模块级 Adapter 属性
Adapter = OpenCodeAdapter
