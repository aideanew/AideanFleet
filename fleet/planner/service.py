"""这是什么：Planner 服务（P2/A2：规划本身是一种 kind=plan 的 todo，由直连模型执行）。
怎么用：
    planner.run_plan_todo(kernel, todo_id, model_client)   # model_client(prompt)->str
    # 内部：组装规划提示词 → 调模型 → 提取 JSON → schema 校验 → 写入 kernel todos
失败语义（方案 4.4）：
    - JSON 解析/schema 校验失败 → TurnResult(verdict="successor", successor={...重试包...})
      或轮数超限时由 kernel 判 needs_user；
    - 模型完全不可用 → verdict="blocked"。
A3 对话即控制面：用户每句话由上层转成 kind=steer todo，Planner 产出计划 diff
（step 模式经 needs_user 等用户确认，auto 模式直接生效）。
"""

from __future__ import annotations

import json
import re
from typing import Any, Callable

from ..kernel import Kernel
from ..kernel import state as st
from ..kernel.state import TurnResult
from .schema import PlanValidationError, validate_plan

ModelClient = Callable[[str], str]

PROMPT_TEMPLATE = """你是 Fleet 的规划器（Planner）。把下面的需求拆解为可并行推进的里程碑与任务。

【需求】
{requirements}

【上下文】
- 目标: {goal_title}
- 已有任务（避免重复拆分）: {existing}
- 可用执行角色: {roles}

【输出要求】
只输出一个 JSON 对象（不要 markdown 代码围栏、不要解释文字），结构：
{{
  "milestones": [{{"id": "M1", "title": "阶段名"}}],
  "todos": [
    {{"id": "T1", "milestone": "M1", "title": "任务名", "role": "角色名",
      "depends_on": [], "allowed_files": ["src/**"],
      "verify": ["真实验收命令，例如 pnpm build / python -m pytest -q"],
      "done_when": "完成判定的客观描述"}}
  ]
}}
铁律：
1. verify 必须是真实可执行命令（构建/测试/lint），禁止"文件存在即通过"；
2. 每个任务都要有 allowed_files 白名单，并行任务的 allowed_files 不得相交；
3. id 唯一、depends_on 引用存在的任务、不得成环；
4. 任务粒度：一个任务一次可交付，2~8 个任务为宜。
"""


def extract_json(text: str) -> Any:
    """从容错提取模型回复里的 JSON 对象（容忍围栏与前后闲话）。"""
    fenced = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    candidate = fenced.group(1) if fenced else text
    start = candidate.find("{")
    end = candidate.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise PlanValidationError("回复中没有 JSON 对象")
    return json.loads(candidate[start:end + 1])


def build_prompt(requirements: str, goal_title: str, existing: list[dict[str, Any]],
                 roles: list[str]) -> str:
    return PROMPT_TEMPLATE.format(
        requirements=requirements.strip() or "（未提供，请按目标合理拆解）",
        goal_title=goal_title,
        existing=json.dumps([{"id": t["id"], "title": t["title"], "status": t["status"]}
                             for t in existing], ensure_ascii=False) or "[]",
        roles=", ".join(roles) or "（未配置，按通用工程角色命名）",
    )


def apply_plan(kernel: Kernel, goal_id: str, plan: dict[str, Any],
               base_depends: list[str] | None = None) -> list[str]:
    """把校验过的计划写入 kernel：返回新 todo id 列表（按计划顺序，依赖已映射）。"""
    id_map: dict[str, str] = {}
    created: list[str] = []
    for spec in plan["todos"]:
        deps = [id_map[d] for d in spec["depends_on"]]
        if base_depends and not deps:
            deps = list(base_depends)
        tid = kernel.create_todo(
            goal_id,
            kind="exec",
            title=f"[{spec['milestone'] or 'M'}] {spec['title']}" if spec.get("milestone") else spec["title"],
            role=spec["role"],
            depends_on=deps,
            allowed_files=spec["allowed_files"],
            verify=spec["verify"],
            done_when=spec["done_when"],
            packet=f"milestone={spec['milestone']};id={spec['id']}",
        )
        id_map[spec["id"]] = tid
        created.append(tid)
    return created


def run_plan_todo(kernel: Kernel, todo_id: str, model_client: ModelClient) -> TurnResult:
    """执行一个 kind=plan 的 todo：模型出计划 → 校验 → 写入。返回写回用 TurnResult。"""
    todo = kernel.get_todo(todo_id)
    if todo["kind"] != "plan":
        raise ValueError(f"todo {todo_id} 不是 plan 类型")
    packet = kernel.packet_for(todo_id)
    requirements = packet["todo"].get("packet") or packet["todo"]["title"]
    roles = todo.get("role", "").split(",") if todo.get("role") else []
    prompt = build_prompt(
        requirements=requirements,
        goal_title=(packet["goal"] or {}).get("title", ""),
        existing=packet["siblings"],
        roles=[r.strip() for r in roles if r.strip()],
    )
    try:
        reply = model_client(prompt)
    except Exception as exc:
        return TurnResult(verdict=st.VERDICT_BLOCKED, note=f"规划模型不可用: {exc}")
    try:
        plan = validate_plan(extract_json(reply))
    except (PlanValidationError, json.JSONDecodeError) as exc:
        # 重试包：把错误反馈给下一轮（successor 语义），轮数超限由 kernel 判 needs_user
        return TurnResult(
            verdict=st.VERDICT_SUCCESSOR,
            note=f"计划校验失败，重试: {exc}",
            successor={"title": todo["title"], "kind": "plan", "role": todo["role"],
                       "packet": requirements + f"\n\n【上一轮错误，务必修正】{exc}"},
        )
    created = apply_plan(kernel, todo["goal_id"], plan)
    return TurnResult(verdict=st.VERDICT_DONE, note=f"计划已生成 {len(created)} 个任务",
                      evidence_path=", ".join(created))
