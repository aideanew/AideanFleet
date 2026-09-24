"""这是什么：AideanFleet 控制台服务（FastAPI + WebSocket 重建版，角色A · CORE-02）。
怎么用：python fleet/console/server.py  ->  http://127.0.0.1:5000 ；uvicorn.run(app) 亦可。
兼容：旧路由字段名全部保留（含 GBK 请求体回退、cookie fleet_token 回退、dist/→static/ 双目录）；
     新增 WS（7 种服务端消息 / 3 种客户端消息）、/api/control/confirm、/api/tasks、/tasks/dispatch。
会话：内存 token，有效期 FLEET_SESSION_EXPIRE_SECONDS > basic.lock_ttl_minutes*60 > 旧 lock_screen_seconds。
"""

from __future__ import annotations

import asyncio
import json
import os
import secrets as pysecrets
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse

from fleet.core import config as fleet_config
from fleet.core import db, events, plan
from fleet.core import state_machine as sm
from fleet.core.paths import paths
from fleet.manager import dispatcher, intake, rework_manager, scheduler
from fleet.governance import ApprovalManager, BudgetManager, UsageAggregator

VERSION = "0.3.0"  # REL-01：版本统一（pyproject.toml 同步）

HOST = os.environ.get("FLEET_CONSOLE_HOST", "127.0.0.1")
PORT = int(os.environ.get("FLEET_CONSOLE_PORT", "5000"))

CONSOLE_DIR = Path(__file__).resolve().parent
DIST_DIR = CONSOLE_DIR / "dist"
STATIC_DIR = CONSOLE_DIR / "static"

_START_TIME = time.time()
app = FastAPI(title="AideanFleet Console", version=VERSION)

#: 调度总线：控制台（HTTP/WS）写模式与确认，run_loop 消费
#: 初始模式可经 .env 的 FLEET_SCHEDULER_MODE 恢复（服务重启后内存态丢失，用户口径 auto 时配置 auto）
bus = scheduler.ControlBus(
    fleet_config.env_setting("FLEET_SCHEDULER_MODE", os.environ.get("FLEET_SCHEDULER_MODE", "step"))
)

#: 对话启动的项目 → 常驻调度循环去重集合
_active_loops: set[str] = set()
_loops_lock = threading.Lock()

#: 常驻调度循环默认关闭（FLEET_SCHEDULER=1 打开）。顶层键不进 os.environ（config.py:279），
#: .env 里写 FLEET_SCHEDULER=1 必须经 env_setting 读取，否则重启恢复静默关闭（实测断链根因）。
#: 进程级 FLEET_SCHEDULER=0 强制关闭，优先于 .env。
_SCHEDULER_ENABLED = (
    os.environ.get("FLEET_SCHEDULER") != "0"
    and (os.environ.get("FLEET_SCHEDULER") == "1" or fleet_config.env_setting("FLEET_SCHEDULER") == "1")
)


# ---------------------------------------------------------------------------
# 会话（内存）
# ---------------------------------------------------------------------------

_sessions: dict[str, dict[str, Any]] = {}
_sessions_lock = threading.Lock()


def session_expire_seconds() -> int:
    """会话有效期：环境变量 > .env basic.lock_ttl_minutes*60 > 旧 lock_screen_seconds > 3600。"""
    env_value = os.environ.get("FLEET_SESSION_EXPIRE_SECONDS")
    if env_value and env_value.strip().isdigit():
        return max(1, int(env_value))
    try:
        minutes = int(fleet_config.load("basic").get("lock_ttl_minutes") or 0)
        if minutes > 0:
            return minutes * 60
    except fleet_config.ConfigError:
        pass
    raw = fleet_config.raw()
    for legacy_key in ("FLEET_LOCK_SCREEN_SECONDS", "FLEET_LOCK_TTL_MINUTES"):
        if raw.get(legacy_key, "").strip().isdigit():
            value = int(raw[legacy_key])
            return max(1, value if legacy_key.endswith("SECONDS") else value * 60)
    return 3600


def create_session(project_id: str) -> tuple[str, int]:
    token = pysecrets.token_hex(16)
    ttl = session_expire_seconds()
    with _sessions_lock:
        _sessions[token] = {"project": project_id, "expires_at": time.time() + ttl}
    return token, ttl


def check_session(token: str) -> dict[str, Any] | None:
    with _sessions_lock:
        session = _sessions.get(token)
        if not session:
            return None
        if session["expires_at"] < time.time():
            _sessions.pop(token, None)
            return None
        return dict(session)


def destroy_session(token: str) -> None:
    with _sessions_lock:
        _sessions.pop(token, None)


def token_of(request: Request) -> str:
    """取会话令牌：Authorization Bearer > cookie fleet_token > ?token=（兼容三层）。"""
    auth = request.headers.get("authorization", "")
    if auth.startswith("Bearer "):
        return auth[7:].strip()
    cookie = request.headers.get("cookie", "")
    for part in cookie.split(";"):
        part = part.strip()
        if part.startswith("fleet_token="):
            return part[len("fleet_token="):].strip()
    return str(request.query_params.get("token") or "")


async def json_body(request: Request) -> dict[str, Any]:
    """解析请求体：utf-8 优先，失败回退 GBK（兼容 Windows 终端/旧客户端中文请求体）。"""
    raw = await request.body()
    if not raw:
        return {}
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        text = raw.decode("gbk", errors="replace")
    try:
        data = json.loads(text)
        return data if isinstance(data, dict) else {}
    except ValueError:
        raise BodyDecodeError()


class BodyDecodeError(Exception):
    """请求体不是合法 JSON 对象。"""


# ---------------------------------------------------------------------------
# WebSocket 连接管理与事件泵
# ---------------------------------------------------------------------------

_connections: set[WebSocket] = set()
_connections_lock = threading.Lock()
_connections_project: dict[WebSocket, str] = {}
_connections_token: dict[WebSocket, str] = {}
_loop: asyncio.AbstractEventLoop | None = None
_pump_task: asyncio.Task | None = None
_pump_state = {"cursor": 0, "plan_mtimes": {}, "config_mtime": None}


def _broadcast_targets(payload: dict[str, Any]) -> list[WebSocket]:
    """按 payload.project 计算目标连接（纯函数，便于单测）。

    规则：无 project 的消息（config_changed 等全局状态）发给所有连接；
    带 project 的消息只发给绑定了该项目的连接（未绑定连接不收定向消息，防反向泄漏）。
    """
    target_project = payload.get('project')
    with _connections_lock:
        sockets = list(_connections)
    if not target_project:
        return sockets
    return [s for s in sockets if _connections_project.get(s) == target_project]


def broadcast(payload: dict[str, Any]) -> None:
    """把一条服务端消息推给所有 WS 连接（线程安全；无连接/无事件循环时静默丢弃）。按 project 过滤"""
    loop = _loop
    if loop is None:
        return
    text = json.dumps(payload, ensure_ascii=False)
    for socket in _broadcast_targets(payload):
        asyncio.run_coroutine_threadsafe(_ws_send(socket, text), loop)


async def _ws_send(socket: WebSocket, text: str) -> None:
    try:
        await socket.send_text(text)
    except Exception:
        with _connections_lock:
            _connections.discard(socket)


def _map_action_to_type(action: str) -> str:
    """事件 action -> WS 消息类型（7 种之一；兜底 notification）。"""
    if action in ("chat", "chat_reply"):
        return "chat_message"
    if action == "mode:changed":
        return "notification"
    if action.startswith(("task:", "gate:", "task:deferred")):
        return "task_update"
    if action.startswith("launch:"):
        return "progress"
    if action.startswith("config"):
        return "config_changed"
    return "notification"


def _progress_of(project_id: str) -> dict[str, Any]:
    """项目进度（需求3 单口径）：plan.json 权重树 × SQLite 状态，叶子权重和恒=100。

    旧行为保持：无显式"权重"字段时权重树退化为等权，percent 与旧版 done/total 完全一致。
    新增 stages 子树（阶段/任务的 weight_pct / contrib_pct），WS progress 直接携带。
    """
    return {"project": project_id, **plan.project_progress(project_id)}


def _event_broadcast_payload(row: dict[str, Any]) -> dict[str, Any] | None:
    """事件行 → WS 广播消息；返回 None 表示不广播。

    项目归属守卫（缺陷③）：无法归属到项目的任务/对话类事件（task_update /
    chat_message）推给所有连接就是把 A 项目的任务完成/对话内容泄漏进 B 项目，
    直接跳过。全局事件（mode:changed / config / rel 系统事件）保持全员广播。
    """
    msg_type = _map_action_to_type(str(row.get("action") or ""))
    row_project = str(row.get("project") or "")
    if not row_project and msg_type in ("task_update", "chat_message"):
        return None
    return {"type": msg_type, "project": row_project, "event": row}


async def _event_pump() -> None:
    """每秒一拍：新事件 -> WS 消息；plan.json 变化 -> plan_update + progress；.env 变化 -> config_changed。"""
    if _pump_state["cursor"] == 0:
        _pump_state["cursor"] = events.max_seq()
    while True:
        try:
            fresh = events.read(since=_pump_state["cursor"])
            for row in fresh:
                _pump_state["cursor"] = max(_pump_state["cursor"], int(row.get("seq") or 0))
                payload = _event_broadcast_payload(row)
                if payload is not None:
                    broadcast(payload)
                if row.get("project"):
                    broadcast({"type": "progress", **_progress_of(str(row["project"]))})
            for project_row in db.list_projects():
                pid = project_row["project_id"]
                target = plan.plan_file(pid)
                mtime = target.stat().st_mtime_ns if target.exists() else 0
                if _pump_state["plan_mtimes"].get(pid) != mtime:
                    _pump_state["plan_mtimes"][pid] = mtime
                    if mtime:
                        broadcast({"type": "plan_update", "project": pid, "plan": plan.snapshot(pid)})
                        broadcast({"type": "progress", **_progress_of(pid)})
            env_mtime = fleet_config.env_mtime()
            if _pump_state["config_mtime"] not in (None, env_mtime):
                broadcast({"type": "config_changed", "mtime": env_mtime})
            _pump_state["config_mtime"] = env_mtime
        except Exception:
            pass
        await asyncio.sleep(1.0)


# ---------------------------------------------------------------------------
# 中间件：会话闸门（/api/health、/api/session、/api/launch-resolve、静态页豁免）
# ---------------------------------------------------------------------------

_EXEMPT_PATHS = {"/api/health", "/api/session", "/api/projects/names", "/api/launch-resolve", "/api/launch-event"}
# launch-event 豁免会话：契约 docs/契约/控制台API.md §4 与 派工3 T5/T6 要求启动器（Hermes/CLI）
# 不带 token 直接 POST；仅监听 127.0.0.1，事件写入前仍过 events.scrub 脱敏。
# projects/names 豁免：锁屏候选列表（只含 id/name，无敏感字段）。


@app.middleware("http")
async def session_gate(request: Request, call_next):
    path = request.url.path
    if path not in _EXEMPT_PATHS and path.startswith("/api/"):
        session = check_session(token_of(request))
        if not session:
            return JSONResponse(
                {"ok": False, "error": "会话无效或已过期，请重新输入项目名解锁", "reason": "unauthorized"},
                status_code=401,
            )
        request.state.session = session
    return await call_next(request)


# ---------------------------------------------------------------------------
# 健康与会话路由
# ---------------------------------------------------------------------------


def _db_alive() -> bool:
    try:
        with sqlite3.connect(f"file:{paths().db_file}?mode=ro", uri=True) as conn:
            names = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            return {"tasks", "projects"} <= names
    except (sqlite3.Error, OSError):
        return False


def _config_alive() -> bool:
    try:
        fleet_config.raw()
        return True
    except Exception:
        return False


@app.get("/api/health")
def api_health() -> dict[str, Any]:
    """契约 §1：返回体恰好四个键 version/db/events/config。"""
    return {"version": VERSION, "db": _db_alive(), "events": events.health(), "config": _config_alive()}


@app.post("/api/session")
async def api_session_create(request: Request):
    try:
        data = await json_body(request)
    except BodyDecodeError:
        return JSONResponse({"ok": False, "error": "请求体必须是 JSON 对象"}, status_code=400)
    project = str(data.get("project", "")).strip()
    if not project:
        return JSONResponse({"ok": False, "error": "请输入项目名"}, status_code=400)
    # 项目身份解析：project_id（P-xxx）或项目名（如 Test09171500）均可解锁，
    # 会话统一记录规范化后的 project_id，杜绝后续按 name 查不到。
    row = db.find_project(project)
    if row is None:
        return JSONResponse({"ok": False, "error": "项目不存在，请检查项目名是否正确"}, status_code=400)
    pid = row["project_id"]
    token, ttl = create_session(pid)
    response = JSONResponse({"ok": True, "token": token, "project": pid, "expires_in": ttl})
    response.set_cookie("fleet_token", token, max_age=ttl, httponly=False, samesite="lax")
    return response


@app.post("/api/session/switch")
async def api_session_switch(request: Request):
    """切换当前会话绑定的项目（TopBar 下拉/对话启动新项目共用）。"""
    try:
        data = await json_body(request)
    except BodyDecodeError:
        return JSONResponse({"ok": False, "error": "请求体必须是 JSON 对象"}, status_code=400)
    session = check_session(token_of(request))
    if not session:
        return JSONResponse({"ok": False, "error": "会话无效或已过期"}, status_code=401)
    project = str(data.get("project", "")).strip()
    row = db.find_project(project) if project else None
    if row is None:
        return JSONResponse({"ok": False, "error": "项目不存在，请检查项目名是否正确"}, status_code=400)
    pid = row["project_id"]
    with _sessions_lock:
        sess = _sessions.get(token_of(request))
        if sess:
            sess["project"] = pid
    events.append(actor="用户", action="session:switch", summary=f"切换项目 → {pid}", project=pid)
    # 更新已连接的 WS 项目映射并广播切换通知
    token = token_of(request)
    with _connections_lock:
        for ws, tok in list(_connections_token.items()):
            if tok == token:
                _connections_project[ws] = pid
    broadcast({"type": "notification", "project": pid, "session_switch": True})
    return {"ok": True, "project": pid, "expires_in": max(0, int(session["expires_at"] - time.time()))}


@app.get("/api/session")
async def api_session_get(request: Request):
    session = getattr(request.state, "session", None) or check_session(token_of(request))
    if not session:
        return JSONResponse({"ok": False, "error": "会话无效或已过期"}, status_code=401)
    return {"ok": True, "project": session["project"], "expires_in": max(0, int(session["expires_at"] - time.time()))}


@app.delete("/api/session")
async def api_session_delete(request: Request):
    destroy_session(token_of(request))
    return {"ok": True}


@app.get("/api/projects")
def api_projects(request: Request):
    """已注册项目列表（切换项目/锁屏候选用；会话保护，未解锁不外泄项目名）。"""
    rows = db.list_projects()
    return {"ok": True, "projects": [
        {"id": row["project_id"], "name": row.get("name") or row["project_id"],
         "path": row.get("path") or "", "port": row.get("port")} for row in rows]}


@app.get("/api/projects/names")
def api_project_names():
    """锁屏候选：免会话（服务仅监听 127.0.0.1），只暴露 id 与 name，不含路径等敏感字段。"""
    rows = db.list_projects()
    return {"ok": True, "projects": [
        {"id": row["project_id"], "name": row.get("name") or row["project_id"]} for row in rows]}


@app.get("/api/mode")
def api_mode_get():
    """当前调度模式与是否在等人工确认（前端每次进入/切换项目时拉一次）。"""
    return {"ok": True, "mode": bus.mode, "awaiting_confirm": bus.awaiting_confirm}


# ---------------------------------------------------------------------------
# 计划 / 事件 / 启动上报
# ---------------------------------------------------------------------------


def _run_started_at(pid: str) -> str | None:
    """项目执行起点：事件流中第一条任务类事件的时间（未开始则为 None）"""
    try:
        for row in events.read(pid, since=0):
            if str(row.get("action") or "").startswith(("task:", "launch:")):
                return str(row.get("timestamp") or "") or None
    except Exception:
        return None
    return None


@app.get("/api/plan")
def api_plan(request: Request, project: str | None = None):
    session = request.state.session
    pid = str(project or session["project"])
    if db.get_project(pid) is None:
        return JSONResponse({"ok": False, "reason": "project_not_found", "project": pid}, status_code=200)
    snapshot = plan.snapshot(pid)
    progress = _progress_of(pid)
    # 旧前端兼容字段（progress/total/done/percent）与契约快照字段并列返回
    return {"ok": True, **snapshot, "run_started_at": _run_started_at(pid),
            "progress": progress, "total": progress["total"],
            "done": progress["done"], "percent": progress["percent"]}


@app.get("/api/events")
def api_events(request: Request, project: str | None = None, since: str = "0"):
    session = request.state.session
    pid = str(project or session["project"])
    try:
        cursor = int(float(since or "0"))
    except ValueError:
        return JSONResponse({"ok": False, "error": "since 参数必须是数字"}, status_code=400)
    rows = events.read(pid, since=cursor)
    return {"ok": True, "project": pid, "since": cursor, "seq": events.current_cursor(pid), "events": rows}


@app.get("/api/launch-resolve")
def api_launch_resolve(project: str = "", mode: str = ""):
    """启动解析（豁免会话）：未知项目 200 + ok=false，绝不用 404/HTML 表达业务态。"""
    if db.get_project(project) is None:
        return JSONResponse({"ok": False, "reason": "project_not_found", "missing": ["project"]}, status_code=200)
    missing = [] if mode in ("BOOT", "RUN") else ["mode"]
    return {"ok": True, "mode": mode or "BOOT", "ui_url": f"http://{HOST}:{PORT}/?project={project}",
            "profile_source": str(fleet_config.env_source()), "missing": missing}


@app.post("/api/launch-event")
async def api_launch_event(request: Request):
    try:
        data = await json_body(request)
    except BodyDecodeError:
        return JSONResponse({"ok": False, "reason": "invalid_json", "missing": []}, status_code=400)
    required = ["project", "phase", "detail"]
    missing = [key for key in required if not str(data.get(key) or "").strip()]
    if missing:
        return JSONResponse({"ok": False, "reason": "missing_fields", "missing": missing}, status_code=400)
    pid = str(data["project"])
    if db.get_project(pid) is None:
        return JSONResponse({"ok": False, "reason": "project_not_found", "project": pid}, status_code=200)
    extra: dict[str, Any] = {}
    for key in ("cli", "model", "percent", "phase"):
        if data.get(key) not in (None, ""):
            extra[key] = data[key]
    row = events.append(
        actor=str(data.get("role") or "launcher"),
        action="launch:" + str(data["phase"]),
        task_id=str(data.get("taskId")) or None,
        summary=str(data["detail"]),
        url=str(data.get("url")) or None,
        project=pid,
        extra=extra or None,
    )
    return {"ok": True, "seq": row["seq"], "action": row["action"], "taskId": row["taskId"], "url": row["url"]}


# ---------------------------------------------------------------------------
# 模式 / 确认 / 对话（含 /api/control/confirm 人工放行）
# ---------------------------------------------------------------------------


def _normalize_mode(mode: str) -> str:
    """旧值 confirm = 新值 step（每步确认）。"""
    return "step" if str(mode).strip().lower() == "confirm" else str(mode).strip().lower()


@app.post("/api/mode")
async def api_mode(request: Request):
    try:
        data = await json_body(request)
    except BodyDecodeError:
        return JSONResponse({"ok": False, "error": "请求体必须是 JSON 对象"}, status_code=400)
    mode = _normalize_mode(str(data.get("mode", "")))
    if mode not in scheduler.MODES:
        return JSONResponse({"ok": False, "error": "mode 只能为 confirm/step（每步确认）或 auto（自动执行）"}, status_code=400)
    bus.set_mode(mode, actor=str(data.get("actor") or "用户"))
    return {"ok": True, "mode": data.get("mode") or mode, "effective": mode}


@app.post("/api/confirm")
async def api_confirm(request: Request):
    """旧路由：每步确认模式下的人工确认/意见（同时喂给调度总线）。"""
    try:
        data = await json_body(request)
    except BodyDecodeError:
        return JSONResponse({"ok": False, "error": "请求体必须是 JSON 对象"}, status_code=400)
    session = request.state.session
    project = str(data.get("project", session["project"]))
    note = str(data.get("note", "")).strip()
    decision = str(data.get("decision", "confirm")).strip()
    if decision not in ("confirm", "note"):
        return JSONResponse({"ok": False, "error": "decision 只能为 confirm（确认）或 note（意见）"}, status_code=400)
    if decision == "confirm" and not note:
        summary = "用户确认当前步骤"
    elif not note:
        return JSONResponse({"ok": False, "error": "意见内容不能为空"}, status_code=400)
    else:
        summary = "用户意见：" + note
    bus.confirm(task_id=str(data.get("taskId")) or None, actor="用户", note=note)
    row = events.append(actor="用户", action="step_confirm", task_id=str(data.get("taskId")) or None,
                        summary=summary, project=project)
    return {"ok": True, "event": row}


@app.post("/api/control/confirm")
async def api_control_confirm(request: Request):
    """新路由：人工放行。ESCALATED -> 后继任务；BLOCKED/REWORK -> 重派；其余 -> 步进确认。"""
    try:
        data = await json_body(request)
    except BodyDecodeError:
        return JSONResponse({"ok": False, "error": "请求体必须是 JSON 对象"}, status_code=400)
    task_id = str(data.get("taskId") or data.get("task_id") or "").strip()
    note = str(data.get("note") or data.get("message") or "").strip()
    if not task_id:
        return JSONResponse({"ok": False, "error": "缺少 taskId"}, status_code=400)
    task = db.get_task(task_id)
    if task is None:
        return JSONResponse({"ok": False, "reason": "task_not_found", "taskId": task_id}, status_code=200)

    state = task["exec_status"]
    if state == "ESCALATED":
        result = rework_manager.confirm_release(task_id, actor="用户", note=note)
        return {"ok": True, **result}
    if state == "REWORK":
        result = rework_manager.redispatch(task_id, actor="用户", reason=note or None)
        return {"ok": bool(result.get("ok")), "taskId": task_id, "state": result.get("state"),
                "detail": result.get("detail")}
    if state == "BLOCKED":
        db.transition_and_log(task_id, "ASSIGNED", actor="用户",
                              summary=f"{task_id} 人工放行（BLOCKED -> ASSIGNED）" + (f"：{note[:120]}" if note else ""),
                              action="task:blocked_release", extra={"note": note[:500]}, blocked_reason="", remark="")
        # dispatch 含最长 timeout_seconds 的子进程等待，绝不能在事件循环线程里同步执行
        # （否则整个控制台 HTTP/WS 全部停摆）；转后台线程，立即返回已落库的 ASSIGNED。
        def _redispatch(tid: str = task_id) -> None:
            task = db.get_task(tid)
            proj = task.get("project_id") if task else ""
            result = dispatcher.dispatch(tid, actor="用户")
            broadcast({"type": "task_update", "project": proj, "taskId": tid, "state": result.state})
        threading.Thread(target=_redispatch, daemon=True, name=f"redispatch-{task_id}").start()
        return {"ok": True, "taskId": task_id, "state": "ASSIGNED", "detail": "已放行，后台重新派工中"}

    # 运行中的任务：按步进确认处理
    bus.confirm(task_id=task_id, actor="用户", note=note)
    row = events.append(actor="用户", action="step_confirm", task_id=task_id,
                        summary=note or f"用户确认 {task_id} 当前步骤", project=task.get("project_id"))
    return {"ok": True, "event": row}


def _process_chat(session: dict[str, Any], project: str, message: str) -> dict[str, Any]:
    """统一对话处理：识别“启动新项目”指令 → intake 注册项目/三级计划/任务建册 → 常驻调度接管；
    普通消息原样回执。返回 {"reply", "new_project"}。"""
    intent = intake.detect_launch_intent(message)
    if not intent:
        reply = (f"【Manager·回执】已收到你的指令：「{message[:80]}{'…' if len(message) > 80 else ''}」。"
                 "已进入事件流，调度器将据此调整任务计划。")
        return {"reply": reply, "new_project": None}

    pid, workspace = intent
    result = intake.start_project(pid, pid, workspace, message)
    new_project = str(result["project"])
    session["project"] = new_project

    mode_intent = intake.detect_mode(message)
    if mode_intent:
        bus.set_mode(mode_intent, actor="用户")

    with _loops_lock:
        if new_project not in _active_loops:
            _active_loops.add(new_project)
            threading.Thread(
                target=lambda: asyncio.run(scheduler.run_loop(bus, project_id=new_project)),
                daemon=True,
            ).start()

    reply = (f"【Manager·回执】项目 {new_project} 已启动：{result['stages']} 个阶段 / {result['tasks']} 个任务"
             f"已建册进入派工队列（工作区 {workspace}，执行模式：{bus.mode}）。"
             "调度循环已接管；任务完成、异常或熔断时将邮件通知。")
    return {"reply": reply, "new_project": new_project}


@app.post("/api/chat")
async def api_chat(request: Request):
    try:
        data = await json_body(request)
    except BodyDecodeError:
        return JSONResponse({"ok": False, "error": "请求体必须是 JSON 对象"}, status_code=400)
    session = request.state.session
    project = str(data.get("project", session["project"]))
    message = str(data.get("message", "")).strip()
    if not message:
        return JSONResponse({"ok": False, "error": "消息内容不能为空"}, status_code=400)
    outcome = _process_chat(session, project, message)
    if outcome.get("new_project"):
        # 会话项目切换持久化（check_session 返回副本，需回写存储本体）
        auth_header = request.headers.get("Authorization", "")
        chat_token = auth_header[7:].strip() if auth_header.startswith("Bearer ") else ""
        with _sessions_lock:
            sess = _sessions.get(chat_token)
            if sess:
                sess["project"] = outcome["new_project"]
    user_row = events.append(actor="用户", action="chat", summary=message, project=project)
    manager_row = events.append(
        actor="Manager", action="chat_reply", summary=outcome["reply"],
        project=outcome.get("new_project") or project,
        extra={"new_project": outcome["new_project"]} if outcome.get("new_project") else None,
    )
    return {"ok": True, "user_event": user_row, "manager_event": manager_row,
            "reply": outcome["reply"], "new_project": outcome.get("new_project")}


@app.post("/api/notify/test")
async def api_notify_test(request: Request):
    """发送一封测试邮件（新版移动端 HTML 模板，含真实项目进度与预计完成时间）。

    请求体可选 {"project": "<project_id>"}；缺省取最近更新的项目。
    参数取 .env email 段（角色C fleet/notify 已交付）。
    """
    cfg = fleet_config.load("email")
    sender = fleet_config.unmask(cfg.get("sender") or "")
    receiver = fleet_config.unmask(cfg.get("receiver") or "")
    host = fleet_config.unmask(cfg.get("host") or "") or "smtp.163.com"
    password = fleet_config.unmask(cfg.get("auth_code") or "")
    port = int(cfg.get("port") or 465)
    missing = [name for name, value in (("发件邮箱", sender), ("收件邮箱", receiver), ("授权码", password)) if not value]
    if missing:
        return JSONResponse({"ok": False, "error": "邮件配置不完整，缺少：" + "、".join(missing)
                             + "。请到「消息」页填好后重试（授权码真值只放环境变量，.env 存 ${VAR}）。"},
                            status_code=200)
    try:
        from fleet.notify.smtp import send_email  # noqa: F401  # try import 探测：INT-03 交付后自动接通
    except Exception as exc:  # notify 模块异常时不静默
        return JSONResponse(
            {"ok": False, "reason": "notify接线未完成", "error": f"notify 模块不可用：{exc}"},
            status_code=503,
        )

    # 选定展示项目：请求体指定 > 最近更新的项目 > 兜底 default
    project = ""
    try:
        data = await json_body(request)
        project = str((data or {}).get("project") or "").strip()
    except BodyDecodeError:
        pass
    if not project:
        try:
            rows = [r for r in db.list_projects() if str(r.get("project_id") or "").strip()]
            project = max(rows, key=lambda r: str(r.get("updated_at") or ""))["project_id"] if rows else ""
        except Exception:
            project = ""
    if not project:
        project = str(fleet_config.load("basic").get("default_project") or "default")

    # 渲染真实进度 + ETA 的移动端模板；渲染失败降级纯文本，绝不因模板阻塞 SMTP 探测
    try:
        from fleet.notify import progress as _progress, templates as _templates

        prog = _progress.compute_project_progress(project)
        html, plain = _templates.render_status_email(
            project=project, event_label="测试邮件 · 状态通知",
            summary="收到本邮件即表示 SMTP 配置可用；进度与预计完成时间来自当前任务数据。",
            occurred_at=db.iso_now(), progress=prog, tasks=prog.get("tasks") or [],
        )
        subject = f"【AideanFleet】测试邮件 · {project} 进度 {prog['percent']}%"
    except Exception as exc:
        html, plain = None, "这是一封来自 AideanFleet 网页控制端的测试邮件，收到即表示 SMTP 配置可用。" \
            + f"（模板渲染失败已降级：{exc}）"
        subject = "【AideanFleet】测试邮件"
    ok, message = send_email(
        subject=subject, body=plain, html=html,
        receiver=receiver, smtp_host=host, smtp_port=port, sender=sender, password=password,
    )
    return {"ok": bool(ok), "message": message, "receiver": receiver, "project": project}


@app.get("/api/notify/triggers")
def api_notify_triggers():
    """角色C 的触发开关清单（config/notifications.json，控制台只读展示）。"""
    target = paths().root / "config" / "notifications.json"
    if not target.exists():
        return {"ok": True, "data": {}, "source": str(target)}
    try:
        return {"ok": True, "data": json.loads(target.read_text(encoding="utf-8")), "source": str(target)}
    except (OSError, json.JSONDecodeError) as exc:
        return JSONResponse({"ok": False, "error": f"读取触发器配置失败：{exc}"}, status_code=500)


# ---------------------------------------------------------------------------
# 拓展（执行体 skills / mcp 勾选，控制台侧配置，落 data/extensions.json）
# ---------------------------------------------------------------------------

_EXT_PATH = paths().data_dir / "extensions.json"


def _ext_load() -> dict[str, Any]:
    try:
        data = json.loads(_EXT_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


@app.get("/api/extensions")
def api_extensions_get():
    return {"ok": True, "data": _ext_load(), "source": str(_EXT_PATH)}


@app.post("/api/extensions")
async def api_extensions_post(request: Request):
    try:
        body = await json_body(request)
    except BodyDecodeError:
        return JSONResponse({"ok": False, "error": "请求体必须是 JSON 对象"}, status_code=400)
    payload = body.get("data") if isinstance(body.get("data"), dict) else body
    out: dict[str, Any] = {}
    for name, rec in payload.items():
        if not isinstance(rec, dict):
            continue
        out[str(name)] = {
            "skills": [str(x) for x in (rec.get("skills") or []) if str(x).strip()],
            "mcp": [str(x) for x in (rec.get("mcp") or []) if str(x).strip()],
        }
    _EXT_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = _EXT_PATH.parent / f".{_EXT_PATH.name}.tmp"
    tmp.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, _EXT_PATH)
    broadcast({"type": "config_changed", "section": "extensions"})
    return {"ok": True, "message": "拓展配置已保存", "count": len(out)}


# ---------------------------------------------------------------------------
# 角色 → 执行体兜底链（控制台侧扩展；契约 roles.adapter 只放第一个生效执行体）
# 原因：fleet/manager/dispatcher._adapter_for 取的是单个适配器名，写逗号串会直接
#      AdapterNotAvailable。完整有序链存这里，派工侧等角色A支持多适配器后再并入。
# ---------------------------------------------------------------------------

_ROLE_ADAPTERS_PATH = paths().data_dir / "role_adapters.json"


@app.get("/api/role-adapters")
def api_role_adapters_get():
    try:
        data = json.loads(_ROLE_ADAPTERS_PATH.read_text(encoding="utf-8"))
        return {"ok": True, "data": data if isinstance(data, dict) else {}}
    except (OSError, json.JSONDecodeError):
        return {"ok": True, "data": {}}


@app.post("/api/role-adapters")
async def api_role_adapters_post(request: Request):
    try:
        body = await json_body(request)
    except BodyDecodeError:
        return JSONResponse({"ok": False, "error": "请求体必须是 JSON 对象"}, status_code=400)
    payload = body.get("data") if isinstance(body.get("data"), dict) else body
    out: dict[str, Any] = {}
    for role, chain in payload.items():
        if isinstance(chain, str):
            chain = [x for x in chain.split(",")]
        if not isinstance(chain, (list, tuple)):
            continue
        items = [str(x).strip() for x in chain if str(x).strip()]
        if items:
            out[str(role)] = items
    _ROLE_ADAPTERS_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = _ROLE_ADAPTERS_PATH.parent / f".{_ROLE_ADAPTERS_PATH.name}.tmp"
    tmp.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, _ROLE_ADAPTERS_PATH)
    return {"ok": True, "message": "角色执行体链已保存", "count": len(out)}


# ---------------------------------------------------------------------------
# 配置（七契约段 + 旧段名别名）
# ---------------------------------------------------------------------------

#: 旧前端段名 -> 契约段名（别名层，写回时一律落契约段）
_SECTION_ALIASES: dict[str, str] = {
    "settings": "basic",
    "models": "model_pool",
    "extensions": "request",
    "message": "notify",
}


def _resolve_section(name: str) -> str:
    key = str(name or "").strip().lower()
    return _SECTION_ALIASES.get(key, key)


@app.get("/api/config/{section}")
def api_config_get(section: str):
    key = _resolve_section(section)
    if key not in fleet_config.SECTIONS:
        return JSONResponse({"ok": False, "reason": "unknown_section", "section": section,
                             "known": list(fleet_config.SECTIONS)}, status_code=400)
    return {"ok": True, "section": key, "data": fleet_config.load(key),
            "source": str(fleet_config.env_source()), "mtime": fleet_config.env_mtime()}


@app.post("/api/config/{section}")
async def api_config_post(request: Request, section: str):
    key = _resolve_section(section)
    if key not in fleet_config.SECTIONS:
        return JSONResponse({"ok": False, "reason": "unknown_section", "section": section,
                             "known": list(fleet_config.SECTIONS)}, status_code=400)
    try:
        data = await json_body(request)
    except BodyDecodeError:
        return JSONResponse({"ok": False, "error": "请求体必须是 JSON 对象"}, status_code=400)
    payload = data.get("data") if "data" in data else data
    if not isinstance(payload, dict):
        return JSONResponse({"ok": False, "error": "请求体格式错误：应为 {\"data\": {...}}"}, status_code=400)
    try:
        result = fleet_config.save(key, payload)
    except fleet_config.ConfigWriteDenied:
        return JSONResponse({"ok": False, "reason": "config_write_denied"}, status_code=403)
    except fleet_config.PlaintextSecretRejected as exc:
        return JSONResponse({"ok": False, "reason": "plaintext_secret_rejected", "error": str(exc)}, status_code=400)
    except fleet_config.ConfigError as exc:
        return JSONResponse({"ok": False, "error": f"配置保存失败：{exc}"}, status_code=500)
    broadcast({"type": "config_changed", "section": key, "mtime": result.get("mtime")})
    return {"ok": True, "section": key, **result}


# ---------------------------------------------------------------------------
# 任务详情 / 派工（契约 §6）
# ---------------------------------------------------------------------------


@app.get("/api/tasks/{task_id}")
def api_task(task_id: str):
    task = db.get_task(task_id)
    if task is None:
        return JSONResponse({"ok": False, "reason": "task_not_found", "taskId": task_id}, status_code=200)
    return {"ok": True, "task": task}


# ---------------------------------------------------------------------------
# 治理层 HTTP 面（GOV-01 库 → 控制台路由；审批中心 / 成本面板 数据源）
# ---------------------------------------------------------------------------

#: 进程内单例（governance 包纯函数/SQLite 线程安全；预算限值为惰性配置，不随请求变化）
_approval_manager = ApprovalManager()
_budget_manager = BudgetManager()
_usage_aggregator = UsageAggregator()


def _approval_dict(row: dict[str, Any]) -> dict[str, Any]:
    """store 行 → 前端契约形状（ApprovalRequest 字段 + ok 信封）。"""
    return {key: row.get(key, "") for key in (
        "approval_id", "action_type", "description", "task_id", "project_id",
        "requested_by", "status", "decision", "decided_by", "decided_at",
        "created_at", "expires_at",
    )}


def _budget_dict(limit: Any) -> dict[str, Any]:
    if limit is None:
        return {}
    data = limit.__dict__ if hasattr(limit, "__dict__") else dict(limit)
    return {key: data.get(key, 0) for key in ("level", "scope", "limit_tokens", "used_tokens", "action")}


@app.get("/api/approvals")
def api_approvals_list(project: str | None = None):
    """待审批与近期审批记录（会话保护；project 过滤 project_id）。"""
    rows = _approval_manager.list_pending()
    if project:
        rows = [row for row in rows if row.get("project_id") == project]
    return {"ok": True, "approvals": [_approval_dict(row) for row in rows], "pending": len(rows)}


@app.get("/api/approvals/{approval_id}")
def api_approvals_detail(approval_id: str):
    row = _approval_manager.get_status(approval_id)
    if row is None:
        return JSONResponse({"ok": False, "reason": "approval_not_found", "approvalId": approval_id}, status_code=200)
    return {"ok": True, "approval": _approval_dict(row)}


@app.post("/api/approvals/{approval_id}/approve")
async def api_approvals_approve(request: Request, approval_id: str):
    try:
        data = await json_body(request)
    except BodyDecodeError:
        return JSONResponse({"ok": False, "error": "请求体必须是 JSON 对象"}, status_code=400)
    decided_by = str(data.get("decided_by") or "console-user")
    decision = _approval_manager.approve(approval_id, decided_by=decided_by)
    _sync_events_budget_after_decision(approval_id, decision)
    return {"ok": True, **decision.__dict__}


@app.post("/api/approvals/{approval_id}/reject")
async def api_approvals_reject(request: Request, approval_id: str):
    try:
        data = await json_body(request)
    except BodyDecodeError:
        return JSONResponse({"ok": False, "error": "请求体必须是 JSON 对象"}, status_code=400)
    decided_by = str(data.get("decided_by") or "console-user")
    decision = _approval_manager.reject(approval_id, decided_by=decided_by)
    return {"ok": True, **decision.__dict__}


def _sync_events_budget_after_decision(approval_id: str, decision: Any) -> None:
    """审批通过后若为 budget_warning 触发，把用量变化落到事件流（契约 §13 消费面）。"""
    try:
        row = _approval_manager.get_status(approval_id) or {}
        project = str(row.get("project_id") or "")
        if project:
            events.append(
                actor="governance", action="approval:decided",
                task_id=str(row.get("task_id") or ""),
                summary=f"审批 {approval_id} -> {decision.decision}（{decision.decided_by}）",
                project=project, extra={"approval_id": approval_id, "decision": decision.decision},
            )
    except Exception:
        pass  # 审批结果以 governance.db 为准，事件流是旁路，不因旁路失败回滚


@app.get("/api/usage/total")
def api_usage_total(since: str = ""):
    totals = _usage_aggregator.total(since=since or None)
    return {"ok": True, **totals}


@app.get("/api/usage/by_date")
def api_usage_by_date(since: str = ""):
    rows = _usage_aggregator.by_date(since=since or None)
    return {"ok": True, "rows": rows}


@app.get("/api/budget")
def api_budget(request: Request, task_id: str = "", project_id: str = ""):
    """三级预算池当前状态（task/project/daily；daily 恒返回当日口径）。"""
    # 会话项目兜底：未显式传 project_id 时取当前会话项目（再兜底 .env basic.default_project）
    if not project_id:
        session = getattr(request.state, "session", None)
        project_id = str(session.get("project") or "") if session else ""
    if not project_id:
        try:
            project_id = str(fleet_config.load("basic").get("default_project") or "")
        except fleet_config.ConfigError:
            project_id = ""
    status = _budget_manager.get_status(task_id=task_id, project_id=project_id)
    payload: dict[str, Any] = {"ok": True}
    for level in ("task", "project", "daily"):
        item = status.get(level)
        if item:
            payload[level] = _budget_dict(item)
    return payload


@app.post("/api/budget")
def api_budget_set(level: str, scope: str, limit_tokens: int = 0, action: str = "pause"):
    if level not in ("task", "project", "daily"):
        return JSONResponse({"ok": False, "error": "level 只能为 task/project/daily"}, status_code=400)
    _budget_manager.set_limit(level, scope, limit_tokens, action)
    return {"ok": True, "level": level, "scope": scope, "limit_tokens": limit_tokens, "action": action}


@app.get("/api/roles/summary")
def api_roles_summary(request: Request, project: str | None = None):
    """角色贡献聚合：assignee → 任务数/完成数/耗时；token/调用次数按 model:call 事件的 role 归属。

    token 不按任务归属（审查类调用无 taskId），直接对项目事件流按 extra.role 聚合，口径可对账。
    """
    session = request.state.session
    pid = str(project or session["project"])
    if db.get_project(pid) is None:
        return JSONResponse({"ok": False, "reason": "project_not_found", "project": pid}, status_code=200)
    roles: dict[str, dict[str, Any]] = {}
    for task in db.list_tasks(pid):
        role = str(task.get("assignee") or "未指定")
        bucket = roles.setdefault(role, {
            "role": role, "tasks_total": 0, "tasks_done": 0,
            "duration_ms": 0, "total_tokens": 0, "call_count": 0,
        })
        bucket["tasks_total"] += 1
        if task.get("exec_status") == "DONE":
            bucket["tasks_done"] += 1
        bucket["duration_ms"] += int(task.get("duration_ms") or 0)
    for row in events.read(project=pid, since=0):
        if row.get("action") != "model:call":
            continue
        extra = row.get("extra") or {}
        role = str(extra.get("role") or row.get("actor") or "未指定")
        usage = extra.get("usage") or {}
        bucket = roles.setdefault(role, {
            "role": role, "tasks_total": 0, "tasks_done": 0,
            "duration_ms": 0, "total_tokens": 0, "call_count": 0,
        })
        bucket["total_tokens"] += int(usage.get("total_tokens") or 0)
        bucket["call_count"] += 1
    ordered = sorted(roles.values(), key=lambda item: (-item["total_tokens"], -item["duration_ms"]))
    return {"ok": True, "project": pid, "roles": ordered}


# ---------------------------------------------------------------------------
# 可观测性扩展（需求4/5/6）：运行中执行体 / 历史任务 / 角色工作档案
# 数据源：执行体登记表（进程内）+ tasks 表 + events 事件流，均为旁路只读，绝不改状态机。
# ---------------------------------------------------------------------------


@app.get("/api/executors/running")
def api_executors_running(request: Request, project: str | None = None):
    """当前在执行体的实时读数：进程名/PID/任务归属/角色/已运行时长（需求4）。

    登记表与调度器同进程（控制台内联派工 + run_loop 线程），无需 IPC；
    跨进程独立运行的调度器不在本读数范围（见执行体页脚注说明）。
    """
    from fleet.executors import registry as exec_registry

    session = request.state.session
    pid = str(project or session["project"])
    rows = [
        row for row in exec_registry.snapshot()
        if not row.get("project") or row["project"] == pid
    ]
    return {"ok": True, "project": pid, "executors": rows, "count": len(rows)}


@app.get("/api/history/tasks")
def api_history_tasks(request: Request, project: str | None = None, limit: int = 200):
    """历史任务列表（需求5）：执行/审查角色、耗时、token、返工次数，按更新时间倒序。"""
    session = request.state.session
    pid = str(project or session["project"])
    if db.get_project(pid) is None:
        return JSONResponse({"ok": False, "reason": "project_not_found", "project": pid}, status_code=200)
    index = plan.tasks_index(pid)
    rows = sorted(
        db.list_tasks(pid),
        key=lambda row: str(row.get("updated_at") or ""),
        reverse=True,
    )
    items = []
    for row in rows[: max(1, min(limit, 1000))]:
        meta = index.get(row["task_id"], {})
        items.append({
            "task_id": row["task_id"],
            "title": row.get("title") or meta.get("subtask") or "",
            "stage": meta.get("stage") or "",
            "subtask": meta.get("subtask") or "",
            "role": row.get("role") or row.get("assignee") or "",
            "assignee": row.get("assignee") or "",
            "reviewer": row.get("reviewer") or "",
            "exec_status": row.get("exec_status") or "",
            "review_status": row.get("review_status") or "",
            "duration_ms": int(row.get("duration_ms") or 0),
            "token": int(row.get("token") or 0),
            "model": row.get("model") or "",
            "adapter": row.get("adapter") or "",
            "rework_count": int(row.get("rework_count") or 0),
            "created_at": row.get("created_at") or "",
            "updated_at": row.get("updated_at") or "",
        })
    return {"ok": True, "project": pid, "total": len(items), "tasks": items}


@app.get("/api/roles/{role}/profile")
def api_role_profile(request: Request, role: str, project: str | None = None):
    """角色工作档案（需求6）：做过什么、耗时与 token、以及未来任务分配。

    口径与 /api/roles/summary 一致：耗时=Σ duration_ms（assignee 归属）；
    token/调用次数=事件流 model:call 的 extra.role 归属（审查调用无 taskId 也计入）。
    """
    session = request.state.session
    pid = str(project or session["project"])
    if db.get_project(pid) is None:
        return JSONResponse({"ok": False, "reason": "project_not_found", "project": pid}, status_code=200)
    index = plan.tasks_index(pid)

    def _brief(row: dict[str, Any]) -> dict[str, Any]:
        meta = index.get(row["task_id"], {})
        return {
            "task_id": row["task_id"],
            "title": row.get("title") or meta.get("subtask") or "",
            "stage": meta.get("stage") or "",
            "state": row.get("exec_status") or "",
            "review_status": row.get("review_status") or "",
            "duration_ms": int(row.get("duration_ms") or 0),
            "token": int(row.get("token") or 0),
            "rework_count": int(row.get("rework_count") or 0),
            "updated_at": row.get("updated_at") or "",
        }

    executed: list[dict[str, Any]] = []
    reviewed: list[dict[str, Any]] = []
    future: list[dict[str, Any]] = []
    duration_ms = 0
    future_states = {"DRAFT", "ASSIGNED", "REWORK", "BLOCKED", "ESCALATED"}
    for row in db.list_tasks(pid):
        if str(row.get("assignee") or "") == role:
            brief = _brief(row)
            executed.append(brief)
            duration_ms += brief["duration_ms"]
            if brief["state"] in future_states:
                future.append(brief)
        if str(row.get("reviewer") or "") == role:
            reviewed.append(_brief(row))

    total_tokens = 0
    call_count = 0
    for event_row in events.read(project=pid, since=0):
        if event_row.get("action") != "model:call":
            continue
        extra = event_row.get("extra") or {}
        if str(extra.get("role") or event_row.get("actor") or "") != role:
            continue
        usage = extra.get("usage") or {}
        total_tokens += int(usage.get("total_tokens") or 0)
        call_count += 1

    executed.sort(key=lambda item: str(item["updated_at"]), reverse=True)
    reviewed.sort(key=lambda item: str(item["updated_at"]), reverse=True)
    done_count = sum(1 for item in executed if item["state"] in ("DONE", "PARTIAL"))
    return {
        "ok": True, "project": pid, "role": role,
        "profile": {
            "role": role,
            "executed": executed, "executed_count": len(executed), "done_count": done_count,
            "reviewed": reviewed, "reviewed_count": len(reviewed),
            "future": future, "future_count": len(future),
            "duration_ms": duration_ms, "total_tokens": total_tokens, "call_count": call_count,
        },
    }


@app.post("/tasks/{task_id}/dispatch")
def api_dispatch(task_id: str):
    if db.get_task(task_id) is None:
        return JSONResponse({"ok": False, "reason": "task_not_found", "taskId": task_id}, status_code=200)
    try:
        outcome = dispatcher.run_to_completion(task_id, actor="console")
    except sm.InvalidTransition as exc:
        return JSONResponse({"ok": False, "reason": "invalid_transition", "from": exc.from_state,
                             "to": exc.to_state, "taskId": task_id, "error": exc.reason}, status_code=409)
    except dispatcher.AdapterNotAvailable as exc:
        return JSONResponse({"ok": False, "reason": "blocked", "taskId": task_id,
                             "state": "BLOCKED", "detail": f"adapter_unavailable: {exc}"}, status_code=200)
    return {"ok": bool(outcome.get("ok")), "taskId": task_id, "state": outcome.get("state"),
            "rounds": outcome.get("rounds", [])}


# ---------------------------------------------------------------------------
# 静态资源：dist/ 优先，static/ 兜底（双目录回退）
# ---------------------------------------------------------------------------

_CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".ico": "image/x-icon",
    ".json": "application/json; charset=utf-8",
}


def _static_file(relative: str) -> FileResponse | None:
    relative = relative.lstrip("/") or "index.html"
    for base in (DIST_DIR, STATIC_DIR):
        full = (base / relative).resolve()
        if not str(full).startswith(str(base.resolve())) or not full.is_file():
            continue
        return FileResponse(full, media_type=_CONTENT_TYPES.get(full.suffix.lower(), "application/octet-stream"),
                            headers={"Cache-Control": "no-store"})
    return None


@app.get("/{path:path}", include_in_schema=False)
def api_static(path: str):
    if path.startswith("api/"):
        return JSONResponse({"ok": False, "reason": "not_found"}, status_code=404)
    target = path or "index.html"
    if not Path(target).suffix:  # SPA 兜底：无后缀路径回 index.html
        target = "index.html"
    found = _static_file(target)
    if found is None:
        return JSONResponse({"ok": False, "reason": "not_found"}, status_code=404)
    return found


# ---------------------------------------------------------------------------
# WebSocket：/ws（7 种服务端消息，3 种客户端消息）
# ---------------------------------------------------------------------------


@app.websocket("/ws")
async def ws_endpoint(websocket: WebSocket):
    global _loop, _pump_task
    token = websocket.query_params.get("token") or token_of(websocket)
    session = check_session(token)
    if not session:
        await websocket.close(code=4401)
        return
    await websocket.accept()
    _loop = asyncio.get_running_loop()
    with _connections_lock:
        _connections.add(websocket)
        _connections_project[websocket] = session.get('project', '')
        _connections_token[websocket] = token
    if _pump_task is None or _pump_task.done():
        _pump_task = asyncio.create_task(_event_pump())
    try:
        while True:
            raw = await websocket.receive_text()
            try:
                message = json.loads(raw)
                if not isinstance(message, dict):
                    raise ValueError
            except ValueError:
                await websocket.send_text(json.dumps({"type": "notification", "error": "消息必须是 JSON 对象"},
                                                     ensure_ascii=False))
                continue
            kind = str(message.get("type") or "")
            if kind == "chat":
                reply_event = _handle_ws_chat(session, message)
                await websocket.send_text(json.dumps({"type": "chat_message", **reply_event}, ensure_ascii=False))
            elif kind == "set_mode":
                try:
                    mode = bus.set_mode(_normalize_mode(str(message.get("mode", ""))),
                                        actor=str(message.get("actor") or "用户"))
                except ValueError:
                    mode = None
                await websocket.send_text(json.dumps({"type": "notification", "mode": mode}, ensure_ascii=False))
            elif kind == "confirm_step":
                result = _handle_ws_confirm(session, message)
                await websocket.send_text(json.dumps({"type": "notification", **result}, ensure_ascii=False))
            else:
                await websocket.send_text(json.dumps({"type": "notification", "error": f"未知消息类型：{kind}"},
                                                     ensure_ascii=False))
    except WebSocketDisconnect:
        pass
    finally:
        with _connections_lock:
            _connections.discard(websocket)
            _connections_project.pop(websocket, None)
            _connections_token.pop(websocket, None)


def _handle_ws_chat(session: dict[str, Any], message: dict[str, Any]) -> dict[str, Any]:
    project = str(message.get("project") or session["project"])
    text = str(message.get("message") or "").strip()
    user_row = events.append(actor="用户", action="chat", summary=text or "(空消息)", project=project)
    broadcast({"type": "chat_message", "project": str(user_row.get("project") or ""), "event": user_row})
    outcome = _process_chat(session, project, text)
    manager_row = events.append(
        actor="Manager", action="chat_reply", summary=outcome["reply"],
        project=outcome.get("new_project") or project,
        extra={"new_project": outcome["new_project"]} if outcome.get("new_project") else None,
    )
    broadcast({"type": "chat_message", "project": str(manager_row.get("project") or ""), "event": manager_row})
    return {"event": manager_row}


def _handle_ws_confirm(session: dict[str, Any], message: dict[str, Any]) -> dict[str, Any]:
    task_id = str(message.get("taskId") or "") or None
    note = str(message.get("note") or "").strip()
    bus.confirm(task_id=task_id, actor="用户", note=note)
    row = events.append(actor="用户", action="step_confirm", task_id=task_id,
                        summary=note or "用户确认当前步骤", project=session["project"])
    return {"event": row}


# ---------------------------------------------------------------------------
# 启动
# ---------------------------------------------------------------------------


@app.on_event("startup")
def _on_startup() -> None:
    fleet_config.allow_write(True)  # 控制台进程允许写 .env；引擎侧保持只读
    try:  # REL-01：事件归档轮转 + 卡死扫描（幂等，失败不阻塞启动）
        from fleet.rel import maintenance

        maintenance.start()
    except Exception:
        pass
    if _SCHEDULER_ENABLED:
        # 服务重启后内存态（_active_loops/bus.mode）丢失：对存在非终态任务的项目恢复调度循环，
        # 否则重启后没有任何 run_loop 在跑，DRAFT/SUBMITTED 任务永远无人推进（此前实测断链）。
        import asyncio as _asyncio

        _ACTIVE_STATES = ("DRAFT", "ASSIGNED", "DOING", "SUBMITTED", "REWORK")
        for _p in db.list_projects():
            _pid = str(_p.get("project_id") or "")
            if not _pid:
                continue
            # notify watch 循环对所有项目拉起（与是否有活跃任务无关）：
            # 终态项目的事件补发/后续升级事件仍需邮件通知；此前只有 launch_core 启动的项目才有监控，
            # 重启后 watch 缺失导致任务终态事件永远不发邮件（实测 Test09161119 无 last_seq）。
            try:
                from fleet.notify.triggers import watch_events_loop as _watch, get_trigger as _get_trigger

                threading.Thread(
                    target=lambda pid=_pid: _watch(pid, _get_trigger()),
                    daemon=True,
                    name=f"watch-{_pid}",
                ).start()
            except Exception:
                pass  # notify 不可用不阻塞调度恢复
            _tasks = db.list_tasks(_pid)
            if not any(t.get("exec_status") in _ACTIVE_STATES for t in _tasks):
                continue
            with _loops_lock:
                if _pid in _active_loops:
                    continue
                _active_loops.add(_pid)
                threading.Thread(
                    target=lambda pid=_pid: asyncio.run(scheduler.run_loop(bus, project_id=pid)),
                    daemon=True,
                ).start()
            events.append(
                actor="console",
                action="scheduler:resumed",
                summary=f"服务重启：项目 {_pid} 调度循环已恢复",
                project=_pid,
            )
    if _SCHEDULER_ENABLED:
        asyncio.get_event_loop().create_task(
            scheduler.run_loop(bus, on_outcome=lambda item: broadcast({"type": "task_update", "dispatch": item}))
        )


def main() -> None:
    import uvicorn

    fleet_config.ensure_env_file()
    db.init_db()
    print(f"AideanFleet 网页控制端已启动：http://{HOST}:{PORT}（FastAPI+WS 版本 {VERSION}）")
    print(f"会话有效期：{session_expire_seconds()} 秒 | 调度循环：{'开' if _SCHEDULER_ENABLED else '关（FLEET_SCHEDULER=1 打开）'}")
    uvicorn.run(app, host=HOST, port=PORT, log_level="warning")


if __name__ == "__main__":
    main()
