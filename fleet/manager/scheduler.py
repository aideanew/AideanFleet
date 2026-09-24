"""这是什么：调度器。周期性取 READY 任务交给 dispatcher，支持 auto（自动连跑）与 step（人工确认步进）。
怎么用：from fleet.manager import scheduler
        scheduler.schedule_once("P-001")                  # 单轮：DRAFT 收编 + READY 派工
        asyncio.run(scheduler.run_loop(scheduler.ControlBus()))   # 常驻循环，0.5s 一拍
节奏：asyncio.sleep(0.5) 定拍，绝不 busy-poll；模式切换通过 ControlBus.set_mode 通知，
循环每一拍先看模式，step 模式下没有人工 confirm 就挂起等待（同样只睡不转）。
"""

from __future__ import annotations

import asyncio
import threading
from pathlib import Path
from typing import Any

from fleet.core import db, events
from fleet.core import state_machine as sm
from . import dag as dag_engine
from . import dispatcher


#: 循环节拍（秒）。工作包 §9.7：asyncio.sleep(0.5)，不允许空转轮询
POLL_SECONDS = 0.5

#: 合法运行模式
MODES: tuple[str, ...] = ("auto", "step")


class ControlBus:
    """模式与人工确认的内存总线：控制台（HTTP/WS）写入，run_loop 消费。

    mode: auto = 有 READY 就派；step = 每派一个任务就挂起，等一次 confirm 放行。
    confirms: 人工确认队列（先进先出），auto 模式下 confirm 也会被收下但只记日志。
    """

    def __init__(self, mode: str = "auto") -> None:
        if mode not in MODES:
            raise ValueError(f"未知模式：{mode}（可选 {'/'.join(MODES)}）")
        self._lock = threading.Lock()
        self._mode = mode
        self._confirms: list[dict[str, Any]] = []
        self.awaiting_confirm = False

    @property
    def mode(self) -> str:
        with self._lock:
            return self._mode

    def set_mode(self, mode: str, *, actor: str = "console") -> str:
        """切换模式并发事件 mode:changed；run_loop 下一拍即生效。"""
        if mode not in MODES:
            raise ValueError(f"未知模式：{mode}（可选 {'/'.join(MODES)}）")
        with self._lock:
            previous = self._mode
            self._mode = mode
        if previous != mode:
            events.append(
                actor=actor,
                action="mode:changed",
                summary=f"调度模式切换：{previous} -> {mode}",
                extra={"from": previous, "to": mode},
            )
        return mode

    def confirm(self, *, task_id: str | None = None, actor: str = "console", note: str = "") -> dict[str, Any]:
        """人工放行一步（step 模式）或表达确认（auto 模式只记录）。"""
        item = {"task_id": task_id, "actor": actor, "note": note}
        with self._lock:
            self._confirms.append(item)
        return item

    def take_confirm(self) -> dict[str, Any] | None:
        """取走队首确认；没有则返回 None。"""
        with self._lock:
            if self._confirms:
                return self._confirms.pop(0)
        return None

    def pending_confirms(self) -> int:
        with self._lock:
            return len(self._confirms)


def collect_drafts(project_id: str, db_file: str | Path | None = None) -> list[str]:
    """把 DRAFT 任务收编成 ASSIGNED（DRAFT -> ASSIGNED 合法迁移），返回任务 id 列表。

    依赖未满足的 DRAFT 也会被收编——READY 判定由 dag 统一负责，收编不等于派工。
    """
    moved: list[str] = []
    for task in db.list_tasks(project_id, db_file=db_file):
        if task.get("exec_status") != "DRAFT":
            continue
        db.transition_and_log(
            task["task_id"],
            "ASSIGNED",
            actor="scheduler",
            summary=f"{task['task_id']} 进入待派队列（ASSIGNED）",
            extra={"by": "scheduler"},
            db_file=db_file,
        )
        moved.append(task["task_id"])
    return moved


def _persist_dispatch_failure(task_id: str, exc: BaseException, *, db_file: str | Path | None = None) -> None:
    """派工异常落 BLOCKED：只记内存 outcome 会让任务长期停在 DOING，控制台也看不到原因。

    无合法出边的状态（DRAFT/终态等）保持原样；落库失败必须静默，不能反过来杀掉调度循环。
    """
    if not task_id:
        return
    try:
        current = db.get_task(task_id, db_file=db_file)
    except Exception:
        return
    if current is None or not sm.can_transition(str(current.get("exec_status") or ""), "BLOCKED"):
        return
    reason = f"dispatch_exception: {exc}"
    try:
        db.transition_and_log(
            task_id,
            "BLOCKED",
            actor="scheduler",
            summary=f"{task_id} 派工异常，已阻塞待人工放行：{reason[:160]}",
            remark=reason[:500],
            blocked_reason=reason[:200],
            extra={"error": str(exc)[:500]},
            db_file=db_file,
        )
    except Exception:
        pass


def _safe_dispatch(task: dict[str, Any], label: str, fn: Any, *, db_file: str | Path | None = None) -> dict[str, Any]:
    """单任务失败只记 outcome 并落 BLOCKED，绝不向上抛——否则 asyncio.to_thread 里的
    异常会静默杀死整个 run_loop 线程（step 模式此前完全没有这层保护）。"""
    task_id = str(task.get("task_id") or "")
    try:
        return fn()
    except Exception as exc:
        _persist_dispatch_failure(task_id, exc, db_file=db_file)
        return {"taskId": task_id, "state": "ERROR", "ok": False, "detail": f"{label}: {exc}"}


def schedule_once(
    project_id: str | None = None,
    *,
    once: bool = False,
    policy: Any | None = None,
    db_file: str | Path | None = None,
) -> list[dict[str, Any]]:
    """跑一轮调度：DRAFT 收编 -> 取 READY -> 逐个 dispatch。

    project_id 为空时对全部项目各跑一轮。once=True 只派第一个 READY 任务（step 模式用）。
    返回每次 dispatch 的结果字典列表。
    """
    project_ids = [project_id] if project_id else [p["project_id"] for p in db.list_projects(db_file=db_file)]
    outcomes: list[dict[str, Any]] = []
    for pid in project_ids:
        try:
            collect_drafts(pid, db_file=db_file)
        except Exception as exc:  # 收编失败同样不能杀掉调度循环
            outcomes.append({"projectId": pid, "state": "ERROR", "ok": False,
                             "detail": f"draft_collect_failed: {exc}"})
            continue
        try:
            ready = dag_engine.get_ready_tasks(pid, db_file=db_file)
        except Exception as exc:
            outcomes.append({"projectId": pid, "state": "ERROR", "ok": False, "detail": f"dag_ready_failed: {exc}"})
            continue
        submitted = [
            t for t in db.list_tasks(pid, db_file=db_file)
            if t.get("exec_status") == "SUBMITTED"
        ]
        if once:
            # step 模式：一次 confirm 只走一步——优先评审 SUBMITTED（机器门），否则派一个 READY。
            if submitted:
                outcomes.append(_safe_dispatch(
                    submitted[0], "gate_review_failed",
                    lambda: dispatcher.run_to_completion(
                        submitted[0]["task_id"], actor="scheduler", policy=policy, db_file=db_file
                    ),
                    db_file=db_file,
                ))
            elif ready:
                outcomes.append(_safe_dispatch(
                    ready[0], "dispatch_failed",
                    lambda: dispatcher.dispatch(
                        ready[0]["task_id"], actor="scheduler", policy=policy, db_file=db_file
                    ).to_dict(),
                    db_file=db_file,
                ))
        else:
            # auto 模式：派完 READY 后，把已回执的 SUBMITTED 全部推进机器门到终态。
            for task in ready:
                outcomes.append(_safe_dispatch(
                    task, "dispatch_failed",
                    lambda task=task: dispatcher.dispatch(
                        task["task_id"], actor="scheduler", policy=policy, db_file=db_file
                    ).to_dict(),
                    db_file=db_file,
                ))
            for task in submitted:
                outcomes.append(_safe_dispatch(
                    task, "gate_review_failed",
                    lambda task=task: dispatcher.run_to_completion(
                        task["task_id"], actor="scheduler", policy=policy, db_file=db_file
                    ),
                    db_file=db_file,
                ))
    return outcomes


async def run_loop(
    bus: ControlBus,
    *,
    project_id: str | None = None,
    interval: float = POLL_SECONDS,
    max_ticks: int | None = None,
    policy: Any | None = None,
    db_file: str | Path | None = None,
    on_outcome: Any | None = None,
) -> None:
    """常驻调度循环。

    auto：每拍 schedule_once 一轮；step：收到一次 confirm 才派一个任务。
    每拍先看模式再干活，等待时只 asyncio.sleep，绝不 busy-poll。
    max_ticks 供测试/演练限次退出；正常常驻传 None。
    on_outcome：每次 dispatch 后的回调（server 用它把结果广播到 WebSocket）。
    """
    tick = 0
    while max_ticks is None or tick < max_ticks:
        tick += 1
        mode = bus.mode
        if mode == "step":
            if bus.take_confirm() is None:
                bus.awaiting_confirm = True
                await asyncio.sleep(interval)
                continue
            bus.awaiting_confirm = False

        outcomes = await asyncio.to_thread(
            schedule_once, project_id, once=(mode == "step"), policy=policy, db_file=db_file
        )
        for item in outcomes:
            if on_outcome:
                payload = on_outcome(item)
                if asyncio.iscoroutine(payload):
                    await payload
        await asyncio.sleep(interval)
