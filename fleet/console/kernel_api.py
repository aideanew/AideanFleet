"""这是什么：Kernel 投影 API（TASK-103，契约 api.json）。
唯一数据源：fleet.kernel（单写者）；本路由只做读投影 + typed 管理面动作。
错误映射（errors.json kernel_exception_mapping）：
  KeyError → 404 GOAL_NOT_FOUND / TODO_NOT_FOUND；
  GoalAlreadyFrozen → 409 GOAL_ALREADY_FROZEN；RequirementsNotReady → 409 REQUIREMENTS_NOT_READY（P3）；
  KernelError → 409 ILLEGAL_TRANSITION。
管理面（B3）：goals.create / goals.clarify / goals.freeze / todos.reopen 需 owner 会话（server.py 会话中间件覆盖）。
"""

from __future__ import annotations

import json
import re
import threading
import time
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse, JSONResponse

from fleet.core.paths import paths
from fleet.kernel import store
from fleet.kernel import Kernel, KernelError
from fleet.kernel.kernel import GoalAlreadyFrozen, RequirementsNotReady

router = APIRouter(prefix="/api/kernel", tags=["kernel"])

EVIDENCE_FILES: dict[str, str] = {
    "gate.json": "gate",
    "harness_output.txt": "harness_output",
    "writeback_note.txt": "host_note",
}


def _kernel() -> Kernel:
    return Kernel(paths().data_dir / "kernel.db")


def _error(reason: str, message: str, status: int, details: dict | None = None):
    body: dict[str, Any] = {"ok": False, "error": message, "reason": reason}
    if details:
        body["details"] = details
    return JSONResponse(body, status_code=status)


def _map_kernel_error(exc: Exception):
    if isinstance(exc, KeyError):
        text = str(exc)
        if "goal" in text or "G-" in text:
            return _error("GOAL_NOT_FOUND", f"目标不存在 {text}", 404)
        return _error("TODO_NOT_FOUND", f"任务不存在 {text}", 404)
    if isinstance(exc, GoalAlreadyFrozen):
        return _error("GOAL_ALREADY_FROZEN", str(exc), 409)
    if isinstance(exc, RequirementsNotReady):
        return _error("REQUIREMENTS_NOT_READY", str(exc), 409)
    if isinstance(exc, KernelError):
        return _error("ILLEGAL_TRANSITION", str(exc), 409)
    return _error("INTERNAL", f"内部错误：{exc}", 500)


# ---------------------------------------------------------------------------
# 幂等（Idempotency-Key，进程内 + 24h TTL）
# ---------------------------------------------------------------------------

_IDEMPOTENCY: dict[str, tuple[float, dict]] = {}
_IDEMPOTENCY_LOCK = threading.Lock()
_IDEMPOTENCY_TTL = 24 * 3600


def _idempotency_key(request: Request) -> str:
    return (request.headers.get("Idempotency-Key") or "").strip()[:64]


def _idempotent_hit(request: Request) -> dict | None:
    key = _idempotency_key(request)
    if not key:
        return None
    now = time.time()
    with _IDEMPOTENCY_LOCK:
        for stale in [k for k, (ts, _) in _IDEMPOTENCY.items() if now - ts > _IDEMPOTENCY_TTL]:
            _IDEMPOTENCY.pop(stale, None)
        hit = _IDEMPOTENCY.get(key)
    return hit[1] if hit else None


def _store_idempotent(request: Request, payload: dict) -> None:
    key = _idempotency_key(request)
    if key:
        with _IDEMPOTENCY_LOCK:
            _IDEMPOTENCY[key] = (time.time(), payload)


# ---------------------------------------------------------------------------
# goals
# ---------------------------------------------------------------------------


def _workspace_roots() -> list[str]:
    """workspace 白名单单源（P1.3）：fleet.core.roots.current()。

    env > fleet.toml > 旧 .env basic > <data_dir>/workspaces 缺省；
    历史上这里回退 intake._allowed_roots（仓库根），安装器部署写保护，已收敛。
    """
    from fleet.core import roots as workspace_roots

    return workspace_roots.current()


def _workspace_ok(workspace: str) -> bool:
    norm = str(workspace).replace("/", "\\").rstrip("\\").lower()
    for root in _workspace_roots():
        root_norm = str(root).replace("/", "\\").rstrip("\\").lower()
        if norm == root_norm or norm.startswith(root_norm + "\\"):
            return True
    return False


def _slug(title: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9_\-\u4e00-\u9fa5]+", "-", title).strip("-") or "goal"
    return slug[:60]


@router.post("/goals")
async def goals_create(request: Request):
    hit = _idempotent_hit(request)
    if hit is not None:
        return JSONResponse(hit, status_code=200)
    try:
        body = await request.json()
    except Exception:
        return _error("VALIDATION_FAILED", "请求体必须是 JSON 对象", 422)
    if not isinstance(body, dict):
        return _error("VALIDATION_FAILED", "请求体必须是 JSON 对象", 422)

    title = str(body.get("title") or "").strip()
    requirements = str(body.get("requirements") or "").strip()
    workspace = str(body.get("workspace") or "").strip()
    mode = str(body.get("mode") or "direct").strip()
    details: dict[str, str] = {}
    if not title or len(title) > 120:
        details["title"] = "必填，1..120 字符"
    if not requirements or len(requirements) > 20000:
        details["requirements"] = "必填，1..20000 字符"
    if mode not in ("direct", "draft"):
        details["mode"] = "只允许 direct / draft"
    if details:
        return _error("VALIDATION_FAILED", "请求字段不合法", 422, details)

    roots = _workspace_roots()
    if not workspace:
        if not roots:
            return _error("WORKSPACE_NOT_ALLOWED", "未配置 allowed_roots，无法推导工作区", 422)
        workspace = str(Path(roots[0]) / _slug(title))

    # SETUP_INCOMPLETE 三态（P1.4）：无模型/缺密钥/未绑定 → 409 带 hint 引导去 /setup
    # （先于 workspace 细节校验；details.hint 纯增量，旧前端读 reason/error 不受影响）
    # draft 模式不过此门（P3）：不出计划、无需规划器，建目标后经 goals.freeze 时再门。
    if mode != "draft":
        try:
            from fleet.cli.clients import planner_status

            status = planner_status()
            if not status["ready"]:
                return _error("SETUP_INCOMPLETE", status["message"], 409,
                              {"hint": {"state": status["state"],
                                        "missing_keys": status["missing_keys"]}})
        except Exception:
            pass

    if not _workspace_ok(workspace):
        return _error("WORKSPACE_NOT_ALLOWED",
                      f"工作区 {workspace} 不在白名单内（允许：{', '.join(roots) or '未配置'}）", 422)

    kernel = _kernel()
    try:
        if mode == "draft":
            goal_id = kernel.create_goal_draft(title, requirements, workspace)
            plan_todo_id = None
        else:
            goal_id, plan_todo_id = kernel.create_goal_with_plan(title, requirements, workspace)
        goal = kernel.get_goal(goal_id)
    except Exception as exc:
        return _map_kernel_error(exc)
    payload = {"ok": True, "goal": goal, "plan_todo_id": plan_todo_id}
    _store_idempotent(request, payload)
    return JSONResponse(payload, status_code=200)


@router.get("/goals")
def goals_list(limit: int = 100, cursor: str | None = None):
    try:
        limit = min(max(limit, 1), 500)
    except (TypeError, ValueError):
        return _error("VALIDATION_FAILED", "limit 必须是整数", 422)
    goals = _kernel().attention()["goals"]
    offset = 0
    if cursor:
        try:
            offset = max(0, int(cursor.removeprefix("o:")))
        except ValueError:
            return _error("VALIDATION_FAILED", "cursor 无效", 422)
    page = goals[offset:offset + limit]
    next_cursor = f"o:{offset + limit}" if offset + limit < len(goals) else None
    return {"ok": True, "items": page, "next_cursor": next_cursor}


@router.get("/goals/{goal_id}")
def goals_get(goal_id: str):
    """P3：goal 全列投影（含 requirements_state）。"""
    try:
        goal = _kernel().get_goal(goal_id)
    except Exception as exc:
        return _map_kernel_error(exc)
    return {"ok": True, "goal": goal}


@router.post("/goals/{goal_id}/clarify")
async def goals_clarify(goal_id: str, request: Request):
    """P3 追加式澄清：draft 态把 addition 并入 requirements，可多次。"""
    try:
        body = await request.json()
    except Exception:
        return _error("VALIDATION_FAILED", "请求体必须是 JSON 对象", 422)
    addition = str((body or {}).get("addition") or "").strip()
    if not addition or len(addition) > 20000:
        return _error("VALIDATION_FAILED", "addition 必填，1..20000 字符", 422)
    try:
        goal = _kernel().append_goal_requirements(goal_id, addition)
    except Exception as exc:
        return _map_kernel_error(exc)
    return {"ok": True, "goal": goal}


@router.post("/goals/{goal_id}/freeze")
def goals_freeze(goal_id: str):
    """P3 冻结：锁定需求并同事务建 kind=plan 规划 todo。

    过 SETUP_INCOMPLETE 三态门（与 direct 建目标一致，P3 决策）：
    冻结即触发规划，规划器未就绪时给引导而非静默卡死。
    """
    try:
        from fleet.cli.clients import planner_status

        status = planner_status()
        if not status["ready"]:
            return _error("SETUP_INCOMPLETE", status["message"], 409,
                          {"hint": {"state": status["state"],
                                    "missing_keys": status["missing_keys"]}})
    except Exception:
        pass
    try:
        _, plan_todo_id, goal = _kernel().freeze_goal(goal_id)
    except Exception as exc:
        return _map_kernel_error(exc)
    return {"ok": True, "goal": goal, "plan_todo_id": plan_todo_id}


# ---------------------------------------------------------------------------
# todos
# ---------------------------------------------------------------------------


@router.get("/todos")
def todos_list(goal_id: str | None = None, status: str | None = None,
               limit: int = 100, cursor: str | None = None):
    todos = _kernel().todos(goal_id=goal_id, status=status)
    try:
        limit = min(max(limit, 1), 500)
    except (TypeError, ValueError):
        return _error("VALIDATION_FAILED", "limit 必须是整数", 422)
    offset = 0
    if cursor:
        try:
            offset = max(0, int(cursor.removeprefix("o:")))
        except ValueError:
            return _error("VALIDATION_FAILED", "cursor 无效", 422)
    page = todos[offset:offset + limit]
    next_cursor = f"o:{offset + limit}" if offset + limit < len(todos) else None
    return {"ok": True, "items": page, "next_cursor": next_cursor}


@router.get("/todos/{todo_id}")
def todos_get(todo_id: str):
    kernel = _kernel()
    try:
        todo = kernel.get_todo(todo_id)
    except Exception as exc:
        return _map_kernel_error(exc)
    attempts = kernel.attempts_of(todo_id)
    evidence_dir = Path(paths().data_dir) / "evidence" / todo_id
    evidence = []
    for name, kind in EVIDENCE_FILES.items():
        file = evidence_dir / name
        if file.is_file():
            evidence.append({
                "name": name, "kind": kind, "size": file.stat().st_size,
                "url": f"/api/kernel/todos/{todo_id}/evidence/{name}",
            })
    return {"ok": True, "todo": todo, "attempts": attempts, "evidence": evidence}


@router.get("/todos/{todo_id}/evidence/{name}")
def evidence_download(todo_id: str, name: str):
    if name not in EVIDENCE_FILES:
        return _error("VALIDATION_FAILED", f"证据文件名只允许 {sorted(EVIDENCE_FILES)}", 422)
    file = Path(paths().data_dir) / "evidence" / todo_id / name
    if not file.is_file():
        return _error("NOT_FOUND", "证据不存在或尚未生成", 404)
    return FileResponse(file, filename=name)


@router.post("/todos/{todo_id}/reopen")
def todos_reopen(todo_id: str):
    try:
        todo = _kernel().reopen(todo_id, actor="console")
    except Exception as exc:
        return _map_kernel_error(exc)
    try:
        from fleet.console.server import broadcast

        broadcast({"type": "task_update", "taskId": todo_id, "status": todo["status"]})
    except Exception:
        pass
    return {"ok": True, "todo": {"id": todo["id"], "status": todo["status"]}}


# ---------------------------------------------------------------------------
# attention / events
# ---------------------------------------------------------------------------


@router.get("/attention")
def attention():
    return {"ok": True, **_kernel().attention()}


@router.get("/events")
def events_list(limit: int = 100):
    kernel = _kernel()
    limit = min(max(limit, 1), 500)
    conn = store.connect(kernel.db_path)
    rows = [dict(r) for r in conn.execute(
        "SELECT seq, ts, kind, todo_id, goal_id, payload, published FROM events"
        " ORDER BY seq DESC LIMIT ?",
        (limit,))]
    for row in rows:
        try:
            row["payload"] = json.loads(row.get("payload") or "{}")
        except Exception:
            row["payload"] = {}
    return {"ok": True, "items": rows}


# ---------------------------------------------------------------------------
# steer（TASK-602，S6）：对话改计划
# ---------------------------------------------------------------------------


@router.post("/goals/{goal_id}/steer")
async def steer_create(goal_id: str, request: Request):
    hit = _idempotent_hit(request)
    if hit is not None:
        return JSONResponse(hit, status_code=200)
    try:
        body = await request.json()
    except Exception:
        return _error("VALIDATION_FAILED", "请求体必须是 JSON 对象", 422)
    message = str((body or {}).get("message") or "").strip()
    if not message or len(message) > 4000:
        return _error("VALIDATION_FAILED", "message 必填且 ≤4000 字符", 422)
    kernel = _kernel()
    try:
        kernel._get_goal(store.connect(kernel.db_path), goal_id)
    except Exception:
        return _map_kernel_error(KeyError(goal_id))
    try:
        steer_id = kernel.create_todo(
            goal_id, kind="steer", title=f"调整计划：{message[:40]}",
            packet=message, role="planner",
            workspace=_goal_workspace(store.connect(kernel.db_path), goal_id),
        )
    except Exception as exc:
        return _map_kernel_error(exc)
    payload = {"ok": True, "steer_todo_id": steer_id}
    _store_idempotent(request, payload)
    return payload


def _goal_workspace(conn, goal_id: str) -> str:
    row = conn.execute("SELECT workspace FROM goals WHERE id=?", (goal_id,)).fetchone()
    return str(row["workspace"]) if row else ""


@router.get("/todos/{todo_id}/diff")
def plan_diff_get(todo_id: str):
    kernel = _kernel()
    try:
        todo = kernel.get_todo(todo_id)
    except Exception as exc:
        return _map_kernel_error(exc)
    try:
        diff = json.loads(todo.get("packet") or "{}")
    except json.JSONDecodeError:
        diff = {}
    return {"ok": True, "diff": diff, "decision": todo.get("plan_decision") or "none"}


@router.post("/todos/{todo_id}/decision")
async def plan_decide(todo_id: str, request: Request):
    hit = _idempotent_hit(request)
    if hit is not None:
        return JSONResponse(hit, status_code=200)
    try:
        body = await request.json()
    except Exception:
        return _error("VALIDATION_FAILED", "请求体必须是 JSON 对象", 422)
    decision = str((body or {}).get("decision") or "")
    if decision not in ("approve", "reject"):
        return _error("VALIDATION_FAILED", "decision 只允许 approve/reject", 422)
    try:
        todo = _kernel().apply_plan_diff(todo_id, decision, actor="console")
    except Exception as exc:
        from fleet.kernel.kernel import DecisionAlreadyMade

        if isinstance(exc, DecisionAlreadyMade):
            return _error("DECISION_ALREADY_MADE", str(exc), 409)
        return _map_kernel_error(exc)
    try:
        from fleet.console.server import broadcast

        broadcast({"type": "task_update", "taskId": todo_id, "status": todo["status"],
                   "plan_decision": todo.get("plan_decision")})
    except Exception:
        pass
    payload = {"ok": True, "todo": {"id": todo["id"], "status": todo["status"],
                                    "plan_decision": todo.get("plan_decision")}}
    _store_idempotent(request, payload)
    return payload
