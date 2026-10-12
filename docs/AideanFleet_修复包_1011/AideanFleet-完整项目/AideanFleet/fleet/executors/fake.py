"""Fake执行体适配器（用于测试）"""

import time
from typing import Callable, Optional

from .base import BaseAdapter, AgentResult, Capabilities, ErrorCode, register_adapter


@register_adapter
class FakeAdapter(BaseAdapter):
    """Fake执行体适配器，支持可注入失败模式

    用于测试重试逻辑、错误处理和通知触发。
    签名与 contracts.BaseAdapter 完全一致，零偏差。
    """

    name = "fake"

    def __init__(self, fail_with: Optional[str] = None):
        """初始化Fake适配器

        Args:
            fail_with: 可注入的失败模式
                - "429": 限流错误
                - "401": 认证错误
                - "TIMEOUT": 超时错误
                - None: 正常成功
        """
        self.fail_with = fail_with
        self.call_count = 0
        self.last_prompt = None
        self.last_workdir = None
        self.last_model = None

    def capabilities(self) -> Capabilities:
        """能力自述（contracts 契约方法）"""
        return Capabilities(
            streaming=False,
            structured_output=False,
            resume_session=False,
            mcp=False,
            native_skills=False,
            sandbox=False,
            usage_reporting=False,
        )

    def run(
        self,
        prompt: str,
        workdir: str,
        model: str,
        timeout: int = 600,
    ) -> AgentResult:
        """执行Fake任务

        Args:
            prompt: 提示词
            workdir: 工作目录
            model: 模型名称
            timeout: 超时时间（秒）

        Returns:
            AgentResult: 执行结果
        """
        self.call_count += 1
        self.last_prompt = prompt
        self.last_workdir = workdir
        self.last_model = model

        # 模拟执行延迟
        time.sleep(0.1)

        # 如果设置了失败模式，返回对应错误
        if self.fail_with:
            return self._create_failure_result()

        # 正常成功返回
        return AgentResult(
            ok=True,
            output=f"FakeAdapter: 已处理任务 '{prompt[:50]}...' (工作目录: {workdir})",
            error_code=None,
            error_msg="",
            usage={"prompt_tokens": 10, "completion_tokens": 20},
            duration_ms=100,
        )

    def run_stream(
        self,
        prompt: str,
        workdir: str,
        model: str,
        timeout: int = 600,
        on_chunk: Callable[[str], None] | None = None,
    ) -> AgentResult:
        """流式执行（P1-A-2）：分 3 次推送假文本块，最后返回正常结果。

        用于不花真钱验证 stream_chunk 管道是否畅通。
        """
        self.call_count += 1
        self.last_prompt = prompt
        self.last_workdir = workdir
        self.last_model = model

        chunks = ["开始分析需求...", "正在生成代码...", "完成，输出报告。"]
        for i, chunk in enumerate(chunks, 1):
            if on_chunk is not None:
                on_chunk(f"Fake chunk {i}/{len(chunks)}: {chunk}")
            time.sleep(0.05)

        if self.fail_with:
            return self._create_failure_result()

        return AgentResult(
            ok=True,
            output=f"FakeAdapter(streamed): 已处理任务 '{prompt[:50]}...' (工作目录: {workdir})",
            error_code=None,
            error_msg="",
            usage={"prompt_tokens": 10, "completion_tokens": 20},
            duration_ms=150,
        )

    def _create_failure_result(self) -> AgentResult:
        """创建失败结果"""
        if self.fail_with == "429":
            return AgentResult(
                ok=False,
                output="",
                error_code=ErrorCode.RATE_LIMITED,
                error_msg="429 Too Many Requests: Rate limit exceeded",
            )
        elif self.fail_with == "401":
            return AgentResult(
                ok=False,
                output="",
                error_code=ErrorCode.BAD_REQUEST,
                error_msg="401 Unauthorized: Invalid API key",
            )
        elif self.fail_with == "TIMEOUT":
            return AgentResult(
                ok=False,
                output="",
                error_code=ErrorCode.TIMEOUT,
                error_msg="Request timed out after 600 seconds",
            )
        else:
            return AgentResult(
                ok=False,
                output="",
                error_code=ErrorCode.TOOL_FAIL,
                error_msg=f"Unknown failure mode: {self.fail_with}",
            )

    def send_test_mail(self) -> tuple[bool, str]:
        """发送测试邮件（用于验证notify集成）"""
        try:
            from ..notify.smtp import send_email
            return send_email(
                subject="[Fleet] FakeAdapter测试邮件",
                body=f"这是FakeAdapter发送的测试邮件。\n\n"
                     f"发送时间: {time.strftime('%Y-%m-%d %H:%M:%S')}\n"
                     f"适配器: fake\n"
                     f"失败模式: {self.fail_with or '无'}",
            )
        except Exception as e:
            return False, f"发送测试邮件失败: {str(e)}"

    def get_call_stats(self) -> dict:
        """获取调用统计信息"""
        return {
            "call_count": self.call_count,
            "last_prompt": self.last_prompt,
            "last_workdir": self.last_workdir,
            "last_model": self.last_model,
            "fail_with": self.fail_with,
        }

    def reset_stats(self) -> None:
        """重置调用统计"""
        self.call_count = 0
        self.last_prompt = None
        self.last_workdir = None
        self.last_model = None


# 别名：resolve() 需要模块级 Adapter 属性
Adapter = FakeAdapter
