"""这是什么：Kernel 的生命周期与 TurnResult 类型（typed turn result，取代自由文本状态）。
生命周期（对标 LoopX）：open → claimed → running → verifying → done | blocked | needs_user | superseded
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

#: todo 种类：exec=执行任务；plan=规划任务（Planner 产出计划）；steer=用户插话（计划 diff）
TODO_KINDS = ("exec", "plan", "steer")

#: 生命周期状态
OPEN = "open"
CLAIMED = "claimed"
RUNNING = "running"
VERIFYING = "verifying"
DONE = "done"
BLOCKED = "blocked"
NEEDS_USER = "needs_user"
SUPERSEDED = "superseded"

#: verifying 失败不是终态：以 successor 语义返工（kernel.transition 里处理）
REWORK_IF_ALLOWED = "rework"

#: 合法迁移表：from -> 允许的 to 集合
TRANSITIONS: dict[str, set[str]] = {
    OPEN: {CLAIMED, BLOCKED, SUPERSEDED, NEEDS_USER},
    CLAIMED: {RUNNING, OPEN, BLOCKED, NEEDS_USER, SUPERSEDED},
    RUNNING: {VERIFYING, OPEN, BLOCKED, NEEDS_USER, SUPERSEDED},
    VERIFYING: {DONE, REWORK_IF_ALLOWED, BLOCKED, NEEDS_USER, SUPERSEDED, RUNNING},
    DONE: set(),
    BLOCKED: {OPEN, SUPERSEDED, NEEDS_USER},  # 人工解除阻塞后重开
    NEEDS_USER: {OPEN, SUPERSEDED},           # 用户决策后重开或废弃
    SUPERSEDED: set(),
}

#: TurnResult 判定
VERDICT_DONE = "done"
VERDICT_SUCCESSOR = "successor"
VERDICT_BLOCKED = "blocked"
VERDICT_NEEDS_USER = "needs_user"
VERDICTS = (VERDICT_DONE, VERDICT_SUCCESSOR, VERDICT_BLOCKED, VERDICT_NEEDS_USER)


@dataclass
class TurnResult:
    """执行体一轮的 typed 结果：写回的唯一入口参数（kernel.transition(todo_id, result)）。

    verdict=done          本 todo 完成（verify 已通过）
    verdict=successor     需要返工/拆分：successor 携带新 todo 规格（同 lineage）
    verdict=blocked       执行受阻（缺依赖/越权），等待人工或上游
    verdict=needs_user    需要用户决策（计划确认、方向选择等）
    """

    verdict: str
    note: str = ""
    evidence_path: str = ""
    exit_code: int | None = None
    tokens_in: int = 0
    tokens_out: int = 0
    session_id: str = ""
    successor: dict[str, Any] = field(default_factory=dict)

    def to_payload(self) -> dict[str, Any]:
        return {
            "verdict": self.verdict,
            "note": self.note,
            "evidence_path": self.evidence_path,
            "exit_code": self.exit_code,
            "tokens_in": self.tokens_in,
            "tokens_out": self.tokens_out,
            "session_id": self.session_id,
            "successor": dict(self.successor),
        }
