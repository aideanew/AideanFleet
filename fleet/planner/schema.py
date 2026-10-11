"""这是什么：Planner 计划 JSON Schema 与校验（P2：让 Manager 变真——LLM 拆解，schema 硬校验）。
计划结构（对标方案 4.4）：
{
  "milestones": [{"id": "M1", "title": "可运行骨架"}],
  "todos": [
    {"id": "T1", "milestone": "M1", "title": "初始化 Vite + Vue", "role": "fe-1",
     "depends_on": [], "allowed_files": ["web/**", "package.json"],
     "verify": ["pnpm -C web build"], "done_when": "pnpm build 退出码 0"}
  ]
}
铁律：
- verify 必须是非空真实命令数组（禁止"文件存在即通过"类伪验收，A5）；
- id 不得重复；depends_on/milestone 引用必须存在；role 必须非空。
"""

from __future__ import annotations

import re
from typing import Any

_ID_RE = re.compile(r"^[A-Za-z0-9_\-]{1,64}$")


class PlanValidationError(ValueError):
    """计划 JSON 不符合 schema。"""


def validate_plan(data: Any) -> dict[str, Any]:
    """校验并归一化计划；不合法抛 PlanValidationError（消息面向 LLM 重试与用户可读）。"""
    if not isinstance(data, dict):
        raise PlanValidationError("计划必须是 JSON 对象")
    milestones = data.get("milestones")
    todos = data.get("todos")
    if not isinstance(milestones, list) or not milestones:
        raise PlanValidationError("milestones 必须是非空数组")
    if not isinstance(todos, list) or not todos:
        raise PlanValidationError("todos 必须是非空数组")

    milestone_ids: set[str] = set()
    for index, m in enumerate(milestones):
        if not isinstance(m, dict) or not isinstance(m.get("id"), str) or not isinstance(m.get("title"), str):
            raise PlanValidationError(f"milestones[{index}] 需要 id/title 字符串字段")
        if not _ID_RE.match(m["id"]):
            raise PlanValidationError(f"milestones[{index}].id 非法: {m['id']!r}")
        if m["id"] in milestone_ids:
            raise PlanValidationError(f"milestone id 重复: {m['id']}")
        milestone_ids.add(m["id"])

    todo_ids: set[str] = set()
    clean_todos: list[dict[str, Any]] = []
    for index, t in enumerate(todos):
        if not isinstance(t, dict):
            raise PlanValidationError(f"todos[{index}] 必须是对象")
        tid, title = t.get("id"), t.get("title")
        if not isinstance(tid, str) or not _ID_RE.match(tid):
            raise PlanValidationError(f"todos[{index}].id 非法: {tid!r}")
        if tid in todo_ids:
            raise PlanValidationError(f"todo id 重复: {tid}")
        if not isinstance(title, str) or not title.strip():
            raise PlanValidationError(f"todos[{index}] ({tid}) 缺有效 title")
        role = str(t.get("role") or "").strip()
        if not role:
            raise PlanValidationError(f"todos[{index}] ({tid}) 缺 role（执行角色）")
        milestone = t.get("milestone")
        if milestone is not None and (not isinstance(milestone, str) or milestone not in milestone_ids):
            raise PlanValidationError(f"todos[{index}] ({tid}) 的 milestone {milestone!r} 未在 milestones 中定义")
        verify = t.get("verify")
        if not isinstance(verify, list) or not verify or not all(
            isinstance(c, str) and c.strip() for c in verify
        ):
            raise PlanValidationError(
                f"todos[{index}] ({tid}) 的 verify 必须是非空命令数组（A5：完成必须可信）"
            )
        for cmd in verify:
            lowered = cmd.strip().lower()
            if lowered.startswith("python -c") and ".exists()" in lowered:
                raise PlanValidationError(
                    f"todos[{index}] ({tid}) 的 verify 是文件存在性伪验收（A5 禁止）: {cmd!r}"
                )
        allowed = t.get("allowed_files", [])
        if isinstance(allowed, str):
            allowed = [item.strip() for item in allowed.split(",") if item.strip()]
        if not isinstance(allowed, list) or not allowed:
            raise PlanValidationError(f"todos[{index}] ({tid}) 缺 allowed_files 白名单")
        deps = t.get("depends_on", [])
        if not isinstance(deps, list) or not all(isinstance(d, str) for d in deps):
            raise PlanValidationError(f"todos[{index}] ({tid}) 的 depends_on 必须是字符串数组")
        todo_ids.add(tid)
        clean_todos.append({
            "id": tid,
            "milestone": milestone or "",
            "title": title.strip(),
            "role": role,
            "depends_on": list(deps),
            "allowed_files": [str(a) for a in allowed],
            "verify": [str(c).strip() for c in verify],
            "done_when": str(t.get("done_when") or "").strip(),
        })

    for t in clean_todos:
        for dep in t["depends_on"]:
            if dep not in todo_ids:
                raise PlanValidationError(f"todo {t['id']} 依赖不存在的 {dep}")
    # 依赖不得成环（简单 DFS）
    by_id = {t["id"]: t for t in clean_todos}
    visiting: set[str] = set()
    done: set[str] = set()

    def _visit(tid: str) -> None:
        if tid in done:
            return
        if tid in visiting:
            raise PlanValidationError(f"依赖成环: {tid}")
        visiting.add(tid)
        for dep in by_id[tid]["depends_on"]:
            _visit(dep)
        visiting.discard(tid)
        done.add(tid)

    for t in clean_todos:
        _visit(t["id"])

    return {
        "milestones": [
            {"id": m["id"], "title": m["title"]} for m in milestones
        ],
        "todos": clean_todos,
    }
