"""这是什么：控制台 FastAPI 服务的路由兼容性测试（会话闸门 / 契约响应形态 / GBK 回退 / 旧字段）。"""

from __future__ import annotations

import json

from fastapi.testclient import TestClient

from fleet.console import server as console_server
from fleet.core import db, events


def client() -> TestClient:
    return TestClient(console_server.app)


def login(tc: TestClient, project: str = "P-001") -> None:
    response = tc.post("/api/session", json={"project": project})
    assert response.status_code == 200
    token = response.json()["token"]
    tc.headers.update({"Authorization": f"Bearer {token}"})


def test_health_exact_contract_shape(fleet_env):
    tc = client()
    response = tc.get("/api/health")
    assert response.status_code == 200
    payload = response.json()
    assert set(payload.keys()) == {"version", "db", "events", "config", "frontend_built"}  # 契约 §1：五键（frontend_built 为 P0-B-3 新增）
    assert payload["version"] == "0.3.0"  # REL-01：版本统一（pyproject.toml 同步）
    assert payload["db"] and payload["events"] and payload["config"]


def test_api_requires_session(fleet_env):
    tc = client()
    for path in ("/api/plan", "/api/events", "/api/config/basic"):
        response = tc.get(path)
        assert response.status_code == 401
        assert response.json()["ok"] is False


def test_session_create_with_cookie_and_gbk_body(fleet_env, project):
    tc = client()
    # GBK 编码的中文请求体必须被兼容解析
    gbk_body = json.dumps({"project": "P-001"}, ensure_ascii=False).encode("gbk")
    response = tc.post("/api/session", content=gbk_body, headers={"Content-Type": "application/json"})
    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True and payload["project"] == project and payload["expires_in"] > 0
    assert "fleet_token" in response.cookies  # cookie 回退通道

    # 用 cookie（而不是 Bearer）访问受保护接口
    tc2 = client()
    tc2.cookies.set("fleet_token", payload["token"])
    assert tc2.get("/api/session").status_code == 200


def test_session_rejects_unknown_project(fleet_env):
    tc = client()
    response = tc.post("/api/session", json={"project": "P-404"})
    assert response.status_code == 400


def test_plan_and_events_contract(fleet_env, project):
    from tests.core.stubs import make_task

    make_task(project, "T-001")
    db.transition_and_log("T-001", "ASSIGNED", actor="tester")
    tc = client()
    login(tc)

    plan_payload = tc.get("/api/plan", params={"project": project}).json()
    assert plan_payload["ok"] is True and plan_payload["project"] == project
    assert isinstance(plan_payload["阶段"], list) and isinstance(plan_payload["tasks"], list)
    task = next(item for item in plan_payload["tasks"] if item["id"] == "T-001")
    assert task["state"] == "ASSIGNED"
    # 旧前端兼容字段仍在
    assert {"progress", "total", "done", "percent"} <= set(plan_payload.keys())

    events_payload = tc.get("/api/events", params={"project": project, "since": "0"}).json()
    assert events_payload["ok"] is True and events_payload["seq"] >= 1
    row = events_payload["events"][0]
    assert {"seq", "timestamp", "actor", "action", "taskId", "summary", "url", "project", "extra"} <= set(row.keys())


def test_plan_unknown_project_is_200_business_error(fleet_env, project):
    tc = client()
    login(tc, project="P-001")
    response = tc.get("/api/plan", params={"project": "P-999"})
    assert response.status_code == 200
    assert response.json() == {"ok": False, "reason": "project_not_found", "project": "P-999"}


def test_launch_event_contract(fleet_env, project):
    tc = client()
    login(tc)
    # 缺字段 -> 400 + missing 列表，且不写事件流
    response = tc.post("/api/launch-event", json={"project": project})
    assert response.status_code == 400
    assert response.json()["reason"] == "missing_fields"
    assert set(response.json()["missing"]) == {"phase", "detail"}
    assert events.read(project=project) == []

    # 合法 -> action = launch:<phase>
    ok_response = tc.post("/api/launch-event", json={
        "project": project, "phase": "dispatch_begins", "detail": "开始派工",
        "role": "manager", "cli": "hermes", "model": "demo-1", "taskId": "T-001",
    })
    assert ok_response.status_code == 200
    payload = ok_response.json()
    assert payload["ok"] is True and payload["action"] == "launch:dispatch_begins"
    row = events.read(project=project)[0]
    assert row["summary"] == "开始派工" and row["extra"]["model"] == "demo-1"

    # 未知项目 -> 200 业务错误
    bad = tc.post("/api/launch-event", json={"project": "P-404", "phase": "x", "detail": "y"})
    assert bad.status_code == 200 and bad.json()["reason"] == "project_not_found"


def test_config_sections_and_aliases(fleet_env, project):
    tc = client()
    login(tc)
    # 七契约段可读
    for section in ("basic", "model_pool", "roles", "executors", "email", "notify", "request"):
        payload = tc.get(f"/api/config/{section}").json()
        assert payload["ok"] is True and payload["section"] == section
    # model_pool 的 api_key 永远是占位
    models = tc.get("/api/config/model_pool").json()["data"]["models"]
    assert all(item["api_key"].startswith("${") or item["api_key"] == "" for item in models)

    # 旧段名别名
    assert tc.get("/api/config/settings").json()["section"] == "basic"
    assert tc.get("/api/config/models").json()["section"] == "model_pool"

    # 未知段 -> 400 + known 列表
    unknown = tc.get("/api/config/foo").json()
    assert unknown["reason"] == "unknown_section" and len(unknown["known"]) == 8  # REL-01：settings 段入列

    # 写入与 ignored 语义
    saved = tc.post("/api/config/notify", json={"data": {"on_task_start": True, "bogus_key": 1}}).json()
    assert saved["ok"] is True and saved["applied"] == {"on_task_start": True}
    assert saved["ignored"] == ["bogus_key"]

    # 明文密钥拒绝写盘（16 位大写形态命中 _SECRET_SHAPES，不引入明文密钥字面量）
    plaintext = tc.post("/api/config/model_pool", json={
        "data": {"models": [{"name": "x", "level": 1, "base_url": "u", "model_id": "m", "api_key": "ABCDEF0123456789"}]}
    }).json()
    assert plaintext["reason"] == "plaintext_secret_rejected"


def test_mode_and_confirm_and_control(fleet_env, project):
    from tests.core.stubs import make_task

    tc = client()
    login(tc)
    # 旧值 confirm 兼容映射为 step
    mode = tc.post("/api/mode", json={"mode": "confirm"}).json()
    assert mode["ok"] is True and mode["effective"] == "step"
    assert console_server.bus.mode == "step"

    make_task(project, "T-001")
    confirmed = tc.post("/api/confirm", json={"decision": "confirm"}).json()
    assert confirmed["ok"] is True
    assert any(row["action"] == "step_confirm" for row in events.read(project=project))

    # ESCALATED 人工放行
    for target in ("ASSIGNED", "DOING", "SUBMITTED", "REVIEWING"):
        db.transition("T-001", target)
    for _ in range(4):
        db.bump_rework("T-001")
    released = tc.post("/api/control/confirm", json={"taskId": "T-001", "note": "放行"}).json()
    assert released["ok"] is True and released["successor"] == "T-001-R1"

    # 未知任务
    missing = tc.post("/api/control/confirm", json={"taskId": "T-404"}).json()
    assert missing["reason"] == "task_not_found"


def test_task_detail_and_dispatch_409(fleet_env, project):
    from tests.core.stubs import make_task

    make_task(project, "T-001")
    for target in ("ASSIGNED", "DOING", "SUBMITTED", "REVIEWING", "DONE"):
        db.transition_and_log("T-001", target, actor="tester")
    tc = client()
    login(tc)

    detail = tc.get("/api/tasks/T-001").json()
    assert detail["ok"] is True and detail["task"]["task_id"] == "T-001"

    # 终态再派工 -> 409 invalid_transition
    conflict = tc.post("/tasks/T-001/dispatch")
    assert conflict.status_code == 409
    payload = conflict.json()
    assert payload["reason"] == "invalid_transition" and payload["from"] == "DONE"

    # 不存在的任务
    absent = tc.get("/api/tasks/T-999").json()
    assert absent == {"ok": False, "reason": "task_not_found", "taskId": "T-999"}


def test_notify_test_unwired_503(fleet_env, project, monkeypatch):
    """fleet.notify 模块不可用时 503 + reason=notify接线未完成（try import 探测，INT-03 交付后自动接通）。"""
    import sys

    tc = client()
    login(tc)
    # 配置缺失 → 200 业务错误（不发送）
    missing = tc.post("/api/notify/test").json()
    assert missing["ok"] is False and "邮件配置不完整" in missing["error"]
    # 模块不可用 → 503 + 机器可读 reason（需先补齐 email 配置才能走到 try import）
    from fleet.core import config as fleet_config

    fleet_config.save("email", {"sender": "ops@example.com", "receiver": "ops@example.com",
                                "host": "smtp.example.com", "auth_code": "${SMTP_AUTH_CODE}", "port": 465})
    monkeypatch.setenv("SMTP_AUTH_CODE", "dummy-not-a-real-key")  # ${VAR} 解析需要环境变量在位
    monkeypatch.setitem(sys.modules, "fleet.notify.smtp", None)  # None = import 必然失败
    blocked = tc.post("/api/notify/test")
    assert blocked.status_code == 503
    body = blocked.json()
    assert body["ok"] is False and body["reason"] == "notify接线未完成"
