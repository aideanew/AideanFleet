"""这是什么：DAG 依赖引擎（纯 Python，不经 LLM）。判断哪些任务"可以立刻派"。
怎么用：from fleet.manager import dag;  dag.get_ready_tasks("P-001");  dag.assert_acyclic({...})
规则：READY = exec_status=ASSIGNED 且所有 dependencies 均为 DONE，且与当前 DOING 任务的
     改动文件范围不冲突（冲突→暂不返回，写事件 task:deferred）；任务 DONE 后用
     release_dependents 找出"依赖已全满足"的下游（只报告，不改状态，分配由 Scheduler 决定）。
"""

from __future__ import annotations

import fnmatch
import json
from typing import Any

from fleet.core import db, events
from fleet.gates import verify


class CycleDetected(Exception):
    """依赖成环。建任务/更新依赖时抛出，落库前拦截。"""


def parse_dependencies(value: Any) -> list[str]:
    """dependencies 列（JSON 数组文本）-> task_id 列表；空/损坏一律返回 []。"""
    if not value:
        return []
    if isinstance(value, (list, tuple)):
        return [str(item) for item in value if str(item).strip()]
    try:
        data = json.loads(value)
    except (TypeError, ValueError):
        return []
    if isinstance(data, (list, tuple)):
        return [str(item) for item in data if str(item).strip()]
    return []


def detect_cycles(deps_map: dict[str, list[str]]) -> list[list[str]]:
    """拓扑排序检测依赖环。返回所有环（空列表 = 无环）。

    deps_map: {task_id: [依赖的 task_id, ...]}，缺失的依赖 id 视为外部节点，不参与成环。
    """
    remaining = {node: set(deps) for node, deps in deps_map.items()}
    known = set(remaining)
    # 只统计"图内"依赖：指向未知节点的依赖不影响本图拓扑
    for node in remaining:
        remaining[node] = {dep for dep in remaining[node] if dep in known}
    # 去自环的归并：自环也是环
    sorted_order: list[str] = []
    indegree_zero = sorted(node for node, deps in remaining.items() if not deps)
    taken: set[str] = set()
    while indegree_zero:
        node = indegree_zero.pop(0)
        taken.add(node)
        sorted_order.append(node)
        for other, deps in remaining.items():
            if other in taken or other in indegree_zero:
                continue
            if deps and deps <= taken:
                indegree_zero.append(other)
                indegree_zero.sort()
    if len(sorted_order) == len(remaining):
        return []
    cyclic = sorted(set(remaining) - taken)
    return [cyclic]


def assert_acyclic(deps_map: dict[str, list[str]]) -> None:
    """成环即抛 CycleDetected（建任务/更新依赖时调用，落库之前）。"""
    cycles = detect_cycles(deps_map)
    if cycles:
        raise CycleDetected(f"依赖成环：{' -> '.join(cycles[0] + [cycles[0][0]])}")


def _successor_chain_done(dep_id: str, tasks: list[dict[str, Any]]) -> bool:
    """依赖任务存在已完成的后继返工任务（task_id 以 f"{dep_id}-R" 开头且 DONE）即视为满足。"""
    prefix = f"{dep_id}-R"
    return any(
        str(t.get("task_id") or "").startswith(prefix) and t.get("exec_status") == "DONE"
        for t in tasks
    )


def _allowed_patterns(task: dict[str, Any]) -> list[str]:
    """任务的改动范围模式；白名单为空视为"无限制"（用 * 参与冲突比较）。"""
    return verify.parse_patterns(task.get("allowed_files")) or ["*"]


def _ranges_conflict(patterns_a: list[str], patterns_b: list[str]) -> bool:
    """两个改动范围是否可能写冲突：任一模式互相 fnmatch 命中即冲突。"""
    return any(
        fnmatch.fnmatch(a, b) or fnmatch.fnmatch(b, a)
        for a in patterns_a
        for b in patterns_b
    )




_UNRESTRICTED = frozenset({"*"})


def _is_unrestricted(patterns: list[str]) -> bool:
    """是否为全通配（空 allowed_files 回退为 ["*"]）。"""
    return set(patterns) == _UNRESTRICTED

#: 内存去重：同一任务因同一批 DOING 冲突只发一次 task:deferred（防调度循环刷屏）。
#: 键含 project_id：全局调度循环逐项目调用本函数，裸 task_id 会被其他项目的
#: "冲突消失"清理误删，导致每拍重写事件（实测 676 条刷屏的根因）。
_DEFER_SEEN: dict[tuple[str, str], str] = {}


def reset_defer_dedup() -> None:
    """清空 deferred 去重缓存（单测/换项目时用）。"""
    _DEFER_SEEN.clear()


def get_ready_tasks(project_id: str, db_file: str | Any = None) -> list[dict[str, Any]]:
    """返回"现在就可以派工"的任务列表（不改变任何状态）。

    条件：exec_status=ASSIGNED + 依赖全部 DONE + 与当前 DOING 任务无文件范围冲突。
    冲突任务写事件 task:deferred 后跳过（下一次冲突集变化时才再写，防事件刷屏）。
    """
    tasks = db.list_tasks(project_id, db_file=db_file)
    doing = [t for t in tasks if t.get("exec_status") == "DOING"]
    doing_ranges = [(t["task_id"], _allowed_patterns(t)) for t in doing]
    ready: list[dict[str, Any]] = []
    active_conflict_signature: set[str] = set()

    for task in tasks:
        if task.get("exec_status") != "ASSIGNED":
            continue
        deps = parse_dependencies(task.get("dependencies"))
        deps_ok = True
        for dep_id in deps:
            dep = next((t for t in tasks if t["task_id"] == dep_id), None)
            if dep is None or dep.get("exec_status") != "DONE":
                # 返工链语义：依赖任务 ESCALATED 后经人工放行产生后继（T01-R1...），
                # 任一后继 DONE 即视为依赖满足——原依赖卡死不应永久阻塞下游。
                if _successor_chain_done(dep_id, tasks):
                    continue
                deps_ok = False
                break
        if not deps_ok:
            continue

        own = _allowed_patterns(task)
        blockers: list[str] = []
        for tid, rng in doing_ranges:
            if _is_unrestricted(own) and _is_unrestricted(rng):
                # P1-B-2：双方均无限制（allowed_files 为空→["*"]），允许并行但发警告
                warn_key = (project_id, task["task_id"], "unrestricted")
                if _DEFER_SEEN.get(warn_key) != tid:
                    _DEFER_SEEN[warn_key] = tid
                    events.append(
                        actor="dag",
                        action="task:range_unrestricted",
                        task_id=task["task_id"],
                        summary=f"{task['task_id']} 与 {tid} 均未限定 allowed_files，并行执行但存在写冲突风险",
                        project=project_id,
                        extra={"conflicts_with": tid, "reason": "both_unrestricted"},
                    )
                continue  # 不阻塞
            if _ranges_conflict(own, rng):
                blockers.append(tid)
        blockers = sorted(blockers)
        if blockers:
            active_conflict_signature.add(task["task_id"])
            signature = ",".join(blockers)
            dedup_key = (project_id, task["task_id"])
            if _DEFER_SEEN.get(dedup_key) != signature:
                _DEFER_SEEN[dedup_key] = signature
                events.append(
                    actor="dag",
                    action="task:deferred",
                    task_id=task["task_id"],
                    summary=f"{task['task_id']} 暂缓派工：与执行中任务存在写范围冲突（{signature}）",
                    url=f"/tasks/{task['task_id']}",
                    project=project_id,
                    extra={"conflicts_with": blockers},
                )
            continue
        ready.append(task)

    # 冲突消失的任务清出去重表（仅限本项目条目），允许未来再次冲突时重新写事件
    for stale in [
        key for key in _DEFER_SEEN
        if key[0] == project_id and key[1] not in active_conflict_signature
    ]:
        _DEFER_SEEN.pop(stale, None)
    return ready


def release_dependents(completed_task_id: str, db_file: str | Any = None) -> list[str]:
    """某任务 DONE 后，找出"依赖它的任务里依赖已全部满足"的下游 id 列表。

    只做标记性报告（不改状态、不派工——分配由 Scheduler 决定）。
    completed_task_id 非 DONE 时返回 []（上游没完成谈不上释放）。
    """
    task = db.get_task(completed_task_id, db_file=db_file)
    if task is None or task.get("exec_status") != "DONE":
        return []
    project_id = task.get("project_id")
    if not project_id:
        return []
    tasks = db.list_tasks(project_id, db_file=db_file)
    by_id = {t["task_id"]: t for t in tasks}
    released: list[str] = []
    for candidate in tasks:
        if candidate.get("exec_status") != "ASSIGNED":
            continue
        deps = parse_dependencies(candidate.get("dependencies"))
        if completed_task_id not in deps:
            continue
        if all(
            (dep_id in by_id and by_id[dep_id].get("exec_status") == "DONE") or dep_id == completed_task_id
            for dep_id in deps
        ):
            released.append(candidate["task_id"])
    return sorted(released)
