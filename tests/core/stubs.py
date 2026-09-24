"""这是什么：tests/core 专用 stub 适配器与假审查回执。只在测试目录里，绝不进 fleet/executors。
要点：脚本化返回序列（429×10、401、成功……），并记录每次调用的入参供断言。
"""

from __future__ import annotations

from typing import Any

from fleet.manager.contracts import AgentResult, BaseAdapter


class StubAdapter(BaseAdapter):
    """按脚本逐个返回 AgentResult；脚本耗尽时重复最后一个。"""

    name = "stub"

    def __init__(self, script: list[AgentResult] | None = None) -> None:
        self.script = list(script or [AgentResult(ok=True, output="# 六节报告\n## 一、目标\n完成")])
        self.calls: list[dict[str, Any]] = []

    def run(self, prompt: str, workdir: str, model: str, timeout: int = 600) -> AgentResult:
        self.calls.append({"prompt": prompt, "workdir": workdir, "model": model, "timeout": timeout})
        if len(self.script) > 1:
            return self.script.pop(0)
        return self.script[0]

    @property
    def total_calls(self) -> int:
        return len(self.calls)


def ok_result(output: str = "# 六节报告\n## 一、目标\n完成") -> AgentResult:
    return AgentResult(ok=True, output=output, usage={"prompt_tokens": 1, "completion_tokens": 1})


def error_result(error_code: str, msg: str = "") -> AgentResult:
    return AgentResult(ok=False, error_code=error_code, error_msg=msg)


class FakeRoute:
    """假的 router.call 返回值：带 reviewer.review 用到的全部属性。"""

    def __init__(self, output: str, ok: bool = True, platform: str = "m2", model: str = "demo-2") -> None:
        self.ok = ok
        self.output = output
        self.platform = platform
        self.model = model
        self.error = ""
        self.kind = ""
        self.usage = None

    def to_dict(self) -> dict[str, Any]:
        return {"ok": self.ok, "output": self.output, "platform": self.platform, "model": self.model}


def pass_route() -> FakeRoute:
    return FakeRoute("审查意见：一切正常。VERDICT: PASS")


def rework_route() -> FakeRoute:
    return FakeRoute("审查意见：实现不完整。VERDICT: REWORK")


def make_task(project_id: str, task_id: str = "T-001", *, verify_cmd: str = 'python -c "print(1)"',
              workspace: str = "", allowed: str = "", forbidden: str = ".env",
              dependencies: list[str] | None = None) -> dict[str, Any]:
    """直接在 SQLite 里登记一个任务（绕过 dispatcher.create_task 的事件副作用，便于分场景组装）。"""
    from fleet.core import db

    return db.create_task(
        {
            "task_id": task_id,
            "project_id": project_id,
            "title": f"任务 {task_id}",
            "detail": "做一点事",
            "verify_cmd": verify_cmd,
            "assignee": "worker-a",
            "reviewer": "reviewer-1",
            "workspace": workspace,
            "allowed_files": allowed,
            "forbidden_files": forbidden,
            "adapter": "stub",
            "dependencies": dependencies or [],
        }
    )
