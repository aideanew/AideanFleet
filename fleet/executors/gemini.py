"""Gemini执行体适配器"""

import json
import subprocess
from pathlib import Path
from typing import Optional

from .base import BaseAdapter, AgentResult, ErrorCode, Capabilities, register_adapter, save_evidence, current_task_id, detect_error, run_subprocess_tree_safe, pool_entry_for, resolve_cli, extract_session_id


def _parse_gemini_json(stdout: str) -> tuple[str, dict | None]:
    """解析 gemini -p 的 JSON 输出。

    结构示例：
    {"generation": "使用说明……", "tokenCount": {"inputTokenCount": 123, "outputTokenCount": 45}, "metadata": {...}}
    取 generation（主答复）与 tokenCount（用量）；缺省/非 JSON 时降级为原样输出。
    """
    if not (stdout or "").strip():
        return stdout or "", None
    try:
        data = json.loads(stdout)
    except json.JSONDecodeError:
        return stdout, None
    if not isinstance(data, dict):
        return stdout, None

    usage: dict | None = None
    tokens = data.get("tokenCount")
    if isinstance(tokens, dict):
        try:
            inp = int(tokens.get("inputTokenCount") or 0)
            out = int(tokens.get("outputTokenCount") or 0)
            usage = {
                "prompt_tokens": inp,
                "completion_tokens": out,
                "reasoning_tokens": 0,
                "total_tokens": inp + out,
            }
        except (TypeError, ValueError):
            usage = None

    text = data.get("generation") or data.get("text")
    if isinstance(text, str) and text.strip():
        return text, usage
    return stdout, usage


@register_adapter
class GeminiAdapter(BaseAdapter):
    """Gemini CLI执行体适配器"""

    name = "gemini"

    def capabilities(self) -> Capabilities:
        """探测Gemini能力"""
        try:
            result = subprocess.run(
                [resolve_cli("gemini"), "--version"],
                capture_output=True,
                text=True,
                timeout=10,
                creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0,
            )
            available = result.returncode == 0

            return Capabilities(
                streaming=False,
                structured_output=available,  # --output-format json 支持
                mcp=False,
                native_skills=False,
                sandbox=False,
                usage_reporting=True,  # tokenCount 字段
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
        """执行Gemini任务"""
        # 假执行防线：空 prompt 或只剩派工标记时直接判 unavailable，绝不空耗重试预算
        stripped = (prompt or "").strip()
        if not stripped or stripped.replace("[MANAGER REWORK DISPATCH]", "").strip() == "":
            return AgentResult(
                ok=False,
                output="",
                error_code=ErrorCode.UNAVAILABLE,
                error_msg="gemini prompt 为空或仅含派工标记（疑似 cmd shim 截断），拒绝假执行",
            )
        workspace = Path(workdir).expanduser()
        if not workdir or not workspace.is_absolute() or not workspace.is_dir():
            return AgentResult(ok=False, error_code=ErrorCode.UNAVAILABLE,
                               error_msg="Gemini 工作区必须是已存在的绝对目录，拒绝回退到控制面目录")
        directory = workspace.resolve().as_posix()

        cli = resolve_cli("gemini")
        # -p 走 stdin（无位置参数时从 stdin 读取）；--approval-mode=yolo 无人值守；
        # --output-format json 结构化输出。多行派工提示词经 argv/cmd shim 会被截断，必须走 stdin。
        cmd = [cli, "-p", "--approval-mode=yolo", "--output-format", "json"]
        # 池模型（OpenAI 兼容端点）gemini CLI 无法直连，降级为 gemini 默认凭据；非池模型才显式传。
        if model and pool_entry_for(model) is None:
            cmd.extend(["--model", model])

        try:
            creationflags = subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0
            p = run_subprocess_tree_safe(
                cmd,
                cwd=directory,
                timeout=timeout,
                creationflags=creationflags,
                input_text=prompt,
            )

            # 保存证据（按 task_id 落盘，从 registry 上下文取；无上下文回落适配器名）
            evidence_content = f"=== STDOUT ===\n{p.stdout}\n\n=== STDERR ===\n{p.stderr}"
            save_evidence(current_task_id() or "gemini", 1, evidence_content)

            if p.returncode != 0:
                error_code = detect_error(p.stderr, p.stdout)
                return AgentResult(
                    ok=False,
                    output="",
                    error_code=error_code,
                    error_msg=(p.stderr or p.stdout)[-2000:],
                )

            output, usage = _parse_gemini_json(p.stdout or "")
            return AgentResult(
                ok=True,
                output=output,
                usage=usage,
                session_id=extract_session_id(p.stdout) or extract_session_id(p.stderr),
            )

        except subprocess.TimeoutExpired as e:
            # 超时也要落证据：此前超时静默失败导致"无证据空转"难以定位
            save_evidence(current_task_id() or "gemini", 1, f"=== TIMEOUT after {timeout}s ===\n{str(e)[-1000:]}")
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
                error_msg="Gemini未安装",
            )
        except Exception as e:
            # 取证：异常路径此前不落 evidence，导致连败根因不可见
            try:
                save_evidence(current_task_id() or "gemini", 1, f"=== EXCEPTION ===\n{type(e).__name__}: {e}")
            except Exception:
                pass
            return AgentResult(
                ok=False,
                output="",
                error_code=ErrorCode.TOOL_FAIL,
                error_msg=str(e)[-2000:],
            )


# 别名：resolve() 需要模块级 Adapter 属性
Adapter = GeminiAdapter