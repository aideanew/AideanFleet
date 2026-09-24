"""这是什么：崩溃恢复入口（REL-01 §9.1）。四态 kill 后的"重启续跑"统一从这里走。
语义（与既有断点恢复契约一致，绝不重复派工）：
  · ASSIGNED  -> dispatcher.dispatch 续跑到 SUBMITTED（baseline 已存在则不重拍，不重复执行）。
  · DOING     -> dispatch 原样返回 already_doing——崩溃时执行体结果不可知，绝不重复派工；
                 后续由 retry_timer 的卡死检测按独立超时升级（REL-01 §9.3，与 Machine Gate 正交）。
  · SUBMITTED -> reviewer.review 续审（机器门 + 审查角色，无需重新派工）。
  · REVIEWING -> reviewer.review 再次进入判定（可续审）。
事件不重复的依据：dispatch/review 内部所有事件都绑定真实状态迁移，重复调用不会重放历史迁移。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from fleet.core import db
from fleet.manager import dispatcher, reviewer
from fleet.models import retry

#: 可恢复的中间态（四态矩阵口径）
RECOVERABLE_STATES: tuple[str, ...] = ("ASSIGNED", "DOING", "SUBMITTED", "REVIEWING")


def scan(project_id: str | None = None, *, db_file: str | Path | None = None) -> list[dict[str, Any]]:
    """找出所有停在可恢复中间态的任务，并给出建议动作。"""
    hints = {
        "ASSIGNED": "dispatch（续跑到 SUBMITTED）",
        "DOING": "dispatch（原样返回，不重复派工；卡死由 retry_timer 升级）",
        "SUBMITTED": "review（续审：机器门 + 审查角色）",
        "REVIEWING": "review（续审）",
    }
    out: list[dict[str, Any]] = []
    for task in db.list_tasks(project_id, db_file=db_file):
        state = str(task.get("exec_status") or "")
        if state in RECOVERABLE_STATES:
            out.append({"task_id": str(task["task_id"]), "state": state, "suggested": hints[state]})
    return out


def resume(
    task_id: str,
    *,
    actor: str = "rel",
    router_fn: Callable[..., Any] | None = None,
    policy: retry.RetryPolicy | None = None,
    db_file: str | Path | None = None,
) -> dict[str, Any]:
    """按当前状态续跑单个任务：ASSIGNED/DOING 走 dispatch，SUBMITTED/REVIEWING 走 review。"""
    task = db.get_task(task_id, db_file=db_file)
    if task is None:
        raise KeyError(f"任务不存在：{task_id}")
    state = str(task["exec_status"])

    if state in ("ASSIGNED", "DOING"):
        outcome = dispatcher.dispatch(task_id, actor=actor, policy=policy, db_file=db_file)
        return {
            "task_id": task_id,
            "from": state,
            "via": "dispatch",
            "state": outcome.state,
            "detail": outcome.detail,
            "ok": outcome.ok,
        }
    if state in ("SUBMITTED", "REVIEWING"):
        review = reviewer.review(task_id, actor=actor, router_fn=router_fn, db_file=db_file)
        return {
            "task_id": task_id,
            "from": state,
            "via": "review",
            "state": review.state,
            "verdict": review.verdict,
            "detail": review.detail,
            "ok": review.ok,
        }
    raise ValueError(f"状态 {state} 不在可恢复集合 {'/'.join(RECOVERABLE_STATES)} 内，拒绝恢复")


def recover_all(
    project_id: str | None = None,
    *,
    actor: str = "rel",
    router_fn: Callable[..., Any] | None = None,
    policy: retry.RetryPolicy | None = None,
    db_file: str | Path | None = None,
) -> dict[str, Any]:
    """重启后一键恢复：对 scan() 的每个任务逐条 resume（单条失败不影响其余），返回逐条结果。"""
    results: list[dict[str, Any]] = []
    for item in scan(project_id, db_file=db_file):
        try:
            results.append(
                resume(
                    item["task_id"],
                    actor=actor,
                    router_fn=router_fn,
                    policy=policy,
                    db_file=db_file,
                )
            )
        except Exception as error:  # 单任务恢复失败绝不拖垮整批
            results.append({"task_id": item["task_id"], "from": item["state"], "ok": False, "error": str(error)})
    return {"recovered": results, "total": len(results), "ok": all(item.get("ok") for item in results)}
