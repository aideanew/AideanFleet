"""Quickstart API —— 零基础一键启动端点（免会话）。

POST /api/quickstart/create  自然语言描述 → 自动建项目 + 会话 + 计划，一步到位
GET  /api/quickstart/status   环境就绪状态（前端向导判断显示哪一步）

设计意图：小白用户不需要敲任何 CLI 命令，在浏览器里点按钮 + 输入产品想法即可。
"""

from __future__ import annotations

import hashlib
import re
import time
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from fleet.console.loopback import is_loopback as _loopback
from fleet.core.paths import paths

router = APIRouter(prefix="/api/quickstart", tags=["quickstart"])


def _forbidden():
    return JSONResponse(
        {"ok": False, "error": "只能在安装 AideanFleet 的电脑上操作", "reason": "FORBIDDEN_NON_LOOPBACK"},
        status_code=403,
    )


def _error(reason: str, message: str, status: int):
    return JSONResponse({"ok": False, "error": message, "reason": reason}, status_code=status)


# ---------------------------------------------------------------------------
# 自然语言 → 项目 ID 提取
# ---------------------------------------------------------------------------

# 从描述中提取关键词作为项目 ID
_STOP_WORDS = set("一个一种一款这个那个我想帮我帮我做开发设计实现创建搭建部署"
                  "的了吗呢吧呀哦啊是能可以需要要求功能并且和与及以".split())
# 常见产品类型关键词
_PRODUCT_KEYWORDS = [
    "todo", "待办", "任务", "chat", "聊天", "blog", "博客", "商城", "电商", "shop",
    "网站", "web", "app", "应用", "管理", "admin", "dashboard", "看板", "kanban",
    "笔记", "note", "文档", "doc", "wiki", "论坛", "forum", "搜索", "search",
    "监控", "monitor", "可视化", "图表", "chart", "游戏", "game",
]


def _extract_project_id(description: str) -> str:
    """从自然语言描述中提取项目 ID。

    策略：
    1. 先找英文关键词（todo, chat, blog 等）
    2. 再找中文关键词
    3. 都没有就用描述的 hash 前缀
    """
    desc_lower = description.lower()

    # 1. 英文关键词
    for kw in _PRODUCT_KEYWORDS:
        if kw.isascii() and kw in desc_lower:
            return f"{kw}-app"

    # 2. 中文关键词
    for kw in _PRODUCT_KEYWORDS:
        if not kw.isascii() and kw in description:
            # 转拼音太复杂，用 hash
            return f"proj-{hashlib.md5(kw.encode()).hexdigest()[:6]}"

    # 3. hash 前缀
    return f"proj-{hashlib.md5(description.encode()).hexdigest()[:8]}"


# 标点清理模式：\x22/\x27 = ASCII 双/单引号。
# （原实现的裸引号会截断 raw string、靠隐式拼接拼回，触发 SyntaxWarning，故改用转义写法）
_PUNCT_RE = re.compile(r"[，。、！？；：\x22\x27（）()\[\]{}【】《》\s]+")


def _extract_project_name(description: str) -> str:
    """从自然语言描述中提取人类可读的项目名。"""
    # 取前 20 个字符，去掉标点
    clean = _PUNCT_RE.sub(" ", description).strip()
    if len(clean) <= 20:
        return clean
    return clean[:20] + "…"


# ---------------------------------------------------------------------------
# GET /api/quickstart/status
# ---------------------------------------------------------------------------

@router.get("/status")
def quickstart_status(request: Request):
    """环境就绪状态（免会话，仅回环）。"""
    if not _loopback(request):
        return _forbidden()

    from fleet.core import db as fleet_db
    from fleet.setup import core as setup_core

    # 组件状态
    try:
        setup_status = setup_core.status()
        components = setup_status.get("components", [])
    except Exception:
        components = []

    has_python = any(c.get("name") == "python" and c.get("state") == "installed" for c in components)
    has_node = any(c.get("name") == "node" and c.get("state") == "installed" for c in components)
    has_npm = any(c.get("name") == "npm" and c.get("state") == "installed" for c in components)
    has_git = any(c.get("name") == "git" and c.get("state") == "installed" for c in components)

    # CLI 执行体
    cli_names = ["claude", "codex", "opencode", "gemini", "cline", "grok"]
    installed_clis = [c["name"] for c in components
                      if c.get("name") in cli_names and c.get("state") == "installed"]
    has_cli = len(installed_clis) > 0

    # API key → 规划器就绪单源（P3.3）
    # 字段名 has_api_key 保留（契约 quickstart.status），语义升级为 planner_status 三态判定
    # （模型 + 密钥 + 绑定一体），fleet.toml 配置的密钥不再漏检。
    try:
        from fleet.cli.clients import planner_status
        has_api_key = bool(planner_status()["ready"])
    except Exception:
        has_api_key = False

    # 已有项目
    try:
        projects = fleet_db.list_projects()
        projects_count = len(projects)
    except Exception:
        projects_count = 0

    # 前端是否已构建
    frontend_built = (paths().root / "fleet" / "console" / "dist" / "index.html").exists()

    return {
        "ok": True,
        "has_python": has_python,
        "has_node": has_node,
        "has_npm": has_npm,
        "has_git": has_git,
        "has_cli": has_cli,
        "installed_clis": installed_clis,
        "has_api_key": has_api_key,
        "has_project": projects_count > 0,
        "projects_count": projects_count,
        "frontend_built": frontend_built,
        "ready": has_python and frontend_built,
    }


# ---------------------------------------------------------------------------
# POST /api/quickstart/create
# ---------------------------------------------------------------------------

@router.post("/create")
async def quickstart_create(request: Request):
    """自然语言 → 项目 + 会话 + 计划，一步到位。

    请求体: { "description": "开发一个待办事项网页应用，能添加删除标记完成" }
    返回: { "ok", "token", "project", "project_name", "expires_in", "plan" }
    """
    if not _loopback(request):
        return _forbidden()

    try:
        body = await request.json()
    except Exception:
        return _error("VALIDATION_FAILED", "请求体必须是 JSON 对象", 422)

    description = str(body.get("description", "")).strip()
    if not description or len(description) < 3:
        return _error("VALIDATION_FAILED", "请描述你想做的产品（至少 3 个字）", 422)
    if len(description) > 20000:
        return _error("VALIDATION_FAILED", "描述过长（最多 20000 字）", 422)

    from fleet.core import db as fleet_db
    from fleet.console.server import create_session

    # 1. 生成项目 ID 和名称
    project_id = _extract_project_id(description)
    project_name = _extract_project_name(description)

    # 确保项目 ID 唯一
    base_id = project_id
    suffix = 1
    while fleet_db.get_project(project_id) is not None:
        project_id = f"{base_id}-{suffix}"
        suffix += 1

    # 2. 创建项目
    workspace = str(paths().root / project_id)
    try:
        fleet_db.create_project(
            project_id=project_id,
            name=project_name,
            path=str(paths().root),
        )
    except Exception as exc:
        return _error("CREATE_FAILED", f"创建项目失败：{exc}", 500)

    # 3. 创建会话
    token, ttl = create_session(project_id)

    # 4. 计划走 kernel 金线（P3.3）：create_goal_with_plan 同事务出 kind=plan 规划 todo。
    # 旧 intake 模板链退役：模板三阶段是假计划，不具执行意义；
    # 规划失败不阻塞——用户至少能进入控制台（plan=null，契约同前）。
    plan_result = None
    try:
        from fleet.console.kernel_api import _kernel, _slug, _workspace_roots

        workspace = str(Path(_workspace_roots()[0]) / _slug(project_name))
        goal_id, plan_todo_id = _kernel().create_goal_with_plan(
            project_name, description, workspace)
        plan_result = {
            "goal_id": goal_id,
            "plan_todo_id": plan_todo_id,
            "stages": 0,  # 计划尚未拆解：规划 todo 待 worker 认领后产出
            "tasks": 0,
        }
    except Exception:
        plan_result = None

    return {
        "ok": True,
        "token": token,
        "project": project_id,
        "project_name": project_name,
        "expires_in": ttl,
        "plan": plan_result,
    }
