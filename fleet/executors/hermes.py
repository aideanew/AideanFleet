"""Hermes执行体适配器"""

import subprocess
import time
from pathlib import Path
from typing import Optional

from .base import BaseAdapter, AgentResult, ErrorCode, Capabilities, register_adapter, save_evidence, detect_error, run_subprocess_tree_safe, resolve_cli, extract_session_id


@register_adapter
class HermesAdapter(BaseAdapter):
    """Hermes子agent适配器"""

    name = "hermes"

    def capabilities(self) -> Capabilities:
        """探测Hermes能力"""
        try:
            result = subprocess.run(
                [resolve_cli("hermes"), "--help"],
                capture_output=True,
                text=True,
                timeout=10,
                creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0,
            )
            help_text = result.stdout + result.stderr

            return Capabilities(
                streaming=False,
                structured_output=False,
                mcp=False,
                native_skills=False,
                sandbox=False,
                usage_reporting=True,
            )
        except Exception:
            return Capabilities()

    def run_manager_gateway(self, timeout: int = 30) -> AgentResult:
        """启动Manager网关"""
        cmd = [resolve_cli("hermes"), "-p", "manager", "gateway", "run"]

        try:
            creationflags = subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0
            p = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                creationflags=creationflags,
            )
            # 运行时登记（需求4）：Manager 网关为长驻进程，登记后由 snapshot 按存活回收
            from . import registry as _registry
            _registry.begin(cmd, cwd=None, adapter="hermes", proc=p, label="hermes-manager-gateway")

            # 等待几秒检查是否启动成功
            time.sleep(2)

            if p.poll() is not None:
                stdout, stderr = p.communicate()
                return AgentResult(
                    ok=False,
                    output="",
                    error_code=ErrorCode.TOOL_FAIL,
                    error_msg=f"Manager网关启动失败: {stderr.decode('utf-8', errors='ignore')[-2000:]}",
                )

            return AgentResult(ok=True, output=f"Manager网关已启动, PID={p.pid}")

        except FileNotFoundError:
            return AgentResult(
                ok=False,
                output="",
                error_code=ErrorCode.UNAVAILABLE,
                error_msg="Hermes未安装",
            )
        except Exception as e:
            return AgentResult(
                ok=False,
                output="",
                error_code=ErrorCode.TOOL_FAIL,
                error_msg=str(e)[-2000:],
            )

    def run(
        self,
        prompt: str,
        workdir: str,
        model: str,
        timeout: int = 600,
    ) -> AgentResult:
        """执行Hermes子agent任务（消息转发）"""
        cmd = [resolve_cli("hermes"), "-p", "worker", "run", "--model", model, prompt]

        try:
            creationflags = subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0
            p = run_subprocess_tree_safe(
                cmd,
                cwd=workdir,
                timeout=timeout,
                creationflags=creationflags,
            )

            # 保存证据
            evidence_content = f"=== STDOUT ===\n{p.stdout}\n\n=== STDERR ===\n{p.stderr}"
            save_evidence("hermes", 1, evidence_content)

            if p.returncode != 0:
                error_code = detect_error(p.stderr, p.stdout)
                return AgentResult(
                    ok=False,
                    output="",
                    error_code=error_code,
                    error_msg=(p.stderr or p.stdout)[-2000:],
                )

            return AgentResult(ok=True, output=p.stdout, session_id=extract_session_id(p.stdout))

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
                error_msg="Hermes未安装",
            )
        except Exception as e:
            return AgentResult(
                ok=False,
                output="",
                error_code=ErrorCode.TOOL_FAIL,
                error_msg=str(e)[-2000:],
            )


# 别名：resolve() 需要模块级 Adapter 属性
Adapter = HermesAdapter
