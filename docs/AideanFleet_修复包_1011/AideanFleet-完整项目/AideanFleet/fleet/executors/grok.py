"""Grok执行体适配器"""

import json
import subprocess
from pathlib import Path
from typing import Optional

from .base import BaseAdapter, AgentResult, ErrorCode, Capabilities, register_adapter, save_evidence, current_task_id, detect_error, run_subprocess_tree_safe, pool_entry_for, resolve_cli, extract_session_id


def _parse_grok_json(stdout: str) -> tuple[str, dict | None]:
    """解析 grok -p --output-format json 输出。

    Grok 的 json 模式在 stdout 末尾输出单个 JSON 对象（含 sessionId）；运行期间可能
    混入非 JSON 的日志/进度行。逐行解析：最后一个合法 JSON 对象视为结果。
    规范结构：
    {"mode":"agentic","sessionId":"...","messages":[...],"usage":{"input_tokens":N,"output_tokens":N},...}
    主答复优先取 messages 里最后一个 role=assistant 的 content；usage 直接透传。
    """
    if not (stdout or "").strip():
        return stdout or "", None

    # 经典用法为单一 JSON 对象；先尝试整段解析
    try:
        data = json.loads(stdout)
    except json.JSONDecodeError:
        data = None
    if not isinstance(data, dict):
        # 降级：逐行找最后一个合法 JSON 对象
        last: dict | None = None
        for line in (stdout or "").splitlines():
            line = line.strip()
            if not line.startswith("{"):
                continue
            try:
                parsed = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(parsed, dict):
                last = parsed
        data = last

    if not isinstance(data, dict):
        return stdout, None
    if not data:
        return stdout, None

    text = _extract_grok_text(data)
    usage = data.get("usage")
    if not isinstance(usage, dict):
        usage = None
    else:
        try:
            inp = int(usage.get("input_tokens") or usage.get("inputTokenCount") or 0)
            out = int(usage.get("output_tokens") or usage.get("outputTokenCount") or 0)
            usage = {
                "prompt_tokens": inp,
                "completion_tokens": out,
                "reasoning_tokens": 0,
                "total_tokens": inp + out,
            }
        except (TypeError, ValueError):
            usage = None
    if isinstance(text, str) and text.strip():
        return text, usage
    return json.dumps(data, ensure_ascii=False), usage


def _extract_grok_text(data: dict) -> str | None:
    """从 grok 结果对象提取主答复文本（messages 里最后一个 assistant 消息）。"""
    messages = data.get("messages")
    if isinstance(messages, list):
        for message in reversed(messages):
            if not isinstance(message, dict):
                continue
            if str(message.get("role")) != "assistant":
                continue
            content = message.get("content")
            if isinstance(content, str) and content.strip():
                return content
            if isinstance(content, list):
                text = "\n".join(
                    part["text"] for part in content
                    if isinstance(part, dict) and isinstance(part.get("text"), str)
                ).strip()
                if text:
                    return text
    return None


@register_adapter
class GrokAdapter(BaseAdapter):
    """Grok CLI执行体适配器"""

    name = "grok"

    def capabilities(self) -> Capabilities:
        """探测Grok能力"""
        try:
            result = subprocess.run(
                [resolve_cli("grok"), "--version"],
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
                usage_reporting=True,  # usage 字段
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
        """执行Grok任务"""
        # 假执行防线：空 prompt 或只剩派工标记时直接判 unavailable，绝不空耗重试预算
        stripped = (prompt or "").strip()
        if not stripped or stripped.replace("[MANAGER REWORK DISPATCH]", "").strip() == "":
            return AgentResult(
                ok=False,
                output="",
                error_code=ErrorCode.UNAVAILABLE,
                error_msg="grok prompt 为空或仅含派工标记（疑似 cmd shim 截断），拒绝假执行",
            )
        workspace = Path(workdir).expanduser()
        if not workdir or not workspace.is_absolute() or not workspace.is_dir():
            return AgentResult(ok=False, error_code=ErrorCode.UNAVAILABLE,
                               error_msg="Grok 工作区必须是已存在的绝对目录，拒绝回退到控制面目录")
        directory = workspace.resolve().as_posix()

        cli = resolve_cli("grok")
        # -p 走 stdin（无位置参数时从 stdin 读取）；--no-auto-update 跳过自动更新；
        # --always-approve 无人值守；--output-format json 结构化输出。
        cmd = [cli, "--no-auto-update", "--always-approve", "-p", "--output-format", "json"]
        # 池模型（OpenAI 兼容端点）grok CLI 无法直连，降级为 grok 默认凭据；非池模型才显式传。
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
            save_evidence(current_task_id() or "grok", 1, evidence_content)

            if p.returncode != 0:
                error_code = detect_error(p.stderr, p.stdout)
                return AgentResult(
                    ok=False,
                    output="",
                    error_code=error_code,
                    error_msg=(p.stderr or p.stdout)[-2000:],
                )

            output, usage = _parse_grok_json(p.stdout or "")
            return AgentResult(
                ok=True,
                output=output,
                usage=usage,
                session_id=extract_session_id(p.stdout) or extract_session_id(p.stderr),
            )

        except subprocess.TimeoutExpired as e:
            # 超时也要落证据：此前超时静默失败导致"无证据空转"难以定位
            save_evidence(current_task_id() or "grok", 1, f"=== TIMEOUT after {timeout}s ===\n{str(e)[-1000:]}")
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
                error_msg="Grok未安装",
            )
        except Exception as e:
            # 取证：异常路径此前不落 evidence，导致连败根因不可见
            try:
                save_evidence(current_task_id() or "grok", 1, f"=== EXCEPTION ===\n{type(e).__name__}: {e}")
            except Exception:
                pass
            return AgentResult(
                ok=False,
                output="",
                error_code=ErrorCode.TOOL_FAIL,
                error_msg=str(e)[-2000:],
            )


# 别名：resolve() 需要模块级 Adapter 属性
Adapter = GrokAdapter