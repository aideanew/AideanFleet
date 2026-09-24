"""Cline执行体适配器"""

import json
import subprocess
from pathlib import Path
from typing import Optional

from .base import BaseAdapter, AgentResult, ErrorCode, Capabilities, register_adapter, save_evidence, current_task_id, detect_error, run_subprocess_tree_safe, pool_entry_for, resolve_cli, extract_session_id


def _parse_cline_json(stdout: str) -> tuple[str, dict | None]:
    """解析 `cline --json` NDJSON 事件流：拼接 text 事件内容，提取会话 id。

    事件结构（层级不固定，text 可能出现在 message/summary 等不同位置）：
    逐行宽松提取字符串字段 "text"；收集不到时降级为 (原样输出, None)，
    绝不因格式变化丢输出。
    """
    chunks: list[str] = []
    for line in (stdout or "").splitlines():
        line = line.strip()
        if not line or not line.startswith("{"):
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, dict):
            continue

        def _find_texts(node) -> list[str]:
            found: list[str] = []
            if isinstance(node, dict):
                for key, value in node.items():
                    if key == "text" and isinstance(value, str) and value.strip():
                        found.append(value)
                    else:
                        found.extend(_find_texts(value))
            elif isinstance(node, list):
                for item in node:
                    found.extend(_find_texts(item))
            return found

        chunks.extend(_find_texts(event))
    if not chunks:
        return stdout, None
    return "\n".join(chunks), None


@register_adapter
class ClineAdapter(BaseAdapter):
    """Cline执行体适配器（headless）"""

    name = "cline"

    def capabilities(self) -> Capabilities:
        """探测Cline能力"""
        try:
            result = subprocess.run(
                [resolve_cli("cline"), "--help"],
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
                usage_reporting=False,
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
        """执行Cline任务"""
        # 假执行防线：空 prompt 或只剩派工标记时直接判 unavailable，绝不空耗重试预算
        stripped = (prompt or "").strip()
        if not stripped or stripped.replace("[MANAGER REWORK DISPATCH]", "").strip() == "":
            return AgentResult(
                ok=False,
                output="",
                error_code=ErrorCode.UNAVAILABLE,
                error_msg="cline prompt 为空或仅含派工标记（疑似 cmd shim 截断），拒绝假执行",
            )
        workspace = Path(workdir).expanduser()
        if not workdir or not workspace.is_absolute() or not workspace.is_dir():
            return AgentResult(ok=False, error_code=ErrorCode.UNAVAILABLE,
                               error_msg="Cline 工作区必须是已存在的绝对目录，拒绝回退到控制面目录")
        directory = workspace.resolve().as_posix()

        cli = resolve_cli("cline")
        # -c 指定工作目录；-t 原生超时秒；--yolo 无人值守全自动批准（headless 非 TTY 下必加）；
        # --json NDJSON 事件流；prompt 走 stdin：多行派工提示词经 argv/cmd shim 会被截断。
        cmd = [cli, "--yolo", "--json", "-c", directory, "-t", str(timeout)]
        # 池模型（OpenAI 兼容端点）cline 无法直连，降级为 cline 默认凭据；非池模型才显式传。
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
            save_evidence(current_task_id() or "cline", 1, evidence_content)

            if p.returncode != 0:
                error_code = detect_error(p.stderr, p.stdout)
                return AgentResult(
                    ok=False,
                    output="",
                    error_code=error_code,
                    error_msg=(p.stderr or p.stdout)[-2000:],
                )

            output, _usage = _parse_cline_json(p.stdout or "")
            return AgentResult(
                ok=True,
                output=output,
                session_id=extract_session_id(p.stdout) or extract_session_id(p.stderr),
            )

        except subprocess.TimeoutExpired as e:
            # 超时也要落证据：此前超时静默失败导致"无证据空转"难以定位
            save_evidence(current_task_id() or "cline", 1, f"=== TIMEOUT after {timeout}s ===\n{str(e)[-1000:]}")
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
                error_msg="Cline未安装",
            )
        except Exception as e:
            # 取证：异常路径此前不落 evidence，导致连败根因不可见
            try:
                save_evidence(current_task_id() or "cline", 1, f"=== EXCEPTION ===\n{type(e).__name__}: {e}")
            except Exception:
                pass
            return AgentResult(
                ok=False,
                output="",
                error_code=ErrorCode.TOOL_FAIL,
                error_msg=str(e)[-2000:],
            )


# 别名：resolve() 需要模块级 Adapter 属性
Adapter = ClineAdapter