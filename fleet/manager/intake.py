"""这是什么：Manager 项目启动器（intake）——把对话指令转成可派工的真实项目。
怎么用：from fleet.manager import intake
        intent = intake.detect_launch_intent(message)   # (pid, workspace) | None
        mode = intake.detect_mode(message)              # 'auto' | 'step' | None
        intake.start_project(pid, pid, workspace, message, default_adapter="")
要点：
- 计划先行：先定三级计划与任务边界，再谈实现；目录/文件结构以计划为准；
- requirements 全文进入每个任务的 detail，执行体不得自行扩大范围；
- 阶段内任务并行（无互相依赖），阶段间串行（依赖前阶段全部任务）；
- default_adapter 供测试注入 FakeAdapter；生产留空走角色配置。
"""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

from ..core import db
from ..core import plan as plan_mod
from . import dispatcher
from .contracts import TaskPack

_LAUNCH_PATTERNS = [
    # Windows 驱动器路径：E:\Demo\Project  或  E:/Demo/Project
    re.compile(
        r"启动新项目\s*[：:]?\s*([A-Za-z0-9_\-\u4e00-\u9fa5]+)\s*[（(]?\s*工作区?\s*[：:]?\s*"
        r"([A-Za-z]:[\\/][^）)\r\n]*)"
    ),
    # Linux/Unix 绝对路径：/home/user/project
    re.compile(
        r"启动新项目\s*[：:]?\s*([A-Za-z0-9_\-\u4e00-\u9fa5]+)\s*[（(]?\s*工作区?\s*[：:]?\s*"
        r"(/[\w.\-/]+)"
    ),
    re.compile(
        r"project\s*[:：]\s*([A-Za-z0-9_\-]+)[\s\S]{0,160}?([A-Za-z]:\\(?:[\w.\-]+\\)+[\w.\-]+)",
        re.IGNORECASE,
    ),
]


def _allowed_roots() -> list[str]:
    """ALLOWED_ROOTS 白名单：.env basic 段优先，回退系统环境变量。"""
    from ..core import config as fleet_config

    try:
        cfg = fleet_config.load("basic") or {}
        raw = cfg.get("allowed_roots", "")
    except Exception:
        raw = ""
    roots: list[str] = []
    if isinstance(raw, list):
        roots = [str(r) for r in raw if str(r).strip()]
    elif isinstance(raw, str) and raw.strip():
        roots = [r.strip() for r in raw.split(",") if r.strip()]
    if not roots:
        env_roots = os.environ.get("FLEET_ALLOWED_ROOTS", "")
        roots = [r.strip() for r in env_roots.split(",") if r.strip()]
    return roots


def _workspace_allowed(workspace: str) -> bool:
    norm = os.path.normpath(workspace.rstrip("\\/")).lower()
    for root in _allowed_roots():
        root_norm = os.path.normpath(root.rstrip("\\/")).lower()
        sep = os.sep
        if norm == root_norm or norm.startswith(root_norm + sep):
            return True
    return False


def detect_launch_intent(message: str) -> tuple[str, str] | None:
    """识别“启动新项目”指令：返回 (项目id, 工作区路径)；工作区缺省时从 ALLOWED_ROOTS 推导。"""
    for pattern in _LAUNCH_PATTERNS:
        match = pattern.search(message or "")
        if not match:
            continue
        pid = re.sub(r"[^A-Za-z0-9_\-]", "", match.group(1))
        workspace = os.path.normpath((match.group(2) or "").strip().rstrip("\\/"))
        if not pid:
            continue
        if not workspace:
            roots = _allowed_roots()
            if not roots:
                return pid, ""
            workspace = os.path.join(roots[0].rstrip("\\/"), pid)
        return pid, workspace
    return None


def detect_mode(message: str) -> str | None:
    """从消息中识别执行模式意图（auto/step）；未提及返回 None。"""
    text = message or ""
    if re.search(r"自动执行|\bauto\b", text, re.IGNORECASE):
        return "auto"
    if re.search(r"每步确认|\bstep\b", text, re.IGNORECASE):
        return "step"
    return None


def _plan_templates(requirements: str) -> list[tuple[str, list[dict[str, str]]]]:
    """默认三级计划模板：技术设计 → 核心实现（并行） → 测试验收。requirements 全文入 detail。"""
    brief = (requirements or "").strip() or "（需求未提供，按项目名合理设计）"
    verify_doc = 'python -c "import pathlib,sys; sys.exit(0 if pathlib.Path(\'docs/design.md\').exists() else 1)"'
    verify_build = ('python -c "import pathlib,sys; sys.exit(0 if any(pathlib.Path(p).exists() '
                    "for p in ('index.html','src/main.ts','src/main.js','src/main.py','src','game')) else 1)\"")

    def detail(responsibility: str, done: str) -> str:
        return (
            f"【总体需求】\n{brief}\n\n"
            f"【本任务职责】{responsibility}\n\n"
            f"【完成定义】{done}\n\n"
            "【边界】只在工作区内改动；目录结构以三级计划为准，创建前先核对计划；"
            "执行命令前确认实际 shell；路径使用带引号的正斜杠格式，禁止裸反斜杠路径。"
        )

    return [
        ("技术设计", [
            {
                "subtask": "架构设计文档",
                "title": "调研·架构设计·技术文档",
                "detail": detail(
                    "自行搜索相关资料，完成技术选型、模块划分与目录结构设计，写入 docs/design.md。",
                    "docs/design.md 存在且含技术选型与目录结构说明",
                ),
                "verify_cmd": verify_doc,
                "assignee": "manager",
                "reviewer": "reviewer-1",
            },
        ]),
        ("核心实现", [
            {
                "subtask": "核心引擎与业务逻辑",
                "title": "核心引擎·实体·业务逻辑实现",
                "detail": detail(
                    "按设计文档实现核心引擎、实体与业务逻辑（含可运行主入口）。",
                    "主入口（index.html / src/main.* / src/）存在且可启动",
                ),
                "verify_cmd": verify_build,
                "assignee": "be-1",
                "reviewer": "reviewer-1",
            },
            {
                "subtask": "界面·渲染·交互实现",
                "title": "界面·渲染·交互实现",
                "detail": detail(
                    "按设计文档实现界面、渲染与交互层，与核心引擎对接。",
                    "界面/渲染代码就位并与核心引擎对接",
                ),
                "verify_cmd": verify_build,
                "assignee": "fe-1",
                "reviewer": "reviewer-1",
            },
        ]),
        ("测试验收", [
            {
                "subtask": "集成联调与缺陷修复",
                "title": "集成联调·端到端验证·缺陷修复",
                "detail": detail(
                    "对前序任务产出做集成联调与端到端验证，发现缺陷直接修复并回归。",
                    "端到端流程可跑通，已知缺陷清零或如实登记",
                ),
                "verify_cmd": verify_build,
                "assignee": "be-2",
                "reviewer": "reviewer-1",
            },
            {
                "subtask": "终局验收与完成度表",
                "title": "终局验收·完成度表·交付报告",
                "detail": detail(
                    "终局验收：核对总体需求逐条达成，输出完成度表（角色/平台/模型/任务/评分）与交付报告。",
                    "验收报告与完成度表落盘",
                ),
                "verify_cmd": verify_build,
                "assignee": "reviewer-1",
                "reviewer": "reviewer-1",
            },
        ]),
    ]


def start_project(
    pid: str,
    name: str,
    workspace: str,
    requirements: str,
    *,
    default_adapter: str = "",
    db_file: str | Path | None = None,
) -> dict[str, Any]:
    """对话驱动项目启动：注册项目 → 三级计划 → DRAFT 任务建册。

    计划先行：先定三级计划与任务边界（本函数），目录/文件由执行体按计划创建。
    阶段内任务并行（无互相依赖），阶段间串行（依赖前阶段全部任务）。
    """
    pid = re.sub(r"[^A-Za-z0-9_\-]", "", pid or "")
    if not pid:
        raise ValueError("项目名不能为空")
    workspace = os.path.normpath((workspace or "").strip().rstrip("\\/"))
    if not workspace:
        roots = _allowed_roots()
        if not roots:
            raise ValueError("ALLOWED_ROOTS 未配置，无法推导工作区")
        workspace = os.path.join(roots[0].rstrip("\\/"), pid)
    if not _workspace_allowed(workspace):
        allowed = ", ".join(_allowed_roots()) or "未配置"
        raise ValueError(f"工作区 {workspace} 不在 ALLOWED_ROOTS 内（允许：{allowed}）")

    # CLI 使用 P-xxx 注册；对话以项目名启动时复用相同名称与工作区的记录。
    for project in db.list_projects(db_file=db_file):
        if (project.get("name") == (name or pid)
                and Path(project["path"]).resolve() == Path(workspace).resolve()):
            pid = project["project_id"]
            break

    if not db.create_project(pid, name or pid, workspace, port=None, db_file=db_file):
        raise RuntimeError(f"项目 {pid} 注册失败")

    # 幂等防护：项目已建册过则不重复建任务（重复指令只补拉调度循环）
    existing_tasks = db.list_tasks(pid, db_file=db_file)
    if existing_tasks:
        return {"project": pid, "workspace": workspace, "stages": 0,
                "tasks": len(existing_tasks), "already": True, "created": []}

    data = plan_mod.empty_plan(pid)
    data["title"] = name or pid
    plan_mod.save(pid, data)

    requirements = (requirements or "").strip()
    created: list[dict[str, Any]] = []
    stage_count = 0
    global_seq = 0
    prev_stage_ids: list[str] = []
    for stage_name, specs in _plan_templates(requirements):
        stage_count += 1
        stage_ids: list[str] = []
        for spec in specs:
            global_seq += 1
            pack = TaskPack(
                id=f"{pid}-T{global_seq:02d}",
                title=spec["title"],
                detail=spec["detail"],
                verify_cmd=spec["verify_cmd"],
                assignee=spec["assignee"],
                reviewer=spec["reviewer"],
                workspace=workspace,
                allowed_files="",
                forbidden_files="",
                project_id=pid,
                adapter=default_adapter,
                stage=stage_name,
                subtask=spec["subtask"],
            )
            row = dispatcher.create_task(
                pack,
                project_id=pid,
                stage=stage_name,
                subtask=spec["subtask"],
                dependencies=list(prev_stage_ids),
                db_file=db_file,
            )
            stage_ids.append(pack.id)
            created.append(row)
        prev_stage_ids = stage_ids

    return {
        "project": pid,
        "workspace": workspace,
        "stages": stage_count,
        "tasks": len(created),
        "created": created,
    }
