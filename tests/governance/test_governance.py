"""GOV-01 治理层测试"""

import json
import os
import tempfile
import threading
from datetime import datetime, timedelta
from pathlib import Path

import pytest

# 确保项目根目录在 sys.path
import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent))


@pytest.fixture(autouse=True)
def _isolated_db(tmp_path):
    """每个测试使用独立的临时数据目录，避免数据库残留"""
    old_env = os.environ.get("FLEET_DATA_DIR")
    os.environ["FLEET_DATA_DIR"] = str(tmp_path)
    # 重置 store 模块的缓存
    import fleet.governance.store as store_mod
    store_mod._db_path = None
    # 确保 init_db 被调用
    from fleet.governance.store import init_db
    init_db()
    try:
        yield
    finally:
        if old_env is not None:
            os.environ["FLEET_DATA_DIR"] = old_env
        else:
            os.environ.pop("FLEET_DATA_DIR", None)
        store_mod._db_path = None


from fleet.governance.store import (
    init_db, record_usage, query_usage, sum_usage,
    get_budget, upsert_budget,
    create_approval, get_approval, list_pending_approvals, decide_approval,
)
from fleet.governance.usage import UsageAggregator, scan_events_file, _extract_usage_from_event
from fleet.governance.budget import BudgetManager, BudgetExceeded, BudgetLimit, DEFAULT_BUDGETS
from fleet.governance.approval import ApprovalManager, ApprovalRequest, ApprovalDecision, APPROVAL_TIMEOUT_HOURS
from fleet.governance.report import ReportGenerator, UsageReport


# ─── Store 层测试 ───

class TestStoreInit:
    def test_init_db_creates_tables(self):
        """init_db 不报错且可重复调用"""
        init_db()
        init_db()


class TestStoreUsage:
    def test_record_and_query(self):
        """写入一条用量并查询"""
        record_usage(
            task_id="t-test-rq-001",
            project_id="proj-test",
            model="claude-3",
            prompt_tokens=100,
            completion_tokens=50,
            total_tokens=150,
            timestamp="2026-09-15T10:00:00",
        )
        rows = query_usage(task_id="t-test-rq-001")
        assert len(rows) >= 1
        assert rows[-1]["prompt_tokens"] == 100
        assert rows[-1]["total_tokens"] == 150

    def test_sum_by_task(self):
        """按任务聚合"""
        record_usage(task_id="t-agg-003", total_tokens=200, timestamp="2026-09-15T11:00:00")
        record_usage(task_id="t-agg-003", total_tokens=300, timestamp="2026-09-15T11:01:00")
        rows = sum_usage(group_by="task_id", task_id="t-agg-003")
        assert len(rows) == 1
        assert rows[0]["total_tokens"] == 500


class TestStoreBudget:
    def test_upsert_and_get(self):
        """预算 upsert"""
        upsert_budget("task", "t-budget-001", limit_tokens=100000, used_tokens=0)
        row = get_budget("task", "t-budget-001")
        assert row is not None
        assert row["limit_tokens"] == 100000

    def test_upsert_update(self):
        """预算更新"""
        upsert_budget("task", "t-budget-002", limit_tokens=50000, used_tokens=0)
        upsert_budget("task", "t-budget-002", used_tokens=10000)
        row = get_budget("task", "t-budget-002")
        assert row["used_tokens"] == 10000


class TestStoreApproval:
    def test_create_and_decide(self):
        """审批创建与决定"""
        create_approval(
            approval_id="appr-test-001",
            action_type="delete_overwrite",
            description="test delete",
            created_at=datetime.now().isoformat(),
        )
        row = get_approval("appr-test-001")
        assert row is not None
        assert row["status"] == "pending"

        ok = decide_approval("appr-test-001", "approve", "tester", datetime.now().isoformat())
        assert ok is True
        row = get_approval("appr-test-001")
        assert row["status"] == "approve"

    def test_list_pending(self):
        """列出待审批"""
        create_approval(
            approval_id="appr-pend-001",
            action_type="smtp_first_send",
            created_at=datetime.now().isoformat(),
        )
        pending = list_pending_approvals()
        assert any(p["approval_id"] == "appr-pend-001" for p in pending)


# ─── Usage 聚合测试 ───

class TestUsageAggregator:
    def test_extract_usage_from_event(self):
        """从事件提取 usage"""
        event = {
            "action": "model:call",
            "usage": {
                "prompt_tokens": 100,
                "cached_tokens": 10,
                "completion_tokens": 50,
                "total_tokens": 150,
            }
        }
        result = _extract_usage_from_event(event)
        assert result is not None
        assert result["prompt_tokens"] == 100
        assert result["completion_tokens"] == 50
        assert result["total_tokens"] == 150
        assert result["unknown_usage"] == 0

    def test_extract_usage_no_usage_field(self):
        """无 usage 字段时视为 0"""
        event = {"action": "model:call"}
        result = _extract_usage_from_event(event)
        assert result is not None
        assert result["unknown_usage"] == 1
        assert result["total_tokens"] == 0

    def test_extract_usage_non_model_call(self):
        """非 model:call 事件返回 None"""
        event = {"action": "chat"}
        result = _extract_usage_from_event(event)
        assert result is None

    def test_scan_events_file(self):
        """扫描 events.jsonl"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False, encoding="utf-8") as f:
            f.write(json.dumps({
                "action": "model:call",
                "timestamp": "2026-09-15T10:00:00",
                "usage": {"prompt_tokens": 200, "completion_tokens": 100, "total_tokens": 300},
                "meta": {"task_id": "t-scan-001", "model": "claude-3"},
            }) + "\n")
            f.write(json.dumps({
                "action": "chat",
                "timestamp": "2026-09-15T10:01:00",
            }) + "\n")
            tmp_path = Path(f.name)

        try:
            count = scan_events_file(tmp_path)
            assert count == 1  # 只有 model:call 被计入
        finally:
            tmp_path.unlink()

    def test_by_task(self):
        """按任务查询"""
        agg = UsageAggregator()
        record_usage(task_id="t-agg-task", total_tokens=500, timestamp="2026-09-15T12:00:00")
        result = agg.by_task("t-agg-task")
        assert result["total_tokens"] == 500


# ─── Budget 熔断测试 ───

class TestBudgetManager:
    def test_default_budget_exists(self):
        """默认预算配置存在"""
        assert "task" in DEFAULT_BUDGETS
        assert "project" in DEFAULT_BUDGETS
        assert "daily" in DEFAULT_BUDGETS
        assert DEFAULT_BUDGETS["task"] == 200000

    def test_budget_limit_properties(self):
        """BudgetLimit 属性"""
        bl = BudgetLimit(level="task", scope="t1", limit_tokens=1000, used_tokens=500)
        assert bl.remaining == 500
        assert bl.usage_pct == 50.0
        assert not bl.is_exceeded
        assert not bl.is_warning

    def test_budget_limit_exceeded(self):
        """BudgetLimit 超限"""
        bl = BudgetLimit(level="task", scope="t1", limit_tokens=1000, used_tokens=1000)
        assert bl.is_exceeded
        assert bl.remaining == 0

    def test_budget_limit_warning(self):
        """BudgetLimit 告警（80%）"""
        bl = BudgetLimit(level="task", scope="t1", limit_tokens=1000, used_tokens=850)
        assert bl.is_warning
        assert not bl.is_exceeded

    def test_consume_and_check(self):
        """消费并检查"""
        bm = BudgetManager()
        bm.set_limit("task", "t-consume-001", limit_tokens=1000)
        bm.consume(100, task_id="t-consume-001")
        status = bm.get_status(task_id="t-consume-001")
        assert "task" in status

    def test_budget_exceeded_raises(self):
        """超限抛出 BudgetExceeded"""
        bm = BudgetManager()
        bm.set_limit("task", "t-exceed-001", limit_tokens=100)
        with pytest.raises(BudgetExceeded) as exc_info:
            bm.consume(100, task_id="t-exceed-001")
        assert exc_info.value.level == "task"
        assert exc_info.value.scope == "t-exceed-001"

    def test_budget_reset(self):
        """重置预算"""
        bm = BudgetManager()
        bm.set_limit("task", "t-reset-001", limit_tokens=100)
        bm.consume(50, task_id="t-reset-001")
        bm.reset("task", "t-reset-001")
        row = get_budget("task", "t-reset-001")
        assert row["used_tokens"] == 0


# ─── Approval 审批门测试 ───

class TestApprovalManager:
    def test_request_approval(self):
        """创建审批请求"""
        am = ApprovalManager()
        req = am.request_delete_overwrite(task_id="t-approve-001")
        assert req.approval_id.startswith("appr-")
        assert req.action_type == "delete_overwrite"
        assert req.status == "pending"

    def test_approve(self):
        """批准"""
        am = ApprovalManager()
        req = am.request_smtp_first_send()
        decision = am.approve(req.approval_id)
        assert decision.approved is True
        assert decision.decision == "approve"

    def test_reject(self):
        """拒绝"""
        am = ApprovalManager()
        req = am.request_budget_warning()
        decision = am.reject(req.approval_id)
        assert decision.approved is False
        assert decision.decision == "reject"

    def test_invalid_action_type(self):
        """无效 action_type 抛出异常"""
        am = ApprovalManager()
        with pytest.raises(ValueError, match="Unknown action_type"):
            am.request_approval("invalid_type")

    def test_check_expired(self):
        """过期自动拒绝"""
        am = ApprovalManager()
        # 创建一个已过期的请求（使用 utcnow 确保时区一致）
        req = ApprovalRequest(
            action_type="delete_overwrite",
            expires_at=(datetime.utcnow() - timedelta(hours=1)).isoformat(),
        )
        create_approval(
            approval_id=req.approval_id,
            action_type=req.action_type,
            description=req.description,
            created_at=req.created_at,
            expires_at=req.expires_at,
        )
        expired = am.check_expired()
        assert req.approval_id in expired

    def test_list_pending(self):
        """列出待审批"""
        am = ApprovalManager()
        am.request_delete_overwrite(task_id="t-list-001")
        am.request_smtp_first_send(task_id="t-list-002")
        pending = am.list_pending()
        assert len(pending) >= 2


# ─── Report 报表测试 ───

class TestReportGenerator:
    def test_generate_daily(self):
        """生成日报"""
        rg = ReportGenerator()
        report = rg.generate_daily()
        assert report.period.startswith("daily:")
        assert isinstance(report.summary, dict)
        assert isinstance(report.pending_approvals, int)

    def test_summary_dict(self):
        """报表转字典"""
        rg = ReportGenerator()
        report = rg.generate_daily()
        d = rg.summary_dict(report)
        assert "period" in d
        assert "total_tokens" in d
        assert "budget_status" in d

    def test_generate_for_task(self):
        """任务级报表"""
        rg = ReportGenerator()
        report = rg.generate_for_task("t-report-001")
        assert report.period == "task:t-report-001"
