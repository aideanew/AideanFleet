"""这是什么：Setup API（TASK-203，契约 api.json setup.*）。
身份边界（identity.json B1）：/api/setup/* 只接受回环来源（127.0.0.1/::1），否则 403——
即使 FLEET_CONSOLE_HOST 被改为 0.0.0.0。setup.* 免会话（首次运行用户尚无项目）。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from fleet.setup import core as setup_core
from fleet.console.loopback import client_host as _client_host
from fleet.console.loopback import is_loopback as _loopback

router = APIRouter(prefix="/api/setup", tags=["setup"])


def _forbidden():
    return JSONResponse({"ok": False, "error": "只能在安装 AideanFleet 的电脑上打开控制台",
                         "reason": "FORBIDDEN_NON_LOOPBACK"}, status_code=403)


def _error(reason: str, message: str, status: int, details: dict | None = None):
    body = {"ok": False, "error": message, "reason": reason}
    if details:
        body["details"] = details
    return JSONResponse(body, status_code=status)


@router.get("/status")
def setup_status(request: Request):
    if not _loopback(request):
        return _forbidden()
    return {"ok": True, "status": setup_core.status()}


@router.post("/install")
async def setup_install(request: Request):
    if not _loopback(request):
        return _forbidden()
    try:
        body = await request.json()
    except Exception:
        return _error("VALIDATION_FAILED", "请求体必须是 JSON 对象", 422)
    components = body.get("components") if isinstance(body, dict) else None
    mirror = str((body or {}).get("mirror") or "auto")
    if not isinstance(components, list) or not components:
        return _error("VALIDATION_FAILED", "components 必须是非空数组", 422)
    if mirror not in ("auto", "official", "cn"):
        return _error("VALIDATION_FAILED", "mirror 只允许 auto/official/cn", 422)
    known = {entry["name"] for entry in setup_core.load_manifest()["components"]}
    unknown = [name for name in components if name not in known]
    if unknown:
        return _error("VALIDATION_FAILED", f"未知组件: {unknown}", 422,
                      {"unknown": unknown})
    import platform as plat

    if plat.machine().lower() in ("arm64", "aarch64"):
        return _error("PLATFORM_UNSUPPORTED", "AideanFleet 安装器当前仅支持 x64 Windows", 422)
    setup_core.note_explicit([str(name) for name in components])
    try:
        job_id = setup_core.install_components([str(name) for name in components], mirror=mirror)
    except setup_core.InstallInProgress as exc:
        return JSONResponse({"ok": False, "error": str(exc), "reason": "INSTALL_IN_PROGRESS",
                             "details": {"job_id": exc.job_id}}, status_code=409)
    return {"ok": True, "job_id": job_id}


@router.get("/jobs/{job_id}")
def setup_job(request: Request, job_id: str):
    if not _loopback(request):
        return _forbidden()
    job = setup_core.read_job(job_id)
    if job is None:
        return _error("JOB_NOT_FOUND", f"作业不存在 {job_id}", 404)
    for step in job.get("steps", []):
        step.setdefault("log_tail", "")
        step.setdefault("error_code", None)
        step.setdefault("component", "")
        step.setdefault("state", "pending")
    return {"ok": True, "job_id": job_id, "state": job["state"], "steps": job["steps"]}
