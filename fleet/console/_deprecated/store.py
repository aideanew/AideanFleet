# [DEPRECATED · CORE-03] 本模块已废弃：实现已迁移到 fleet/core/config.py 与 SQLite。
# 归档于此仅供历史追溯，任何代码不得 import；确认全仓零引用后移入本目录。
# -*- coding: utf-8 -*-
"""
store.py —— AideanFleet 控制台的数据读写层（角色B · FLEET-FE-01）

职责：
  1. 事件流 events.jsonl（append-only）：seq 单调递增，launch-event 校验后落盘。
  2. plan.json（三级大纲）：默认 10 步准备清单，Manager 修正任务后由角色A更新本文件。
  3. projects.json：锁屏校验的项目列表。

契约说明（与角色A对齐的 mock 实现）：
  - 事件字段：seq / timestamp / actor / action / taskId / summary / url（+ 可选 phase/cli/model/percent）
  - /api/plan 返回三级大纲 phases -> steps -> children，用于总览与右侧进度条聚合百分比。
  - 角色A交付 fleet/core 后，仅需把本文件的读写替换为对 fleet/core 模块的调用。

本模块不依赖任何第三方库。
"""

import json
import os
import threading
import time

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
STATE_DIR = os.path.join(BASE_DIR, "fleet", "console", "state")

EVENTS_PATH = os.path.join(STATE_DIR, "events.jsonl")
PLAN_PATH = os.path.join(STATE_DIR, "plan.json")
PROJECTS_PATH = os.path.join(STATE_DIR, "projects.json")

_lock = threading.Lock()

# 用户设计原文的固定 10 步准备清单
DEFAULT_PREPARE_STEPS = [
    "接收指令",
    "分析需求",
    "初始化Manager",
    "建立项目主体计划",
    "确认创建模型库",
    "确认创建角色库",
    "确认创建执行体",
    "确认创建工具库",
    "确认创建提示词",
    "一切就绪!是否启动?",
]


def _now():
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime()) + (
        "%.3f" % (time.time() % 1))[1:] + "+08:00"


# ---------------------------------------------------------------- projects

def _ensure_projects():
    if not os.path.exists(PROJECTS_PATH):
        os.makedirs(STATE_DIR, exist_ok=True)
        data = {
            "projects": [
                {"id": "default", "name": "默认项目"},
                {"id": "aideanfleet", "name": "AideanFleet"},
            ]
        }
        with open(PROJECTS_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)


def list_projects():
    _ensure_projects()
    with open(PROJECTS_PATH, "r", encoding="utf-8") as f:
        return json.load(f).get("projects", [])


def project_exists(project_id):
    return any(p.get("id") == project_id for p in list_projects())


# ---------------------------------------------------------------- plan

def default_plan(project_id):
    """默认三级大纲：准备阶段（固定 10 步）+ 执行阶段（Manager 下发后才有内容）。

    launched 语义：False=还在准备清单阶段，右轨无执行进度；
    准备 10 步全部完成且用户确认启动后置 True。
    """
    steps = []
    for i, title in enumerate(DEFAULT_PREPARE_STEPS, start=1):
        steps.append({
            "id": f"prep-{i}",
            "index": f"{i}/10",
            "title": title,
            "status": "pending",  # pending / current / done
            "detail": "",
            "children": [],
        })
    return {
        "project": project_id,
        "confirm_mode": "confirm",  # confirm=每步确认 / auto=自动执行
        "launched": False,
        "updated_at": _now(),
        "phases": [
            {"id": "prepare", "title": "准备", "steps": steps},
            {"id": "execute", "title": "执行", "steps": []},
        ],
    }


def load_plan(project_id):
    _ensure_projects()
    os.makedirs(STATE_DIR, exist_ok=True)
    plans = {}
    if os.path.exists(PLAN_PATH):
        with open(PLAN_PATH, "r", encoding="utf-8") as f:
            try:
                plans = json.load(f)
            except (ValueError, TypeError):
                plans = {}
    plan = plans.get(project_id)
    if not plan:
        plan = default_plan(project_id)
        plans[project_id] = plan
        _save_plan_locked(plans)
    return plan


def _save_plan_locked(plans):
    tmp = PLAN_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(plans, f, ensure_ascii=False, indent=2)
    os.replace(tmp, PLAN_PATH)


def save_plan(project_id, plan):
    plan["updated_at"] = _now()
    with _lock:
        plans = {}
        if os.path.exists(PLAN_PATH):
            with open(PLAN_PATH, "r", encoding="utf-8") as f:
                try:
                    plans = json.load(f)
                except (ValueError, TypeError):
                    plans = {}
        plans[project_id] = plan
        _save_plan_locked(plans)


def set_mode(project_id, mode):
    """每步确认 / 自动执行 切换。"""
    plan = load_plan(project_id)
    plan["confirm_mode"] = mode
    save_plan(project_id, plan)


def phase_of(plan, phase_id):
    """按 id 找阶段（prepare / execute）。"""
    for ph in plan.get("phases", []):
        if ph.get("id") == phase_id:
            return ph
    return None


def mark_launched(project_id):
    """准备 10 步全部确认后启动执行：右轨从此显示执行阶段进度。"""
    plan = load_plan(project_id)
    plan["launched"] = True
    # 执行阶段第一步进入 current（有内容才推进）
    execute = phase_of(plan, "execute")
    if execute and execute["steps"] and all(s["status"] == "pending" for s in execute["steps"]):
        execute["steps"][0]["status"] = "current"
    save_plan(project_id, plan)
    return plan


def upsert_execute_step(project_id, step_id, title, status, detail=""):
    """执行阶段的步骤由 launch-event 动态登记/更新（Manager 下发任务后逐步出现）。"""
    plan = load_plan(project_id)
    execute = phase_of(plan, "execute")
    if execute is None:
        execute = {"id": "execute", "title": "执行", "steps": []}
        plan["phases"].append(execute)
    target = next((s for s in execute["steps"] if s["id"] == step_id), None)
    if target is None:
        target = {
            "id": step_id,
            "index": str(len(execute["steps"]) + 1),
            "title": title or step_id,
            "status": "pending",
            "detail": "",
            "children": [],
        }
        execute["steps"].append(target)
    if title:
        target["title"] = title
    if status in ("pending", "current", "done"):
        target["status"] = status
    if detail:
        target["detail"] = detail
    plan["launched"] = True
    save_plan(project_id, plan)
    return plan


def advance_step(project_id, step_id=None, status="done", detail=""):
    """根据事件推进准备阶段步骤状态（launch-event 上报 step_done/step_start 时调用）。

    准备阶段找不到 step_id 时，视为执行阶段任务，动态登记到 execute 相位。
    """
    plan = load_plan(project_id)
    steps = plan["phases"][0]["steps"]
    target = next((s for s in steps if s["id"] == step_id), None) if step_id else None
    if target is not None:
        target["status"] = status
        if detail:
            target["detail"] = detail
    else:
        if step_id:
            # 非准备清单的步骤 -> 归入执行阶段（右轨进度只统计这里）
            return upsert_execute_step(project_id, step_id, step_id, status, detail)
        for s in steps:
            if s["status"] == "current":
                s["status"] = "done"
                break
    # 自动把下一个 pending 置为 current
    for s in steps:
        if s["status"] != "done":
            if s["status"] != "current":
                s["status"] = "current"
            break
    # 准备 10 步全完成 => 视为已启动执行
    if all(s["status"] == "done" for s in steps):
        plan["launched"] = True
    save_plan(project_id, plan)
    return plan


def progress(plan):
    """按用户口径计算进度：

    - 准备阶段（launched=False）：右轨不显示执行进度，总览显示 n/10 准备清单；
      percent = 准备完成度（仅用于总览文案）。
    - 执行阶段（launched=True）：percent 只由 execute 相位聚合，
      准备阶段不计入总进度。
    返回 {launched, percent, done, total, current_phase, current_step}
    """
    prepare = phase_of(plan, "prepare") or {"steps": []}
    execute = phase_of(plan, "execute") or {"steps": []}
    launched = bool(plan.get("launched"))
    if not launched:
        total = len(prepare["steps"])
        done = sum(1 for s in prepare["steps"] if s["status"] == "done")
        current = next((s for s in prepare["steps"] if s["status"] == "current"), None)
        return {
            "launched": False,
            "percent": round(done * 100 / total) if total else 0,
            "done": done,
            "total": total,
            "current_phase": "prepare",
            "current_step": current,
        }
    esteps = execute["steps"]
    etotal = len(esteps)
    edone = sum(1 for s in esteps if s["status"] == "done")
    current = next((s for s in esteps if s["status"] == "current"), None)
    if current is None and esteps and edone == etotal:
        current = esteps[-1]  # 全部完成时末端停在最后一步
    return {
        "launched": True,
        "percent": round(edone * 100 / etotal) if etotal else 0,
        "done": edone,
        "total": etotal,
        "current_phase": "execute",
        "current_step": current,
    }


# ---------------------------------------------------------------- events

def next_seq():
    """读最后一个事件的 seq（内存不缓存，简单可靠）。"""
    last = 0
    if os.path.exists(EVENTS_PATH):
        with open(EVENTS_PATH, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    last = max(last, int(json.loads(line).get("seq", 0)))
                except (ValueError, TypeError):
                    continue
    return last


def append_event(event):
    """追加一条事件到 events.jsonl。调用方必须已校验必填字段。"""
    with _lock:
        seq = next_seq() + 1
        event = dict(event)
        event["seq"] = seq
        event.setdefault("timestamp", _now())
        event.setdefault("taskId", "")
        event.setdefault("url", "")
        os.makedirs(STATE_DIR, exist_ok=True)
        with open(EVENTS_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(event, ensure_ascii=False) + "\n")
    return event


def get_events(project_id, since=0, limit=200):
    """增量读取 seq > since 的事件（按项目过滤，seq 升序）。"""
    out = []
    if os.path.exists(EVENTS_PATH):
        with open(EVENTS_PATH, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    ev = json.loads(line)
                except (ValueError, TypeError):
                    continue
                if ev.get("seq", 0) <= since:
                    continue
                if ev.get("project") != project_id:
                    continue
                out.append(ev)
    out.sort(key=lambda e: e.get("seq", 0))
    return out[-limit:]


def required_event_fields_ok(data):
    """launch-event 必填字段校验：project/actor/action/summary 缺一不可。"""
    if not isinstance(data, dict):
        return False
    for k in ("project", "actor", "action", "summary"):
        if not str(data.get(k, "")).strip():
            return False
    return True
