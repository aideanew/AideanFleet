"""这是什么：三级大纲规划文件 plan.json 的读写。Manager 每次分配后调它重写，控制台按它显示进度。
怎么用：from fleet.core import plan;  plan.update_task("P-001", "阶段0", "写契约", "T-001")
结构：{project, updated_at, 阶段:[{名称, 任务:[{子任务, task_id, state}]}]}（字段名冻结，见 docs/契约/任务进度表字段.md §7）
写盘：临时文件 + os.replace 原子替换，避免控制台读到半个 JSON。
"""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any

from .paths import paths

#: 写盘互斥锁：临时文件名固定（.<name>.tmp），并发写必须串行化，否则 Windows 上 replace 会撞文件
_SAVE_LOCK = threading.Lock()

STAGE_KEY = "阶段"
STAGE_NAME_KEY = "名称"
TASK_KEY = "任务"
SUBTASK_KEY = "子任务"
TASK_ID_KEY = "task_id"
STATE_KEY = "state"  # 扩展字段：镜像 SQLite 里的 exec_status，方便控制台直接渲染
WEIGHT_KEY = "权重"  # 可选扩展（需求3）：阶段/任务条目的进度权重，缺省等权

#: 计入"已完成"的状态（与控制台 server._progress_of、web stores/plan.ts 口径一致）
DONE_STATES = ("DONE", "PARTIAL")


# ---------------------------------------------------------------------------
# 权重化进度（需求3）：阶段 → 任务 两级树，叶子权重和恒等于 100.0（一级小数）
# ---------------------------------------------------------------------------

def _parse_weight(raw: Any, default: float = 1.0) -> float:
    """解析条目权重：缺省/非法/非正数一律回落 default，绝不抛异常。"""
    if raw is None:
        return default
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return default
    return value if value > 0 else default


def _distribute_pct(weights: list[float], total_pct: float = 100.0) -> list[float]:
    """按权重把 total_pct 精确拆成 1 位小数的份额（Hamilton 最大余数法）。

    保证 sum(返回) == round(total_pct, 1)，杜绝"加起来差 0.1%"的舍入漂移。
    """
    count = len(weights)
    if count == 0:
        return []
    if all(w <= 0 for w in weights):
        weights = [1.0] * count
    total_w = sum(weights)
    scale = total_pct / total_w
    raw = [w * scale for w in weights]
    tenths = [int(value * 10) for value in raw]
    remainder = int(round(total_pct * 10)) - sum(tenths)
    if remainder > 0:
        order = sorted(range(count), key=lambda i: raw[i] * 10 - tenths[i], reverse=True)
        for slot in range(remainder):
            tenths[order[slot % count]] += 1
    return [t / 10.0 for t in tenths]


def compute_progress(plan_data: dict[str, Any], states: dict[str, str]) -> dict[str, Any]:
    """权重化进度树（需求3 的唯一计算口径；/api/plan 与 WS progress 共用）。

    规则：
      - 阶段权重 = 显式"权重"，否则 Σ(该阶段任务权重)（等权时即任务数 → 与旧口径等价）；
      - 任务权重 = 显式"权重"，否则 1；
      - 叶子（任务）份额先分阶段再分任务，两级 Hamilton 舍入，全部叶子份额之和恒为 100.0；
      - plan.json 未登记的 SQLite 任务归入虚拟阶段「未归入计划」，保证不丢分母；
      - 无任务阶段的权重不参与分配（避免有权重却没状态的分母黑洞）。
    states: task_id -> exec_status（来自 SQLite，plan.json 的 state 镜像只作展示）。
    """
    stages_in = plan_data.get(STAGE_KEY, []) or []
    seen: set[str] = set()
    specs: list[tuple[str, list[tuple[str, float]], float | None]] = []  # (阶段名, [(task_id, 任务权重)], 阶段显式权重|None)
    explicit = False
    for stage in stages_in:
        if not isinstance(stage, dict):
            continue
        name = str(stage.get(STAGE_NAME_KEY, "") or "")
        stage_weight = _parse_weight(stage.get(WEIGHT_KEY)) if stage.get(WEIGHT_KEY) is not None else None
        if stage_weight is not None:
            explicit = True
        entries: list[tuple[str, float]] = []
        for entry in stage.get(TASK_KEY, []) or []:
            if not isinstance(entry, dict):
                continue
            task_id = entry.get(TASK_ID_KEY)
            if not task_id or task_id not in states:
                continue  # SQLite 里不存在（已删/未建）：不进分母
            seen.add(str(task_id))
            if entry.get(WEIGHT_KEY) is not None:
                explicit = True
            entries.append((str(task_id), _parse_weight(entry.get(WEIGHT_KEY))))
        if entries:
            specs.append((name, entries, stage_weight))
    orphans = [t for t in states if t not in seen]
    if orphans:
        specs.append(("未归入计划", [(t, 1.0) for t in orphans], None))

    total = len(states)
    done = sum(1 for state in states.values() if state in DONE_STATES)
    if not specs:
        return {"mode": "equal", "percent": round(done / total * 100, 1) if total else 0.0,
                "total": total, "done": done, "stages": []}

    stage_weights = [
        stage_weight if stage_weight is not None else sum(w for _, w in entries)
        for _name, entries, stage_weight in specs
    ]
    stage_pcts = _distribute_pct(stage_weights)

    stages_out: list[dict[str, Any]] = []
    percent = 0.0
    for (name, entries, _sw), stage_pct in zip(specs, stage_pcts):
        task_pcts = _distribute_pct([w for _, w in entries], total_pct=stage_pct)
        tasks_out: list[dict[str, Any]] = []
        stage_contrib = 0.0
        stage_done = 0
        for (task_id, _w), task_pct in zip(entries, task_pcts):
            state = states.get(task_id, "DRAFT")
            is_done = state in DONE_STATES
            if is_done:
                stage_done += 1
                percent += task_pct
            stage_contrib += task_pct
            tasks_out.append({
                "id": task_id, "subtask": "",
                "weight_pct": task_pct, "contrib_pct": task_pct,
                "state": state, "done": is_done,
            })
        stages_out.append({
            "name": name, "virtual": name == "未归入计划",
            "weight_pct": round(stage_contrib, 1), "contrib_pct": round(stage_contrib, 1),
            "total": len(entries), "done": stage_done, "tasks": tasks_out,
        })
    return {
        "mode": "weighted" if explicit else "equal",
        "percent": round(percent, 1), "total": total, "done": done, "stages": stages_out,
    }


def empty_plan(project_id: str) -> dict[str, Any]:
    """空计划骨架。"""
    return {"project": project_id, "updated_at": None, STAGE_KEY: []}


def plan_file(project_id: str) -> Path:
    """某项目的 plan.json 路径。"""
    return paths().plan_file(project_id)


def load(project_id: str) -> dict[str, Any]:
    """读取计划；文件不存在或损坏时返回空骨架（不抛异常，避免打断引擎）。"""
    target = plan_file(project_id)
    if not target.exists():
        return empty_plan(project_id)
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return empty_plan(project_id)
    if not isinstance(data, dict):
        return empty_plan(project_id)
    data.setdefault("project", project_id)
    data.setdefault(STAGE_KEY, [])
    return data


def save(project_id: str, data: dict[str, Any]) -> Path:
    """原子写：先写 .tmp 再 os.replace 覆盖。返回写入路径。并发写以锁串行化。"""
    from .db import iso_now

    target = plan_file(project_id)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = dict(data)
    payload["project"] = project_id
    payload["updated_at"] = iso_now()
    tmp = target.parent / f".{target.name}.tmp"
    with _SAVE_LOCK:
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.replace(tmp, target)
    return target


def find_stage(data: dict[str, Any], stage_name: str) -> dict[str, Any] | None:
    """按名称找阶段。"""
    for stage in data.get(STAGE_KEY, []):
        if stage.get(STAGE_NAME_KEY) == stage_name:
            return stage
    return None


def update_stage(project_id: str, stage_name: str, tasks: list[dict[str, Any]] | None = None,
                 weight: float | None = None) -> dict[str, Any]:
    """新建或整体替换一个阶段。tasks 为 [{子任务, task_id, 权重?}, ...]；weight 为阶段权重（需求3，可选）。"""
    data = load(project_id)
    stage = find_stage(data, stage_name)
    if stage is None:
        stage = {STAGE_NAME_KEY: stage_name, TASK_KEY: []}
        data.setdefault(STAGE_KEY, []).append(stage)
    if weight is not None:
        stage[WEIGHT_KEY] = weight
    if tasks is not None:
        stage[TASK_KEY] = [
            {
                SUBTASK_KEY: item.get(SUBTASK_KEY, ""),
                TASK_ID_KEY: item.get(TASK_ID_KEY),
                STATE_KEY: item.get(STATE_KEY),
                **({WEIGHT_KEY: item[WEIGHT_KEY]} if item.get(WEIGHT_KEY) is not None else {}),
            }
            for item in tasks
        ]
    save(project_id, data)
    return data


def update_task(project_id: str, stage_name: str, subtask: str, task_id: str, state: str | None = None) -> dict[str, Any]:
    """登记/更新一条"子任务 ↔ task_id"映射（Manager 每次分配后调用）。

    同一 task_id 已存在时原地更新，不重复追加。
    """
    data = load(project_id)
    stage = find_stage(data, stage_name)
    if stage is None:
        stage = {STAGE_NAME_KEY: stage_name, TASK_KEY: []}
        data.setdefault(STAGE_KEY, []).append(stage)
    entry = next((item for item in stage[TASK_KEY] if item.get(TASK_ID_KEY) == task_id), None)
    if entry is None:
        stage[TASK_KEY].append({SUBTASK_KEY: subtask, TASK_ID_KEY: task_id, STATE_KEY: state})
    else:
        entry[SUBTASK_KEY] = subtask or entry.get(SUBTASK_KEY, "")
        if state is not None:
            entry[STATE_KEY] = state
    save(project_id, data)
    return data


def sync_task_state(project_id: str, task_id: str, state: str) -> dict[str, Any]:
    """把某任务的最新状态镜像进 plan.json（找不到该 task_id 时不动结构）。"""
    data = load(project_id)
    changed = False
    for stage in data.get(STAGE_KEY, []):
        for entry in stage.get(TASK_KEY, []):
            if entry.get(TASK_ID_KEY) == task_id:
                entry[STATE_KEY] = state
                changed = True
    if changed:
        save(project_id, data)
    return data


def tasks_index(project_id: str) -> dict[str, dict[str, str]]:
    """task_id -> {stage, subtask} 的反查表，供控制台 API 拼装。"""
    index: dict[str, dict[str, str]] = {}
    for stage in load(project_id).get(STAGE_KEY, []):
        for entry in stage.get(TASK_KEY, []):
            task_id = entry.get(TASK_ID_KEY)
            if task_id:
                index[task_id] = {
                    "stage": str(stage.get(STAGE_NAME_KEY, "")),
                    "subtask": str(entry.get(SUBTASK_KEY, "")),
                }
    return index


def project_progress(project_id: str) -> dict[str, Any]:
    """进度读数（需求3 单口径）：plan.json 权重树 × SQLite 任务状态。"""
    from . import db  # 延迟导入，避免循环

    states = {row["task_id"]: str(row.get("exec_status") or "DRAFT") for row in db.list_tasks(project_id)}
    return compute_progress(load(project_id), states)


def snapshot(project_id: str) -> dict[str, Any]:
    """API 用快照：plan.json 的骨架 + 与 SQLite 合并后的 tasks 列表。

    字段见 docs/契约/控制台API.md §2（tasks[].id/state/assignee/reviewer/verify_cmd…）。
    扩展键：progress（权重进度树，需求3）、plan_exists（plan.json 是否已生成，需求2）。
    """
    from . import db  # 延迟导入，避免循环

    data = load(project_id)
    index = tasks_index(project_id)
    tasks: list[dict[str, Any]] = []
    for task in db.list_tasks(project_id):
        meta = index.get(task["task_id"], {})
        tasks.append(
            {
                "id": task["task_id"],
                "title": task.get("title") or meta.get("subtask") or "",
                "state": task["exec_status"],
                "assignee": task.get("assignee"),
                "reviewer": task.get("reviewer"),
                "verify_cmd": task.get("verify_cmd"),
                "task_type": task.get("task_type"),
                "review_status": task.get("review_status"),
                "stage": meta.get("stage"),
                "subtask": meta.get("subtask"),
                "rework_count": task.get("rework_count") or 0,
                "updated_at": task.get("updated_at"),
            }
        )
    project = db.get_project(project_id) or {}
    states = {task["id"]: str(task.get("state") or "DRAFT") for task in tasks}
    return {
        "project": project_id,
        "name": project.get("name") or data.get("project") or project_id,
        "updated_at": data.get("updated_at"),
        "plan_exists": plan_file(project_id).exists(),
        STAGE_KEY: data.get(STAGE_KEY, []),
        "tasks": tasks,
        "progress": compute_progress(data, states),
    }