"""这是什么：任务状态机。定义 10 个状态、合法迁移表，以及"非法迁移必须抛异常且不落库"的闸门。
怎么用：from fleet.core import state_machine as sm;  sm.assert_transition("DRAFT", "ASSIGNED")
口径来源：docs/契约/任务状态机.md（已冻结）；改这里必须同步改契约文档与 tests/test_state_machine.py。
注意：本模块是纯函数，不碰数据库、不写事件；持久化一律由 db.transition_and_log 负责。
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# 状态（10 个，名称冻结）
# ---------------------------------------------------------------------------

STATES: tuple[str, ...] = (
    "DRAFT",
    "ASSIGNED",
    "DOING",
    "SUBMITTED",
    "REVIEWING",
    "DONE",
    "PARTIAL",
    "REWORK",
    "BLOCKED",
    "ESCALATED",
)

TERMINAL_STATES: frozenset[str] = frozenset({"DONE", "PARTIAL", "ESCALATED"})

#: 审查角色的合法回执（工作包 §9.5-2：只接受这四个值）
REVIEW_VERDICTS: tuple[str, ...] = ("PASS", "PARTIAL", "REWORK", "BLOCKED")

#: 审查回执 -> 目标状态
VERDICT_TO_STATE: dict[str, str] = {
    "PASS": "DONE",
    "PARTIAL": "PARTIAL",
    "REWORK": "REWORK",
    "BLOCKED": "BLOCKED",
}

#: review_status 列的取值（见 docs/契约/任务进度表字段.md §4）
REVIEW_STATUSES: tuple[str, ...] = ("PENDING", "REVIEWING", "PASS", "PARTIAL", "REWORK", "BLOCKED")

#: 合法迁移表：from -> {to, ...}（契约 §2 逐条对应）
TRANSITIONS: dict[str, frozenset[str]] = {
    "DRAFT": frozenset({"ASSIGNED"}),
    "ASSIGNED": frozenset({"DOING", "BLOCKED"}),
    "DOING": frozenset({"SUBMITTED", "BLOCKED"}),
    "SUBMITTED": frozenset({"REVIEWING", "BLOCKED"}),
    "REVIEWING": frozenset({"DONE", "PARTIAL", "REWORK", "BLOCKED"}),
    "REWORK": frozenset({"ASSIGNED", "ESCALATED"}),
    "BLOCKED": frozenset({"ASSIGNED"}),
    "DONE": frozenset(),
    "PARTIAL": frozenset(),
    "ESCALATED": frozenset(),
}

#: 返工升级阈值：REWORK 次数 > 3 → ESCALATED（工作包 §9.1-1）
REWORK_ESCALATE_THRESHOLD = 3

#: 状态 -> 执行期间语义（供控制台展示进度用）
ACTIVE_STATES: frozenset[str] = frozenset({"ASSIGNED", "DOING", "SUBMITTED", "REVIEWING", "REWORK"})


class InvalidTransition(Exception):
    """非法状态迁移。抛出即表示"不得落库"（契约 §2.2）。"""

    def __init__(self, from_state: str, to_state: str, reason: str = "") -> None:
        self.from_state = from_state
        self.to_state = to_state
        self.reason = reason or f"非法迁移：{from_state} -> {to_state}"
        super().__init__(self.reason)


def is_state(state: str) -> bool:
    """是否是已知状态。"""
    return state in STATES


def is_terminal(state: str) -> bool:
    """是否是终态（不再有出边）。"""
    return state in TERMINAL_STATES


def can_transition(from_state: str, to_state: str) -> bool:
    """是否允许迁移。"""
    return to_state in TRANSITIONS.get(from_state, frozenset())


def assert_transition(from_state: str, to_state: str) -> None:
    """校验迁移合法性；非法直接抛 InvalidTransition。

    调用方必须在**写数据库之前**调用本函数（契约 §5 第 1 步）。
    """
    if not is_state(from_state):
        raise InvalidTransition(from_state, to_state, f"未知源状态：{from_state}")
    if not is_state(to_state):
        raise InvalidTransition(from_state, to_state, f"未知目标状态：{to_state}")
    if not can_transition(from_state, to_state):
        raise InvalidTransition(from_state, to_state)


def resolve_rework_target(rework_count: int) -> str:
    """返工后该去哪：<=3 次回 ASSIGNED，>3 次升级 ESCALATED。"""
    return "ESCALATED" if int(rework_count) > REWORK_ESCALATE_THRESHOLD else "ASSIGNED"


def verdict_to_state(verdict: str) -> str:
    """审查回执转目标状态；回执非法抛 ValueError（调用方转成 BLOCKED）。"""
    text = str(verdict or "").strip().upper()
    if text not in VERDICT_TO_STATE:
        raise ValueError(f"非法审查回执：{verdict!r}；只允许 {'/'.join(REVIEW_VERDICTS)}")
    return VERDICT_TO_STATE[text]


def next_states(state: str) -> tuple[str, ...]:
    """某状态的合法出边（供控制台/调试展示）。"""
    return tuple(sorted(TRANSITIONS.get(state, frozenset())))