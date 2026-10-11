"""这是什么：Steer——对话改计划的 Planner 侧实现（TASK-601，S6）。
语义（schemas/plan-diff.json）：
  steer todo（kind=steer）由模型产出 PlanDiff{add/cancel/modify}；
  kernel.apply_plan_diff(todo_id, decision) 原子应用：
    approve → add 新 todo / cancel → superseded / modify → 字段更新，plan_decision=approved；
    reject → 仅记录，plan_decision=rejected。
铁律：
  cancel/modify 引用的 todo 必须存在且非 done/superseded，否则校验失败走 successor 重试；
  不新增状态值（MN-05）：needs_user + plan_decision 承载"待确认"。
"""

from __future__ import annotations

import json
import re
from typing import Any, Callable

from ..kernel import Kernel
from ..kernel import state as st
from ..kernel.state import TurnResult

PROMPT_TEMPLATE = """你是 Fleet 的计划调整器。用户在看板运行中提出了新的指示，请输出计划变更（PlanDiff）。

【当前计划 todos】
{todos}

【用户指示】
{message}

只输出一个 JSON 对象（无 markdown 围栏）：
{{
  "add": [{{"id": "N1", "milestone": "M1", "title": "新任务", "role": "fe-1",
           "depends_on": [], "allowed_files": ["src/**"], "verify": ["真实命令"], "done_when": "…"}}],
  "cancel": ["T-xxx"],
  "modify": [{{"todo_id": "T-yyy", "fields": {{"title": "…", "verify": ["…"], "done_when": "…", "allowed_files": ["…"]}}}}]
}}
铁律：cancel/modify 只能引用上面列出的、状态非 done/superseded 的 todo id；
add 的 id 用 N1/N2…；verify 必须真实命令；无变更时输出空数组三键。"""


def build_prompt(todos: list[dict[str, Any]], message: str) -> str:
    slim = [{"id": t["id"], "title": t["title"], "status": t["status"],
             "verify": t["verify"], "allowed_files": t["allowed_files"]} for t in todos]
    return PROMPT_TEMPLATE.format(todos=json.dumps(slim, ensure_ascii=False, indent=1),
                                  message=message.strip())


def extract_diff(text: str) -> dict[str, Any]:
    fenced = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    candidate = fenced.group(1) if fenced else text
    start, end = candidate.find("{"), candidate.rfind("}")
    if start == -1 or end <= start:
        raise ValueError("回复中没有 JSON 对象")
    data = json.loads(candidate[start:end + 1])
    return {
        "add": data.get("add") or [],
        "cancel": data.get("cancel") or [],
        "modify": data.get("modify") or [],
    }


def validate_diff(kernel: Kernel, diff: dict[str, Any]) -> list[str]:
    """返回问题列表；空 = 可应用。add 项复用 plan schema 的关键字段校验。"""
    problems: list[str] = []
    known = {t["id"]: t for t in kernel.todos()}
    for tid in diff.get("cancel", []):
        todo = known.get(tid)
        if todo is None:
            problems.append(f"cancel 引用不存在的 {tid}")
        elif todo["status"] in (st.DONE, st.SUPERSEDED):
            problems.append(f"cancel 引用已终态 {tid}（{todo['status']}）")
    for m in diff.get("modify", []):
        tid = str(m.get("todo_id") or "")
        todo = known.get(tid)
        if todo is None:
            problems.append(f"modify 引用不存在的 {tid}")
        elif todo["status"] in (st.DONE, st.SUPERSEDED):
            problems.append(f"modify 引用已终态 {tid}")
        elif not (m.get("fields") or {}):
            problems.append(f"modify {tid} 缺 fields")
    for item in diff.get("add", []):
        if not (item.get("id") and item.get("title") and item.get("role")):
            problems.append(f"add 项缺 id/title/role: {item}")
            continue
        if not (item.get("verify") or []):
            problems.append(f"add {item['id']} 的 verify 必须是非空真实命令（A5）")
        if not (item.get("allowed_files") or []):
            problems.append(f"add {item['id']} 缺 allowed_files")
    return problems


def run_steer_todo(kernel: Kernel, todo_id: str, model_client: Callable[[str], str],
                   *, auto_apply: bool = False) -> TurnResult:
    """执行 kind=steer 的 todo：模型出 PlanDiff → 校验 → needs_user（或 auto 直接 approve）。"""
    todo = kernel.get_todo(todo_id)
    if todo["kind"] != "steer":
        raise ValueError(f"todo {todo_id} 不是 steer 类型")
    plan_todo = kernel.packet_for(todo_id)
    message = todo["packet"] or todo["title"]
    prompt = build_prompt(kernel.todos(todo["goal_id"]), message)
    try:
        reply = model_client(prompt)
    except Exception as exc:
        return TurnResult(verdict=st.VERDICT_BLOCKED, note=f"规划模型不可用: {exc}")
    try:
        diff = extract_diff(reply)
        problems = validate_diff(kernel, diff)
        if problems:
            raise ValueError("；".join(problems))
    except (ValueError, json.JSONDecodeError) as exc:
        return TurnResult(
            verdict=st.VERDICT_SUCCESSOR,
            note=f"PlanDiff 校验失败，重试: {exc}",
            successor={"title": todo["title"], "kind": "steer", "role": todo["role"],
                       "packet": message, "workspace": todo["workspace"]},
        )

    diff["source_todo"] = todo_id
    decision = "approved" if auto_apply else "pending"
    if auto_apply:
        kernel.apply_plan_diff(todo_id, "approve", diff=diff)
        return TurnResult(verdict=st.VERDICT_DONE, note="计划变更已自动应用（auto 模式）",
                          evidence_path=json.dumps(diff, ensure_ascii=False)[:2000])
    kernel.propose_plan_diff(todo_id, diff)
    return TurnResult(verdict=st.VERDICT_NEEDS_USER, note="计划变更待确认（plan_diff_review）")
