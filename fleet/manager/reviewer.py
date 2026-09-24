"""这是什么：审查器。先跑机器门，再把回执交给审查角色，只接受 PASS/PARTIAL/REWORK/BLOCKED 四值。
怎么用：from fleet.manager import reviewer;  reviewer.review("T-001")
硬规则（工作包 §9.5-3）：机器门任一失败 → 直接 REWORK，Manager/LLM 无权改判；
                     门本身跑不起来（workspace/基线缺失）→ BLOCKED；
                     审查回执不是上述四值 → 判 BLOCKED（绝不默认放行为 PASS）。
返工：每次 REWORK 让 rework_count +1，超过 3 次即 ESCALATED（工作包 §9.1-1）。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from fleet.core import db, events
from fleet.core import state_machine as sm
from fleet.gates import verify
from fleet.models import retry, router

from . import report as report_parser

#: 审查提示词：要求只回一个判定值
REVIEW_PROMPT_TEMPLATE = """你是审查角色（只审查、不修改代码）。
请基于下面的**机器门事实**与执行体回执，给出唯一判定：PASS / PARTIAL / REWORK / BLOCKED。

硬性要求：
- 机器门事实优先于执行体自述；不得把 verify_cmd 失败解释成 PASS；
- 不得修改任何文件；
- 只允许在最后一行输出 `VERDICT: <四值之一>`，不要输出别的判定词。

任务：{task_id} — {title}
工作区：{workspace}
机器门：exit_code={exit_code}，passed={passed}，原因={reasons}
机器门输出（末尾 2000 字）：
{output}

执行体回执：
{report}
"""

_VERDICT_LINE_RE = re.compile(r"VERDICT\s*[:：]\s*(PASS|PARTIAL|REWORK|BLOCKED)", re.IGNORECASE)
_VERDICT_WORD_RE = re.compile(r"\b(PASS|PARTIAL|REWORK|BLOCKED)\b", re.IGNORECASE)
_JSON_VERDICT_RE = re.compile(r'"verdict"\s*:\s*"(PASS|PARTIAL|REWORK|BLOCKED)"', re.IGNORECASE)


@dataclass
class ReviewOutcome:
    """审查结果。verdict 一定是四值之一；invalid 回执也会被记成 BLOCKED（不写 PASS）。"""

    ok: bool
    task_id: str
    state: str
    verdict: str
    reviewer: str = ""
    detail: str = ""
    gate: dict[str, Any] = field(default_factory=dict)
    platform: str | None = None
    model: str | None = None
    rework_count: int = 0
    routed: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "taskId": self.task_id,
            "state": self.state,
            "verdict": self.verdict,
            "reviewer": self.reviewer,
            "detail": self.detail,
            "gate": self.gate,
            "platform": self.platform,
            "model": self.model,
            "rework_count": self.rework_count,
        }


def determine_verdict(text: str) -> str | None:
    """严格解析审查回执：只认四个值。

    优先级：JSON 的 verdict 字段 → `VERDICT: X` 行 → 全文唯一的四值词。
    出现两个不同判定词时视为歧义，返回 None（调用方判 BLOCKED）。
    """
    content = str(text or "")
    json_match = _JSON_VERDICT_RE.search(content)
    if json_match:
        return json_match.group(1).upper()

    line_match = _VERDICT_LINE_RE.search(content)
    if line_match:
        return line_match.group(1).upper()

    words = {match.group(1).upper() for match in _VERDICT_WORD_RE.finditer(content)}
    if len(words) == 1:
        return words.pop()
    return None


def build_review_prompt(task: dict[str, Any], gate: verify.GateResult, report_text: str) -> str:
    """拼审查提示词（机器门事实放在最前面）。"""
    return REVIEW_PROMPT_TEMPLATE.format(
        task_id=task["task_id"],
        title=task.get("title") or "",
        workspace=task.get("workspace") or "",
        exit_code=gate.exit_code,
        passed=gate.passed,
        reasons=", ".join(gate.reasons) or "无",
        output=gate.output_tail or "(无输出)",
        report=report_text or "(回执文件不可读)",
    )


def _read_report(task: dict[str, Any]) -> str:
    """读执行体回执文件；读不到返回空串（机器门已单独校验过存在性）。"""
    raw = str(task.get("report_path") or task.get("evidence_path") or "").strip()
    if not raw:
        return ""
    target = Path(raw)
    if not target.is_absolute() and task.get("workspace"):
        target = Path(str(task["workspace"])) / raw
    try:
        return target.read_text(encoding="utf-8")
    except OSError:
        return ""


def _rework(task: dict[str, Any], actor: str, reason: str, verdict: str) -> dict[str, Any]:
    """机器门失败或审查 REWORK：rework_count +1，>3 次自动升级 ESCALATED。"""
    updated = db.bump_rework(task["task_id"], remark=reason[:500], blocked_reason="")
    to_state = updated["exec_status"]
    action = "task:escalated" if to_state == "ESCALATED" else "task:rework"
    events.append(
        actor=actor,
        action=action,
        task_id=task["task_id"],
        summary=(
            f"{task['task_id']} 返工第 {updated['rework_count']} 次"
            + ("，已超过 3 次 → ESCALATED" if to_state == "ESCALATED" else "")
            + f"：{reason[:200]}"
        ),
        url=f"/tasks/{task['task_id']}",
        project=task.get("project_id"),
        extra={"verdict": verdict, "rework_count": updated["rework_count"], "state": to_state},
    )
    return updated


def review(
    task_id: str,
    *,
    actor: str = "manager",
    router_fn: Callable[..., Any] | None = None,
    policy: retry.RetryPolicy | None = None,
    db_file: str | Path | None = None,
) -> ReviewOutcome:
    """机器门 + 审查角色，得出终态。返回 ReviewOutcome。

    router_fn 默认用 models/router.call；单测/演练可注入假实现以离线跑通。
    """
    task = db.get_task(task_id, db_file=db_file)
    if task is None:
        raise KeyError(f"任务不存在：{task_id}")

    state = task["exec_status"]
    if state not in ("SUBMITTED", "REVIEWING"):
        sm.assert_transition(state, "REVIEWING")  # 非法就抛，交给调用方处理

    # ---------- 第一步：机器门（权威高于任何自述） ----------
    gate = verify.run_gate(task)

    # 机器门事件（契约 §9.5-3 的 8 事件链）：门跑不起来不归门管，不
    # 发 gate:pass/gate:fail，只发随后的 task:blocked。
    if not gate.fatal:
        events.append(
            actor="machine_gate",
            action="gate:pass" if gate.passed else "gate:fail",
            task_id=task_id,
            summary=(
                f"{task_id} 机器门{'通过' if gate.passed else '失败'}"
                f"（exit_code={gate.exit_code}）"
                + ("：" + "; ".join(gate.reasons)[:200] if gate.reasons else "")
            ),
            url=f"/tasks/{task_id}",
            project=task.get("project_id"),
            extra=gate.summarize(),
        )

    if gate.fatal:
        updated = db.transition_and_log(
            task_id,
            "BLOCKED",
            actor=actor,
            summary=f"{task_id} 机器门无法执行：{'; '.join(gate.reasons)}",
            remark="; ".join(gate.reasons)[:500],
            blocked_reason="gate_fatal",
            extra={"gate": gate.summarize()},
            db_file=db_file,
        )
        return ReviewOutcome(
            ok=False,
            task_id=task_id,
            state=updated["exec_status"],
            verdict="BLOCKED",
            reviewer=str(task.get("reviewer") or ""),
            detail="machine_gate_fatal",
            gate=gate.summarize(),
        )

    if state == "SUBMITTED":
        task = db.transition_and_log(
            task_id,
            "REVIEWING",
            actor=actor,
            summary=f"{task_id} 进入判别（机器门 passed={gate.passed}）",
            extra={"gate": gate.summarize()},
            db_file=db_file,
        )

    if not gate.passed:
        updated = _rework(task, actor, "machine_gate_failed: " + "; ".join(gate.reasons), "REWORK")
        return ReviewOutcome(
            ok=False,
            task_id=task_id,
            state=updated["exec_status"],
            verdict="REWORK",
            reviewer=str(task.get("reviewer") or ""),
            detail="machine_gate_failed（LLM 无权改判）",
            gate=gate.summarize(),
            rework_count=int(updated.get("rework_count") or 0),
        )

    # ---------- 第二步：审查角色（只审不改） ----------
    reviewer_role = str(task.get("reviewer") or task.get("receipt_role") or "").strip()
    report_text = _read_report(task)
    invoke = router_fn or router.call
    route = invoke(reviewer_role, build_review_prompt(task, gate, report_text), project=task.get("project_id"))

    verdict = None
    detail = ""
    if getattr(route, "ok", False):
        verdict = determine_verdict(getattr(route, "output", ""))
        if verdict is None:
            detail = "invalid_review_verdict（回执非法，按 BLOCKED 处理，绝不默认 PASS）"
    else:
        verdict = "BLOCKED"
        detail = "reviewer_route_blocked: " + router.blocked_reason(route)

    routed = route.to_dict() if hasattr(route, "to_dict") else {}
    platform = getattr(route, "platform", None)
    model = getattr(route, "model", None)

    # ---------- 第三步：按判定落库 ----------
    from fleet.core import plan

    base_extra = {"verdict": verdict, "gate": gate.summarize(), "routed": routed}
    if verdict in ("PASS", "PARTIAL"):
        # 审查通过事件（先于 task:done/task:partial，凑齐契约 8 事件链）
        events.append(
            actor=reviewer_role or actor,
            action="task:review_pass",
            task_id=task_id,
            summary=f"{task_id} 审查角色判定 {verdict}",
            url=f"/tasks/{task_id}",
            project=task.get("project_id"),
            extra={"verdict": verdict, "routed": routed},
        )
        updated = db.transition_and_log(
            task_id,
            "DONE" if verdict == "PASS" else "PARTIAL",
            actor=reviewer_role or actor,
            summary=f"{task_id} 审查通过（{verdict}）",
            remark=detail[:500],
            extra=base_extra,
            db_file=db_file,
            receipt_role=reviewer_role,
            platform=platform,
            model=model,
        )
        return ReviewOutcome(
            ok=True,
            task_id=task_id,
            state=updated["exec_status"],
            verdict=verdict,
            reviewer=reviewer_role,
            detail=detail,
            gate=gate.summarize(),
            platform=platform,
            model=model,
            rework_count=int(updated.get("rework_count") or 0),
            routed=routed,
        )

    if verdict == "REWORK":
        updated = _rework(task, reviewer_role or actor, "review_verdict=REWORK", "REWORK")
        plan.sync_task_state(str(task.get("project_id")), task_id, updated["exec_status"])
        return ReviewOutcome(
            ok=False,
            task_id=task_id,
            state=updated["exec_status"],
            verdict="REWORK",
            reviewer=reviewer_role,
            detail=detail or "review_verdict=REWORK",
            gate=gate.summarize(),
            platform=platform,
            model=model,
            rework_count=int(updated.get("rework_count") or 0),
            routed=routed,
        )

    reason = detail or "review_verdict=BLOCKED"
    updated = db.transition_and_log(
        task_id,
        "BLOCKED",
        actor=reviewer_role or actor,
        summary=f"{task_id} 审查阻塞：{reason[:200]}",
        remark=reason[:500],
        blocked_reason=reason[:200],
        extra=base_extra,
        db_file=db_file,
        receipt_role=reviewer_role,
        platform=platform,
        model=model,
    )
    return ReviewOutcome(
        ok=False,
        task_id=task_id,
        state=updated["exec_status"],
        verdict="BLOCKED",
        reviewer=reviewer_role,
        detail=reason,
        gate=gate.summarize(),
        platform=platform,
        model=model,
        rework_count=int(updated.get("rework_count") or 0),
        routed=routed,
    )