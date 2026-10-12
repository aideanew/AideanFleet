"""执行体适配器模块"""

from .base import (
    BaseAdapter,
    AgentResult,
    ErrorCode,
    Capabilities,
    register_adapter,
    get_adapter,
    save_evidence,
    detect_error,
)
from .claudecode import ClaudeCodeAdapter
from .codex import CodexAdapter
from .opencode import OpenCodeAdapter
from .hermes import HermesAdapter
from .cline import ClineAdapter
from .gemini import GeminiAdapter
from .grok import GrokAdapter
from .fake import FakeAdapter
from . import registry

__all__ = [
    "BaseAdapter",
    "AgentResult",
    "ErrorCode",
    "Capabilities",
    "register_adapter",
    "get_adapter",
    "save_evidence",
    "detect_error",
    "ClaudeCodeAdapter",
    "CodexAdapter",
    "OpenCodeAdapter",
    "HermesAdapter",
    "ClineAdapter",
    "GeminiAdapter",
    "GrokAdapter",
    "FakeAdapter",
]
