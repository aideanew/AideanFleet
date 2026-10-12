"""这是什么：项目进度与预期完成时间（ETA）计算，供邮件通知使用。
怎么用：from fleet.notify import progress;  progress.compute_project_progress("P-001")
口径：
  · 进度百分比 = (终态任务数 + 0.5 × 进行中任务数) / 任务总数 × 100，四舍五入取整；
    终态 = DONE / PARTIAL / ESCALATED（与 core/state_machine.TERMINAL_STATES 冻结口径一致）；
    进行中 = DOING / SUBMITTED / REVIEWING，按半程记 0.5。
  · ETA = 当前时间 + 剩余未终态任务数 × 已完成任务的平均耗时（duration_ms，来自契约字段）；
    无已完成任务历史耗时时如实返回"暂无法预估"，绝不编造。
注意：本模块只读 DB，不改任何状态；BLOCKED/REWORK 等非终态任务计入"剩余"，其耗时
不确定性天然体现在"预估"语义里，不做额外加权。
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from fleet.core import db
from fleet.core import state_machine as sm

#: 进行中状态（按 0.5 权重计入进度）
IN_FLIGHT_STATES: frozenset[str] = frozenset({"DOING", "SUBMITTED", "REVIEWING"})
IN_FLIGHT_WEIGHT: float = 0.5

#: 单任务缺省历史耗时不可得时的提示文案
_ETA_NO_DATA = "暂无历史耗时数据，暂无法预估"


def _human_duration(seconds: float) -> str:
    """秒 -> 人读时长（X 分钟 / X 小时 Y 分钟）。"""
    minutes = int(round(seconds / 60))
    if minutes < 60:
        return f"{max(1, minutes)} 分钟"
    hours, rest = divmod(minutes, 60)
    return f"{hours} 小时 {rest} 分钟" if rest else f"{hours} 小时"


def compute_project_progress(project_id: str, db_file: str | Any = None) -> dict[str, Any]:
    """计算项目进度百分比与预期完成时间。空项目返回结构完整但数值为 0 的结果。"""
    empty = {
        "total": 0, "done": 0, "in_flight": 0, "remaining": 0,
        "percent": 0, "eta_text": _ETA_NO_DATA, "eta_iso": None,
        "eta_basis": "", "avg_task_text": "",
    }
    try:
        tasks = db.list_tasks(project_id, db_file=db_file)
    except Exception:
        return empty
    if not tasks:
        return empty

    total = len(tasks)
    done = [t for t in tasks if str(t.get("exec_status") or "") in sm.TERMINAL_STATES]
    in_flight = [t for t in tasks if str(t.get("exec_status") or "") in IN_FLIGHT_STATES]
    weighted = len(done) + IN_FLIGHT_WEIGHT * len(in_flight)
    percent = int(round(100.0 * weighted / total))
    remaining = total - len(done)

    durations_ms = [
        int(t.get("duration_ms") or 0)
        for t in tasks
        if str(t.get("exec_status") or "") == "DONE" and t.get("duration_ms")
    ]

    eta_text, eta_iso, eta_basis = _ETA_NO_DATA, None, ""
    if remaining <= 0:
        eta_text = "全部任务已完成，无剩余工作"
    elif durations_ms:
        avg_ms = sum(durations_ms) / len(durations_ms)
        eta_seconds = avg_ms / 1000.0 * remaining
        eta_dt = datetime.now().astimezone() + timedelta(seconds=eta_seconds)
        eta_iso = eta_dt.isoformat(timespec="minutes")
        eta_text = eta_dt.strftime("%m-%d %H:%M") + f"（约 {_human_duration(eta_seconds)}后）"
        avg_text = _human_duration(avg_ms / 1000.0)
        eta_basis = f"基于 {len(durations_ms)} 个已完成任务的平均耗时 {avg_text} 估算"
        empty["avg_task_text"] = avg_text

    return {
        "total": total,
        "done": len(done),
        "in_flight": len(in_flight),
        "remaining": remaining,
        "percent": max(0, min(100, percent)),
        "eta_text": eta_text,
        "eta_iso": eta_iso,
        "eta_basis": eta_basis,
        "avg_task_text": empty["avg_task_text"],
        # 轻量任务清单（邮件模板展示用；只取展示字段，不携带 detail 等重负载）
        "tasks": sorted(
            (
                {
                    "task_id": str(t.get("task_id") or ""),
                    "title": str(t.get("title") or ""),
                    "exec_status": str(t.get("exec_status") or ""),
                }
                for t in tasks
            ),
            key=lambda item: item["task_id"],
        ),
    }
