"""执行体适配器桥接层

将 fleet/manager/contracts.py 的 BaseAdapter 契约桥接到 fleet/executors/ 命名空间。
角色C 的具体适配器从本模块 import，而非直接依赖 contracts.py（保持关注点分离）。

设计意图：
  - contracts.py 定义契约（冻结），executors/ 实现契约
  - 本模块提供向后兼容的 ErrorCode/Capabilities 等工具
  - register_adapter/get_adapter 是 contracts.register/resolve 的便捷封装
"""

import json
import re
import shutil
import subprocess
from enum import Enum
from pathlib import Path
from typing import Optional

# 从 contracts.py 导入契约类（单向依赖，executors 依赖 manager）
from fleet.manager.contracts import (
    AgentResult,
    BaseAdapter,
    Capabilities,
    TaskPack,
    register,
    resolve,
    registered,
    unregister,
    AdapterNotAvailable,
)


class ErrorCode(str, Enum):
    """错误码枚举（内部工具，不改变 contracts 契约）"""
    RATE_LIMITED = "429"
    BAD_REQUEST = "400"
    TIMEOUT = "TIMEOUT"
    TOOL_FAIL = "TOOL_FAIL"
    UNAVAILABLE = "UNAVAILABLE"


def save_evidence(
    task_id: str,
    attempt: int,
    content: str,
    evidence_dir: str = "data/evidence",
) -> Path:
    """保存原始输出证据（辅助函数，供适配器使用）"""
    evidence_path = Path(evidence_dir) / task_id
    evidence_path.mkdir(parents=True, exist_ok=True)
    log_file = evidence_path / f"attempt-{attempt}.log"
    log_file.write_text(content, encoding="utf-8")
    return log_file


def current_task_id() -> str:
    """从线程本地执行上下文取当前 task_id（dispatcher.run_context 设置）。

    适配器在 run() 内调用，把证据按 task_id 而非适配器名落盘——
    此前 opencode/codex 把适配器名当 task_id 传，导致所有任务的证据
    覆盖同一个 data/evidence/<adapter>/attempt-1.log，无法按任务追溯。
    无上下文时返回空串（调用方自行回落到适配器名）。
    """
    try:
        from . import registry as _reg
        tid = _reg.get_run_context().get("task_id")
        if tid:
            return str(tid)
    except Exception:
        pass
    return ""


def detect_error(stderr: str, stdout: str) -> ErrorCode:
    """检测错误码（辅助函数，供适配器使用）"""
    combined = (stderr + stdout).lower()

    if "429" in combined or "rate limit" in combined or "too many requests" in combined:
        return ErrorCode.RATE_LIMITED
    if "400" in combined or "bad request" in combined or "invalid" in combined:
        return ErrorCode.BAD_REQUEST
    if "timeout" in combined or "timed out" in combined:
        return ErrorCode.TIMEOUT

    return ErrorCode.TOOL_FAIL


#: session id 的键名候选（不同 CLI 命名不一：codex=thread_id/session_id，claude=session_id，opencode=sessionID）
_SESSION_KEYS = ("session_id", "thread_id", "sessionID", "sessionId", "conversation_id")
_SESSION_RE = re.compile(
    r'"(?:' + "|".join(_SESSION_KEYS) + r')"\s*:\s*"([^"\s]{6,})"', re.IGNORECASE
)


def extract_session_id(text: str | None) -> str | None:
    """从 CLI 原始输出容错提取执行体会话 id。

    策略：① 逐行尝试 JSON 解析，取首个命中 _SESSION_KEYS 的标量值；
    ② 失败则正则兜底扫描 "session_id":"..." 形态。任何异常返回 None，
    绝不因提取失败影响派工主流程（session_id 是锦上添花的追踪字段）。
    """
    if not text:
        return None
    try:
        for line in text.splitlines():
            line = line.strip()
            if not line or ("{" not in line and '"' not in line):
                continue
            try:
                data = json.loads(line)
            except (json.JSONDecodeError, ValueError):
                continue
            if isinstance(data, dict):
                for key in _SESSION_KEYS:
                    value = data.get(key)
                    if isinstance(value, (str, int)) and str(value).strip():
                        return str(value).strip()
                # 嵌套一层（如 {"session": {"id": ...}} 形态）
                for value in data.values():
                    if isinstance(value, dict):
                        for key in _SESSION_KEYS:
                            nested = value.get(key)
                            if isinstance(nested, (str, int)) and str(nested).strip():
                                return str(nested).strip()
    except Exception:
        pass
    match = _SESSION_RE.search(text)
    return match.group(1) if match else None


# 便捷别名，让现有适配器代码无需修改
ADAPTER_REGISTRY: dict[str, type] = {}


def register_adapter(cls):
    """注册适配器类（装饰器形式）

    用法：
        @register_adapter
        class MyAdapter(BaseAdapter):
            name = "my"
            ...
    """
    ADAPTER_REGISTRY[cls.name] = cls
    # 同时注册到 contracts 的全局注册表（使用工厂函数）
    register(cls.name, lambda: cls())
    return cls


def get_adapter(name: str) -> Optional[BaseAdapter]:
    """获取适配器实例

    Args:
        name: 适配器名称

    Returns:
        Optional[BaseAdapter]: 适配器实例，不存在则返回 None
    """
    try:
        return resolve(name)
    except AdapterNotAvailable:
        return None


def resolve_cli(name: str) -> str:
    """解析 CLI 可执行文件完整路径。

    Windows 下 Popen 裸名（如 codex）只解析 .exe，找不到 npm shim 的 .cmd
    （WinError 2），导致派工静默连败。用 shutil.which 按 PATHEXT 解析完整路径；
    解析不到时原样返回（保持既有语义，由调用方报错）。
    """
    return shutil.which(name) or name


def pool_entry_for(model_id: str):
    """按 model_id 反查模型池条目；未命中返回 None（供各适配器决定桥接/降级策略）。"""
    if not model_id:
        return None
    try:
        from fleet.models import pool as pool_mod

        for entry in pool_mod.load_pool():
            if entry.model_id == model_id:
                return entry
    except Exception:
        pass
    return None


def kill_tree(pid: int) -> None:
    """终止整个进程树（Windows: taskkill /T /F；POSIX: 杀进程组）。

    兜底语义：PID 已退出/权限不足时静默——清理只做加法，不抛错。
    """
    import os
    import signal
    import subprocess as _sp
    import sys

    try:
        if sys.platform == "win32":
            _sp.run(
                ["taskkill", "/PID", str(pid), "/T", "/F"],
                capture_output=True, timeout=10,
                creationflags=_sp.CREATE_NO_WINDOW if hasattr(_sp, "CREATE_NO_WINDOW") else 0,
            )
        else:
            os.killpg(os.getpgid(pid), signal.SIGKILL)
    except Exception:
        pass


def run_subprocess_tree_safe(cmd, cwd, timeout, creationflags=0, env=None, input_text=None):
    """subprocess.run 的进程树安全版（Windows 专项治理）。

    问题：subprocess.run 超时只 terminate 主进程，cmd shim → node 的子进程树残留驻留。
    本封装：Popen 启动 → 超时/结束后 kill_tree(proc.pid) 兜底清树 → 保持 TimeoutExpired 异常语义。
    正常完成也兜底清一次（taskkill 对已退出树容错），杜绝执行体 spawn 的驻留子进程。
    env：注入子进程环境（如模型池 OPENAI_BASE_URL/OPENAI_API_KEY 桥接），None 表示继承父环境。
    input_text：经 stdin 传给子进程的文本。多行 prompt 走 argv 会被 cmd shim 截断，必须走 stdin。
    """
    proc = subprocess.Popen(
        cmd, cwd=cwd,
        stdin=subprocess.PIPE if input_text is not None else None,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, encoding="utf-8", errors="replace", creationflags=creationflags, env=env,
    )
    # 运行时登记（需求4）：控制台"运行中执行体"读数来自 fleet.executors.registry
    from . import registry as _registry
    reg_key = _registry.begin(cmd, cwd=cwd, proc=proc)
    try:
        stdout, stderr = proc.communicate(input=input_text, timeout=timeout)
    except subprocess.TimeoutExpired:
        kill_tree(proc.pid)
        try:
            stdout, stderr = proc.communicate(timeout=10)
        except Exception:
            stdout, stderr = "", ""
        raise subprocess.TimeoutExpired(cmd, timeout, output=stdout, stderr=stderr) from None
    finally:
        kill_tree(proc.pid)  # 兜底：无论正常/超时都清一次树，清理已退出树时静默容错
        _registry.end(reg_key)
    return subprocess.CompletedProcess(cmd, proc.returncode, stdout, stderr)
