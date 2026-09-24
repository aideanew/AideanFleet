"""这是什么：返工管理器。REWORK 状态的任务由它负责"带意见重派"，ESCALATED 只能人工放行。
怎么用：from fleet.manager import rework_manager
        rework_manager.handle_rework("T-001")            # REWORK -> ASSIGNED（意见并入 detail）
        rework_manager.redispatch("T-001")               # 上一步 + 立即走完整派工
        rework_manager.confirm_release("T-001")          # ESCALATED 人工放行 -> 后继任务
规则（工作包 §9.4）：返工意见必须进下次派工提示词；rework_count > 3 已由 db.bump_rework
自动升级 ESCALATED 并停止自动派工；ESCALATED 是终态，放行 = 创建后继任务（原任务保持不动）。
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from typing import Any

from fleet.core import db, events, plan
from fleet.core import state_machine as sm
from fleet.core.paths import paths
from fleet.gates import verify as gates_verify

from . import dispatcher
from .contracts import TaskPack

#: 后继任务 id 的后缀模板
SUCCESSOR_SUFFIX = "-R{}"

# ---- Incremental Diff（CORE-04 契约 v1.2 §13.5）的截尾上限 ----
_DIFF_STAT_LIMIT = 1200
_FILE_DIFF_LIMIT = 1500
_MAX_FILE_DIFFS = 3


def _git_diff(workspace: str, args: list[str]) -> str | None:
    """只读执行 git diff 家族命令；非仓库/无 git/超时返回 None（不得编造）。"""
    if not workspace or not Path(workspace).is_dir():
        return None
    try:
        completed = subprocess.run(
            ["git", *args],
            cwd=str(Path(workspace)),
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if completed.returncode != 0:
        return None
    return completed.stdout or ""


def _collect_evidence_paths(task: dict[str, Any]) -> list[str]:
    """收集上轮证据文件（report.md / gate.json / verify_output.txt / changed_files.json 等）。"""
    out: list[str] = []
    for key in ("report_path", "evidence_path", "baseline_path"):
        value = str(task.get(key) or "").strip()
        if value and Path(value).exists() and value not in out:
            out.append(value)
    project_id = str(task.get("project_id") or "")
    task_id = str(task.get("task_id") or "")
    if project_id and task_id:
        gate_dir = paths().evidence_dir(project_id, task_id) / "gate"
        if gate_dir.is_dir():
            for item in sorted(gate_dir.iterdir()):
                if item.is_file():
                    out.append(str(item))
    return out


def _previous_diff(task: dict[str, Any]) -> dict[str, Any]:
    """上轮改动增量：优先 git diff --stat + 关键文件 diff（截尾）；退化用基线快照对比。"""
    workspace = str(task.get("workspace") or "").strip()
    stat = _git_diff(workspace, ["diff", "--stat"])
    files: dict[str, str] = {}
    source = "git"
    if stat is not None:
        changed = gates_verify.git_changed_files(workspace) or []
        for relative in changed[:_MAX_FILE_DIFFS]:
            diff = _git_diff(workspace, ["diff", "--", relative])
            if diff:
                files[relative] = diff[:_FILE_DIFF_LIMIT]
    else:
        source = "baseline"
        changed, source_name = gates_verify.changed_files_of(task)
        source = source_name if source_name != "none" else "none"
        stat = "（无 git 仓库，回退基线快照对比）" if changed else "（无 git 仓库且无基线快照，未生成 diff）"
    return {"stat": stat[:_DIFF_STAT_LIMIT], "files": files, "source": source}


def build_retry_context(task: dict[str, Any], *, db_file: str | Path | None = None) -> dict[str, Any]:
    """生成返工增量上下文（契约 v1.2 §13.5）：{attempt, failure, previous_diff, evidence_paths}。"""
    gate_info: dict[str, Any] | None = None
    gate_file = None
    project_id = str(task.get("project_id") or "")
    task_id = str(task.get("task_id") or "")
    if project_id and task_id:
        candidate = paths().evidence_dir(project_id, task_id) / "gate.json"
        if candidate.exists():
            gate_file = candidate
    if gate_file is None:
        for item in _collect_evidence_paths(task):
            if item.endswith("gate.json"):
                gate_file = Path(item)
                break
    if gate_file is not None:
        try:
            gate_info = json.loads(gate_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            gate_info = None
    return {
        "attempt": int(task.get("rework_count") or 0),
        "failure": {
            "gate": gate_info,
            "review": str(task.get("remark") or task.get("blocked_reason") or "").strip()[:500],
        },
        "previous_diff": _previous_diff(task),
        "evidence_paths": _collect_evidence_paths(task),
    }


def last_rework_opinion(detail: str) -> str:
    """从 detail 里取最后一个【返工意见 · 第 N 轮】块（作为返工 prompt 的修复指令）。"""
    matches = re.findall(r"【返工意见 · 第 \d+ 轮】\n?(.*)$", str(detail or ""), flags=re.S)
    return matches[-1].strip() if matches else ""


def _rework_reason(task: dict[str, Any], override: str | None) -> str:
    """返工意见来源：显式传入 > remark（bump_rework 写入的审查意见）> blocked_reason。"""
    text = str(override or "").strip()
    if text:
        return text
    for key in ("remark", "blocked_reason"):
        text = str(task.get(key) or "").strip()
        if text:
            return text
    return "审查意见未提供（自动返工重派）"


def handle_rework(
    task_id: str,
    *,
    actor: str = "manager",
    reason: str | None = None,
    db_file: str | Path | None = None,
) -> dict[str, Any]:
    """接手一个刚被判返工的任务，把返工意见并入 detail（下次派工提示词会带上）。

    两种到来形态都支持：
    - ASSIGNED（常态）：db.bump_rework 已按 resolve_rework_target 把 <=3 次的任务直接推回 ASSIGNED，
      这里只做"意见并入 detail"这一步，不再动状态；
    - REWORK（个别路径停在 REWORK）：执行 REWORK -> ASSIGNED 迁移并并入意见。
    ESCALATED 任务原样返回（不动状态、不派工）。
    """
    task = db.get_task(task_id, db_file=db_file)
    if task is None:
        raise KeyError(f"任务不存在：{task_id}")
    state = task["exec_status"]

    if state == "ESCALATED":
        return {
            "taskId": task_id,
            "state": "ESCALATED",
            "ok": False,
            "rework_count": int(task.get("rework_count") or 0),
            "detail": "已升级 ESCALATED，自动派工停止，等待 /api/control/confirm 人工放行",
        }
    if state not in ("REWORK", "ASSIGNED"):
        raise sm.InvalidTransition(state, "ASSIGNED", "只有 REWORK/ASSIGNED 状态可以返工重派")

    count = int(task.get("rework_count") or 0)
    text = _rework_reason(task, reason)
    original = str(task.get("detail") or "").rstrip()
    merged = (original + f"\n\n【返工意见 · 第 {count} 轮】\n{text}").strip()

    # CORE-04 契约 v1.2 §13.5：返工时自动生成增量 retry_context 并落库（派生数据，可重建）
    retry_context = build_retry_context(task, db_file=db_file)

    if state == "REWORK":
        updated = db.transition_and_log(
            task_id,
            "ASSIGNED",
            actor=actor,
            summary=f"{task_id} 返工重派（第 {count} 轮）：{text[:120]}",
            action="task:rework_dispatch",
            extra={"rework_reason": text[:500], "rework_count": count, "retry_context": retry_context},
            detail=merged,
            remark="",
            blocked_reason="",
            retry_context=retry_context,
            db_file=db_file,
        )
        return {
            "taskId": task_id,
            "state": str(updated["exec_status"]),
            "ok": True,
            "rework_count": count,
            "detail": f"已推回 ASSIGNED，返工意见并入派工提示词（第 {count} 轮）",
        }

    # ASSIGNED：只补 detail 与 retry_context，不重复发迁移事件（task:rework 已由 reviewer 发过）
    patch: dict[str, Any] = {}
    if merged != original:
        patch["detail"] = merged
    patch["retry_context"] = retry_context
    db.update_task(task_id, db_file=db_file, **patch)
    return {
        "taskId": task_id,
        "state": "ASSIGNED",
        "ok": True,
        "rework_count": count,
        "detail": f"返工意见已并入派工提示词（第 {count} 轮）",
    }


def redispatch(
    task_id: str,
    *,
    actor: str = "manager",
    reason: str | None = None,
    policy: Any | None = None,
    db_file: str | Path | None = None,
) -> dict[str, Any]:
    """返工重派的完整链路：REWORK -> ASSIGNED -> 立即 dispatch。

    返回值在 handle_rework 结果上附加 dispatch 字段，并把 state 更新为派工后的真实状态。
    """
    handled = handle_rework(task_id, actor=actor, reason=reason, db_file=db_file)
    if handled["state"] != "ASSIGNED":
        return handled
    result = dispatcher.dispatch(task_id, actor=actor, policy=policy, db_file=db_file)
    handled["dispatch"] = result.to_dict()
    handled["state"] = result.state
    handled["ok"] = result.state == "SUBMITTED"
    return handled


def confirm_release(
    task_id: str,
    *,
    actor: str,
    note: str = "",
    db_file: str | Path | None = None,
) -> dict[str, Any]:
    """ESCALATED 人工放行：创建后继任务（新 id、DRAFT、保留 rework_count），原任务保持 ESCALATED。

    设计决策：冻结状态机里 ESCALATED 是终态、没有 ESCALATED -> ASSIGNED 边，
    所以"放行"不等于改老任务状态，而是生成后继任务重新走完整流程。
    """
    task = db.get_task(task_id, db_file=db_file)
    if task is None:
        raise KeyError(f"任务不存在：{task_id}")
    if task["exec_status"] != "ESCALATED":
        raise ValueError("只有 ESCALATED 状态的任务需要人工放行")

    project_id = str(task.get("project_id") or "")
    successor_id = task_id + SUCCESSOR_SUFFIX.format(1)
    existing_ids = {row["task_id"] for row in db.list_tasks(project_id, db_file=db_file)}
    index = 1
    while successor_id in existing_ids:
        index += 1
        successor_id = task_id + SUCCESSOR_SUFFIX.format(index)

    suffix_note = f"【人工放行】{note.strip() or '人工确认后重新派工'}"
    merged_detail = (str(task.get("detail") or "").rstrip() + "\n\n" + suffix_note).strip()
    pack = TaskPack(
        id=successor_id,
        title=str(task.get("title") or successor_id),
        detail=merged_detail,
        verify_cmd=str(task.get("verify_cmd") or ""),
        assignee=str(task.get("assignee") or ""),
        reviewer=str(task.get("reviewer") or ""),
        workspace=str(task.get("workspace") or ""),
        allowed_files=str(task.get("allowed_files") or ""),
        forbidden_files=str(task.get("forbidden_files") or ""),
        project_id=project_id or None,
        adapter=str(task.get("adapter") or ""),
        stage=task.get("stage"),
        subtask=task.get("subtask"),
    )
    created = dispatcher.create_task(
        pack,
        project_id=project_id,
        stage=str(task.get("stage") or "默认阶段"),
        subtask=str(task.get("subtask") or task.get("title") or ""),
        dependencies=task.get("dependencies") or [],
        db_file=db_file,
    )
    # 后继任务继承返工计数，但本轮人工放行清零"连续失败"语义由 rework_count 延续表达
    created = db.update_task(successor_id, rework_count=int(task.get("rework_count") or 0), db_file=db_file)

    events.append(
        actor=actor,
        action="task:escalated_release",
        task_id=task_id,
        summary=f"{task_id} 人工放行 -> 后继任务 {successor_id}" + (f"（{note.strip()}）" if note.strip() else ""),
        url=f"/tasks/{successor_id}",
        project=project_id or None,
        extra={"successor": successor_id, "note": note[:500]},
    )
    if project_id:
        plan.sync_task_state(project_id, task_id, "ESCALATED")

    return {
        "taskId": task_id,
        "state": "ESCALATED",
        "released": True,
        "successor": successor_id,
        "successor_state": str(created.get("exec_status") or "DRAFT"),
        "ok": True,
    }
