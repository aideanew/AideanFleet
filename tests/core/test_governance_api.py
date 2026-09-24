"""审批中心 / 成本面板 数据源 HTTP 契约测试（UI-03R · 主题 9.5 补全）。

覆盖 server.py 新挂载的治理层路由：
  GET  /api/approvals[?project=]
  GET  /api/approvals/{id}
  POST /api/approvals/{id}/approve
  POST /api/approvals/{id}/reject
  GET  /api/usage/total[?since=]
  GET  /api/usage/by_date[?since=]
  GET  /api/budget[?task_id=&project_id=]
  POST /api/budget
"""

from __future__ import annotations

from fastapi.testclient import TestClient
import pytest

from fleet.console import server as console_server
from fleet.governance import approval as gov_approval, usage as gov_usage, budget as gov_budget, store as gov_store


def client() -> TestClient:
    return TestClient(console_server.app)


def login(tc: TestClient, project: str = "P-001") -> None:
    response = tc.post("/api/session", json={"project": project})
    assert response.status_code == 200
    tc.headers.update({"Authorization": f"Bearer {response.json()['token']}"})


def _reset_gov(monkeypatch, tmp_path):
    """治理层路由在进程内持有单例，跨测试必须重置 store 缓存并切换数据目录。"""
    monkeypatch.setenv("FLEET_DATA_DIR", str(tmp_path))
    gov_store._db_path = None
    gov_store.init_db()
    console_server._approval_manager = gov_approval.ApprovalManager()
    console_server._budget_manager = gov_budget.BudgetManager()
    console_server._usage_aggregator = gov_usage.UsageAggregator()


def test_approvals_requires_session(fleet_env, project, monkeypatch):
    _reset_gov(monkeypatch, fleet_env["data"])
    tc = client()
    assert tc.get("/api/approvals").status_code == 401
    login(tc)
    assert tc.get("/api/approvals").status_code == 200


def test_approvals_lifecycle(fleet_env, project, monkeypatch):
    _reset_gov(monkeypatch, fleet_env["data"])
    tc = client()
    login(tc)

    manager = console_server._approval_manager
    req = manager.request_smtp_first_send(task_id="T-001", project_id=project)

    listing = tc.get("/api/approvals", params={"project": project}).json()
    assert listing["ok"] is True and listing["pending"] == 1
    row = listing["approvals"][0]
    assert row["approval_id"] == req.approval_id
    assert row["action_type"] == "smtp_first_send"
    assert row["status"] == "pending"

    detail = tc.get(f"/api/approvals/{req.approval_id}").json()
    assert detail["ok"] is True and detail["approval"]["approval_id"] == req.approval_id

    missing = tc.get("/api/approvals/appr-not-exist").json()
    assert missing == {"ok": False, "reason": "approval_not_found", "approvalId": "appr-not-exist"}

    approved = tc.post(f"/api/approvals/{req.approval_id}/approve").json()
    assert approved["ok"] is True and approved["decision"] == "approve"
    assert approved["approval_id"] == req.approval_id

    after = tc.get("/api/approvals").json()
    assert after["pending"] == 0


def test_approvals_reject(fleet_env, project, monkeypatch):
    _reset_gov(monkeypatch, fleet_env["data"])
    tc = client()
    login(tc)
    req = console_server._approval_manager.request_budget_warning(task_id="T-002", project_id=project)
    rejected = tc.post(f"/api/approvals/{req.approval_id}/reject").json()
    assert rejected["ok"] is True and rejected["decision"] == "reject"
    # 前端契约口径：已决记录 status 为 "rejected"（store.decide_approval 写入 status=decision）
    status = tc.get(f"/api/approvals/{req.approval_id}").json()["approval"]
    assert status["decision"] == "reject" and status["status"] in ("rejected", "reject")


def test_usage_totals_and_by_date(fleet_env, project, monkeypatch):
    _reset_gov(monkeypatch, fleet_env["data"])
    tc = client()
    login(tc)

    gov_usage.record_manual_usage(task_id="T-001", project_id=project, prompt_tokens=100,
                                  completion_tokens=50, total_tokens=150, cached_tokens=10)
    gov_usage.record_manual_usage(task_id="T-002", project_id=project, prompt_tokens=200,
                                  completion_tokens=100, total_tokens=300, cached_tokens=20)

    total = tc.get("/api/usage/total").json()
    assert total == {"ok": True, "prompt_tokens": 300, "completion_tokens": 150,
                     "total_tokens": 450, "call_count": 2}

    by_date = tc.get("/api/usage/by_date").json()
    assert by_date["ok"] is True
    rows = by_date["rows"]
    assert len(rows) == 1
    assert rows[0]["period"] == _today_str()
    assert rows[0]["total_tokens"] == 450
    # sum_usage(group_by="date") 聚合列含 prompt/completion/total/call/unknown，缓存命中原样透传
    assert rows[0]["cached_tokens"] == 30


def _today_str() -> str:
    """与 fleet/governance/usage.py 的记录口径对齐：period 按 UTC 日期聚合。
    用本地 date.today() 断言会在北京时间 0:00-8:00（UTC 仍是前一天）产生假失败。"""
    from datetime import datetime
    return datetime.utcnow().date().isoformat()


def test_budget_status_defaults_and_set(fleet_env, project, monkeypatch):
    _reset_gov(monkeypatch, fleet_env["data"])
    tc = client()
    login(tc)

    status = tc.get("/api/budget", params={"task_id": "T-001", "project_id": project}).json()
    assert status["ok"] is True
    assert set(("task", "project", "daily")) <= set(status.keys())
    assert status["task"]["scope"] == "T-001"
    assert status["task"]["limit_tokens"] == 200_000  # DEFAULT_BUDGETS
    assert status["project"]["scope"] == project
    assert status["daily"]["limit_tokens"] == 500_000

    updated = tc.post("/api/budget", params={
        "level": "task", "scope": "T-001", "limit_tokens": 1000, "action": "pause",
    }).json()
    assert updated["ok"] is True and updated["limit_tokens"] == 1000

    rechecked = tc.get("/api/budget", params={"task_id": "T-001", "project_id": project}).json()
    assert rechecked["task"]["limit_tokens"] == 1000

    # 会话项目兜底：不传 project_id 时取当前会话项目 P-001（.env basic.default_project 兜底其次）
    fallback = tc.get("/api/budget").json()
    assert fallback["ok"] is True
    assert fallback["project"]["scope"] == project  # 会话项目 P-001，而不是 .env 的 default_project

    bad = tc.post("/api/budget", params={"level": "bogus", "scope": "X", "limit_tokens": 1}).json()
    assert bad["ok"] is False


def test_budget_consume_exceeded_visible(fleet_env, project, monkeypatch):
    """budget:exceeded 端到端联动：consume 逼近阈值后 /api/budget 必须如实反映 used/limit。

    口径对齐前端 governance.ts::budgetIsWarning（>=80% 预警）与 budgetIsExceeded（used>=limit 熔断）。
    """
    _reset_gov(monkeypatch, fleet_env["data"])
    tc = client()
    login(tc)

    tc.post("/api/budget", params={"level": "task", "scope": "T-009", "limit_tokens": 100, "action": "pause"})
    console_server._budget_manager.consume(tokens=60, task_id="T-009", project_id=project)
    status = tc.get("/api/budget", params={"task_id": "T-009", "project_id": project}).json()
    assert status["task"]["used_tokens"] == 60
    assert status["task"]["limit_tokens"] == 100
    # 60% < 80%：预警未触发
    assert not (status["task"]["limit_tokens"] > 0 and status["task"]["used_tokens"] / status["task"]["limit_tokens"] * 100 >= 80)

    console_server._budget_manager.consume(tokens=25, task_id="T-009", project_id=project)
    status = tc.get("/api/budget", params={"task_id": "T-009", "project_id": project}).json()
    # 85% >= 80%：预警触发（前端徽章「接近上限」）
    assert status["task"]["used_tokens"] == 85
    assert status["task"]["limit_tokens"] > 0 and status["task"]["used_tokens"] / status["task"]["limit_tokens"] * 100 >= 80

    # 熔断联动：consume 到 110/100 时库内 check 抛 BudgetExceeded（预算池硬熔断，库内行为）；
    # 但 /api/budget 读取侧只读 SQLite 行，如实呈现超限数值（前端「已熔断」红色 = used>=limit 派生）。
    # consume 的 upsert 在抛异常前已把 used=110 写入 SQLite，断言异常捕获后读库验证呈现。
    with pytest.raises(gov_budget.BudgetExceeded) as exc_info:
        console_server._budget_manager.consume(tokens=25, task_id="T-009", project_id=project)
    assert exc_info.value.level == "task" and exc_info.value.scope == "T-009"
    assert exc_info.value.used == 110 and exc_info.value.limit == 100
    # 清掉 BudgetManager 内存缓存，使 /api/budget 重读 SQLite
    console_server._budget_manager._limits.pop("T-009", None)
    status = tc.get("/api/budget", params={"task_id": "T-009", "project_id": project}).json()
    assert status["task"]["used_tokens"] == 110
    assert status["task"]["used_tokens"] >= status["task"]["limit_tokens"]  # 前端 budgetIsExceeded 口径
