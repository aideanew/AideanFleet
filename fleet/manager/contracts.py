"""这是什么：控制面向"执行体适配器"暴露的唯一接口层 —— TaskPack、AgentResult、BaseAdapter、适配器注册表。
怎么用（角色C）：在 fleet/executors/<name>.py 里 `from fleet.manager.contracts import BaseAdapter, AgentResult`
                并实现 `run(self, prompt, workdir, model, timeout) -> AgentResult`；模块里放名为 `Adapter` 的类即可被自动发现。
怎么用（控制面）：dispatcher 只调 `BaseAdapter.run`，不关心底层是 CLI 还是 HTTP。
冻结说明：TaskPack 字段与 run() 签名一经定稿不再改名（工作包 §11 契约先行）。
边界：本文件属于角色A 的控制面，角色C 只 import、不修改。
"""

from __future__ import annotations

import importlib
import json
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field
from typing import Any, Callable

#: 适配器 lazy import 的前缀（角色C 的实现放这里）
EXECUTOR_PACKAGE = "fleet.executors"

#: context_budget 合法下限（契约 v1.2 §13.1：低于此值按缺省 8000 处理）
MIN_CONTEXT_BUDGET = 300
DEFAULT_CONTEXT_BUDGET = 8000


def _parse_budget(raw: Any) -> int:
    """解析 context_budget：非法/低于下限一律回退缺省 8000。"""
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return DEFAULT_CONTEXT_BUDGET
    return value if value >= MIN_CONTEXT_BUDGET else DEFAULT_CONTEXT_BUDGET


def _parse_refs(raw: Any) -> list[str]:
    """解析 memory_refs：DB 里是 JSON 文本，TaskPack 里是列表；非法一律空列表。"""
    if isinstance(raw, list):
        return [str(item) for item in raw if str(item).strip()]
    if isinstance(raw, str) and raw.strip():
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return []
        if isinstance(data, list):
            return [str(item) for item in data if str(item).strip()]
    return []


def _parse_json_object(raw: Any) -> dict[str, Any] | None:
    """解析 retry_context：JSON 文本或 dict；非法一律 None。"""
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str) and raw.strip():
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return None
        if isinstance(data, dict):
            return data
    return None


@dataclass
class Capabilities:
    """适配器能力自述（`初始设计/d7.md`：不同 CLI 能力并不相同，不能假设一致）。"""

    streaming: bool = False
    structured_output: bool = False
    resume_session: bool = False
    mcp: bool = False
    native_skills: bool = False
    sandbox: bool = False
    usage_reporting: bool = False


@dataclass
class AgentResult:
    """执行体一次运行的返回（字段冻结）。"""

    ok: bool
    output: str = ""
    error_code: str | None = None  # 429/401/402/403/quota_exhausted/model_not_found/TIMEOUT/TOOL_FAIL
    error_msg: str = ""
    usage: dict[str, Any] | None = None
    duration_ms: int = 0
    # 执行体会话 id（需求：每步派工记录执行体 session_id，供用户回溯 CLI 原始会话）。
    # 各适配器从 CLI 原始输出容错提取；提取不到为 None，绝不阻塞派工主流程。
    session_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class TaskPack:
    """派给一个执行体的完整任务包（字段冻结，见工作包 §9.5-1；v1.2 增补三个可选成本字段）。"""

    id: str
    title: str
    detail: str
    verify_cmd: str = ""
    assignee: str = ""
    reviewer: str = ""
    workspace: str = ""
    allowed_files: str = ""
    forbidden_files: str = ""
    project_id: str | None = None
    evidence_path: str | None = None
    report_path: str | None = None
    retry_limit: int = 3
    adapter: str = ""
    stage: str | None = None
    subtask: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)
    # ---- v1.2 上下文成本三可选字段（契约 控制台API.md §13.1，向后兼容） ----
    context_budget: int = 8000
    memory_refs: list[str] = field(default_factory=list)
    retry_context: dict[str, Any] | None = None

    @staticmethod
    def from_task(task: dict[str, Any]) -> "TaskPack":
        """由 SQLite 的任务行构建 TaskPack。"""
        return TaskPack(
            id=str(task.get("task_id", "")),
            title=str(task.get("title") or ""),
            detail=str(task.get("detail") or ""),
            verify_cmd=str(task.get("verify_cmd") or ""),
            assignee=str(task.get("assignee") or task.get("role") or ""),
            reviewer=str(task.get("reviewer") or ""),
            workspace=str(task.get("workspace") or ""),
            allowed_files=str(task.get("allowed_files") or ""),
            forbidden_files=str(task.get("forbidden_files") or ""),
            project_id=task.get("project_id"),
            evidence_path=task.get("evidence_path"),
            report_path=task.get("report_path"),
            retry_limit=int(task.get("retry_limit") or 3),
            adapter=str(task.get("adapter") or ""),
            context_budget=_parse_budget(task.get("context_budget")),
            memory_refs=_parse_refs(task.get("memory_refs")),
            retry_context=_parse_json_object(task.get("retry_context")),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def allowed_list(self) -> list[str]:
        from fleet.gates import verify

        return verify.parse_patterns(self.allowed_files)

    def forbidden_list(self) -> list[str]:
        from fleet.gates import verify

        return verify.parse_patterns(self.forbidden_files)

    def to_prompt(self) -> str:
        """渲染派工提示词（结构对应 docs/启动Hermes派工2(英文版).txt §5）。"""
        allowed = "\n".join(f"- {item}" for item in self.allowed_list()) or "- （未限定，仍不得越界改动）"
        return DISPATCH_TEMPLATE.format(
            task_id=self.id,
            title=self.title,
            objective=self.detail,
            workspace=self.workspace,
            assignee=self.assignee,
            reviewer=self.reviewer,
            allowed=allowed,
            forbidden=self.forbidden_files or "- 不得改动白名单之外的任何文件",
            verify_cmd=self.verify_cmd or "(none)",
            evidence=self.evidence_path or "(见 report_path)",
            report_path=self.report_path or "(未指定)",
            project=self.project_id or "(未指定)",
        )


#: 派工提示词模板：六节报告要求写在里面，执行体必须按契约回执
DISPATCH_TEMPLATE = """[MANAGER DISPATCH]
项目: {project}
任务 ID: {task_id}
标题: {title}
工作区(workspace): {workspace}
执行角色: {assignee}
审查角色: {reviewer}

目标:
{objective}

允许改动（allowed_files）:
{allowed}

禁止:
- 不得改动白名单之外的任何文件；
- 不得改动控制台/引擎状态与审计日志；
- 不得 git commit / git push；
- 不得输出任何明文 Key；
- 不得在无证据的情况下声称完成。

必须执行:
1. 先读取列出的既有文件再动手；
2. 只实现要求范围内的改动；
3. 运行要求的测试；
4. 原样运行机器门命令：{verify_cmd}
5. 证据在标准输出中原样返回，由 Fleet 保存到：{evidence}（执行体不得越界写入）；
6. 按 prompts/报告模板.md 返回完整六节报告（改动清单 / 命令记录 / 证据链 / 四要素 / 未完成事项 / 模型自述）；
7. 命令输出必须是真实原文，不得转述；
8. 写明 provider / model_id / 是否发生降级；
9. 被阻塞时如实返回 BLOCKED，并写清阻塞点与所需依赖。

报告由 Fleet 落盘到：{report_path}；执行体只返回完整六节报告，不创建控制面目录。
不要向用户提问，直接执行。
"""


class AdapterNotAvailable(Exception):
    """找不到该执行体适配器（角色C 尚未实现，或名字写错）。"""


class BaseAdapter(ABC):
    """执行体适配器抽象基类（工作包 §9.5-1，签名冻结）。"""

    #: 适配器名，需与 .env executors 段 / 角色的 adapter 字段一致
    name: str = "base"

    @abstractmethod
    def run(self, prompt: str, workdir: str, model: str, timeout: int = 600) -> AgentResult:
        """跑一次任务。

        **约定（冻结）**：`ok=False` 只用于"没能跑起来/没能拿到回执"（网关离线、超时、额度不足、进程异常），
        这类情况控制面会置 BLOCKED；**实现层面的失败要返回 ok=True + 六节报告**，
        由机器门（fleet/gates/verify.py）判定后走 REWORK —— 事实层不能被自述左右。
        必须自己吞掉所有异常并转成 AgentResult(ok=False, error_code=...)。
        """
        raise NotImplementedError

    def capabilities(self) -> Capabilities:
        """能力自述；默认全 False，由角色C 的具体适配器覆盖。"""
        return Capabilities()

    def __repr__(self) -> str:  # 便于日志排查
        return f"<Adapter {self.name}>"


# ---------------------------------------------------------------------------
# 适配器注册表：控制面只认名字，不 import 具体实现
# ---------------------------------------------------------------------------

_REGISTRY: dict[str, Callable[[], BaseAdapter]] = {}


def register(name: str, factory: Callable[[], BaseAdapter] | BaseAdapter) -> None:
    """注册适配器（工厂函数或实例）。测试里注入 FakeAdapter 就走这里。"""
    if isinstance(factory, BaseAdapter):
        _REGISTRY[name] = lambda: factory
    else:
        _REGISTRY[name] = factory


def unregister(name: str) -> None:
    """注销（测试清理用）。"""
    _REGISTRY.pop(name, None)


def registered() -> list[str]:
    """已注册的适配器名。"""
    return sorted(_REGISTRY)


def resolve(name: str) -> BaseAdapter:
    """按名字取适配器实例：先查注册表，再 lazy import fleet.executors.<name>。"""
    if not name:
        raise AdapterNotAvailable("适配器名为空；请在 .env roles 段填写 adapter 字段")
    if name in _REGISTRY:
        return _REGISTRY[name]()
    try:
        module = importlib.import_module(f"{EXECUTOR_PACKAGE}.{name}")
    except ImportError as error:
        raise AdapterNotAvailable(
            f"适配器 {name} 不可用（未注册且无法 import {EXECUTOR_PACKAGE}.{name}）：{error}"
        ) from error

    candidate = getattr(module, "Adapter", None) or getattr(module, "adapter", None)
    if candidate is None:
        raise AdapterNotAvailable(f"{EXECUTOR_PACKAGE}.{name} 里没有 Adapter 类或 adapter 实例")
    if isinstance(candidate, BaseAdapter):
        return candidate
    if isinstance(candidate, type) and issubclass(candidate, BaseAdapter):
        instance = candidate()
        instance.name = getattr(instance, "name", name) or name
        return instance
    raise AdapterNotAvailable(f"{EXECUTOR_PACKAGE}.{name} 的 Adapter 不是 BaseAdapter 子类")


def available_adapters() -> list[str]:
    """注册表 + fleet/executors 目录下可导入的适配器名（供控制台展示）。"""
    from pathlib import Path

    names = set(registered())
    try:
        package = importlib.import_module(EXECUTOR_PACKAGE)
        for path in getattr(package, "__path__", []):
            for file in Path(path).glob("*.py"):
                if not file.name.startswith("_"):
                    names.add(file.stem)
    except ImportError:
        pass
    return sorted(names)