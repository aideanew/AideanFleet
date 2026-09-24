"""这是什么：模型路由器。按角色绑定的模型链依次尝试，失败自动降级，并把每次切换写进事件流。
怎么用：from fleet.models import router;  res = router.call("reviewer-1", "审查这段回执")
口径：429/超时 → 等 10 秒重试最多 10 次；401/402/403/额度耗尽/模型不存在 → 立即切换；
     全候选耗尽 → 返回 BLOCKED 并附每家失败原因；每次切换发事件 launch:model_switch（含 from/to/attempts）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from fleet.core import config, events

from . import pool, retry, transport
from .pool import ModelEntry
from .transport import TransportResult, get_transport

STATUS_OK = "OK"
STATUS_BLOCKED = "BLOCKED"


@dataclass
class CandidateAttempt:
    """单个候选模型的尝试记录（BLOCKED 时如实汇报，不允许含糊）。"""

    model: str
    platform: str
    model_id: str
    attempts: int = 0
    ok: bool = False
    text: str = ""
    error_code: str | None = None
    error: str = ""
    kind: str = ""
    usage: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "model": self.model,
            "platform": self.platform,
            "model_id": self.model_id,
            "attempts": self.attempts,
            "ok": self.ok,
            "error_code": self.error_code,
            "error": self.error,
            "kind": self.kind,
        }


@dataclass
class RouteResult:
    """一次路由的最终结果。status=BLOCKED 时 failures 必须非空。"""

    status: str
    output: str = ""
    model: str | None = None
    platform: str | None = None
    model_id: str | None = None
    attempts: int = 0
    switches: list[dict[str, Any]] = field(default_factory=list)
    failures: list[dict[str, Any]] = field(default_factory=list)
    usage: dict[str, Any] | None = None

    @property
    def ok(self) -> bool:
        return self.status == STATUS_OK

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "model": self.model,
            "platform": self.platform,
            "model_id": self.model_id,
            "attempts": self.attempts,
            "switches": self.switches,
            "failures": self.failures,
        }


class NoTransport(Exception):
    """没有可用的传输实现。"""


def _emit_switch(
    role: str,
    from_entry: ModelEntry | None,
    to_entry: ModelEntry,
    attempts: int,
    project: str | None = None,
) -> dict[str, Any]:
    """发 launch:model_switch 事件（extra 里的 from / to / attempts 字段冻结）。"""
    extra = {
        "role": role,
        "from": from_entry.name if from_entry else None,
        "to": to_entry.name,
        "attempts": attempts,
    }
    return events.append(
        actor="router",
        action="launch:model_switch",
        task_id=None,
        summary=f"{role} 模型切换：{extra['from'] or '(首个候选)'} -> {to_entry.name}（上一候选已试 {attempts} 次）",
        url=None,
        project=project,
        extra=extra,
    )


def _try_candidate(
    entry: ModelEntry,
    prompt: str,
    system_prompt: str | None,
    policy: retry.RetryPolicy,
    invoke: transport.Transport,
    *,
    role: str = "",
    project: str | None = None,
) -> CandidateAttempt:
    """对一个候选模型按策略重试，返回尝试记录。"""
    attempt = CandidateAttempt(model=entry.name, platform=entry.name, model_id=entry.model_id)
    while True:
        attempt.attempts += 1
        result: TransportResult = invoke(entry, prompt, policy.timeout_seconds, system_prompt)
        if result.ok:
            attempt.ok = True
            attempt.text = result.text
            attempt.usage = result.usage
            # CORE-04 契约 v1.2 §13.2：HTTP 路径每次成功调用发 model:call（usage 四键齐全）
            events.append(
                actor="router",
                action="model:call",
                task_id=None,
                summary=f"{role} 调用 {entry.name} 成功（attempts={attempt.attempts}）",
                url=None,
                project=project,
                extra={
                    "role": role,
                    "model": entry.name,
                    "model_id": entry.model_id,
                    "attempts": attempt.attempts,
                    "usage": transport.normalize_usage(result.usage),
                },
            )
            return attempt
        attempt.error_code = result.error_code
        attempt.error = result.error_msg
        attempt.kind = retry.classify(result.error_code, result.error_msg)
        if not policy.should_retry(attempt.kind, attempt.attempts):
            return attempt
        policy.wait()  # 软失败：等 10 秒再试（测试注入假 sleep）


def call(
    role: str,
    prompt: str,
    *,
    system_prompt: str | None = None,
    policy: retry.RetryPolicy | None = None,
    transport_fn: transport.Transport | None = None,
    project: str | None = None,
    emit_switch: bool = True,
) -> RouteResult:
    """按角色的模型链依次尝试，返回 RouteResult（网络异常不会向上抛）。

    transport_fn 为空时用 transport.get_transport()；单测注入假实现即可离线验证降级。
    """
    active_policy = policy or retry.policy()
    invoke = transport_fn or get_transport()
    chain = pool.chain_for(role)

    if not chain:
        if emit_switch:
            events.append(
                actor="router",
                action="launch:model_switch",
                summary=f"{role} 没有绑定任何可用模型",
                url=None,
                project=project,
                extra={"role": role, "from": None, "to": None, "attempts": 0},
            )
        return RouteResult(status=STATUS_BLOCKED, failures=[{"model": None, "error_code": "no_model_bound", "attempts": 0}])

    switches: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    previous: ModelEntry | None = None
    previous_attempts = 0

    for entry in chain:
        if previous is not None and emit_switch:
            switches.append(_emit_switch(role, previous, entry, previous_attempts, project))

        if not pool.is_available(entry):
            # 未配置 key：不空耗重试，直接记为失败并切下一个
            failures.append(
                {
                    "model": entry.name,
                    "platform": entry.name,
                    "model_id": entry.model_id,
                    "attempts": 0,
                    "ok": False,
                    "error_code": "no_key",
                    "error": f"{entry.name} 未配置可用 api_key（仍为占位）",
                    "kind": retry.HARD,
                }
            )
            previous, previous_attempts = entry, 0
            continue

        attempt = _try_candidate(entry, prompt, system_prompt, active_policy, invoke, role=role, project=project)
        previous_attempts = attempt.attempts
        previous = entry

        if attempt.ok:
            return RouteResult(
                status=STATUS_OK,
                output=attempt.text,
                model=entry.name,
                platform=entry.name,
                model_id=entry.model_id,
                attempts=attempt.attempts,
                switches=switches,
                failures=failures,
                usage=attempt.usage,
            )
        failures.append(attempt.to_dict())

    return RouteResult(status=STATUS_BLOCKED, failures=failures, switches=switches)


def blocked_reason(result: RouteResult) -> str:
    """把 BLOCKED 结果压成一行原因（附每家失败原因，便于事件/报告直接引用）。"""
    parts = [f"{item.get('model')}:{item.get('error_code') or 'error'}x{item.get('attempts')}" for item in result.failures]
    return "all_models_exhausted(" + ", ".join(parts) + ")"