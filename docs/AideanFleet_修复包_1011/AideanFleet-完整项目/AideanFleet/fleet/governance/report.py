"""报表生成器：生成治理层使用量报表"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from datetime import date

from .usage import UsageAggregator
from .budget import BudgetManager
from .approval import ApprovalManager
from .store import init_db


@dataclass
class UsageReport:
    """用量报表"""
    period: str  # "daily" / "weekly" / "monthly"
    generated_at: str
    summary: dict[str, Any]
    by_task: list[dict[str, Any]]
    by_project: list[dict[str, Any]]
    by_model: list[dict[str, Any]]
    budget_status: dict[str, Any]
    pending_approvals: int


class ReportGenerator:
    """报表生成器"""

    def __init__(self):
        init_db()
        self._usage = UsageAggregator()
        self._budget = BudgetManager()
        self._approval = ApprovalManager()

    def generate_daily(self, target_date: str | None = None) -> UsageReport:
        """生成日报"""
        if target_date is None:
            target_date = date.today().isoformat()

        summary = self._usage.total(since=target_date)
        by_model = self._usage.by_model(since=target_date)
        budget_status = self._budget.get_status()
        pending = self._approval.list_pending()

        return UsageReport(
            period=f"daily:{target_date}",
            generated_at=date.today().isoformat(),
            summary=summary,
            by_task=[],
            by_project=[],
            by_model=by_model,
            budget_status=budget_status,
            pending_approvals=len(pending),
        )

    def generate_for_task(self, task_id: str) -> UsageReport:
        """生成任务级报表"""
        summary = self._usage.by_task(task_id)
        budget_status = self._budget.get_status(task_id=task_id)
        pending = self._approval.list_pending()

        return UsageReport(
            period=f"task:{task_id}",
            generated_at=date.today().isoformat(),
            summary=summary,
            by_task=[summary],
            by_project=[],
            by_model=[],
            budget_status=budget_status,
            pending_approvals=len(pending),
        )

    def generate_for_project(self, project_id: str) -> UsageReport:
        """生成项目级报表"""
        summary = self._usage.by_project(project_id)
        budget_status = self._budget.get_status(project_id=project_id)
        pending = self._approval.list_pending()

        return UsageReport(
            period=f"project:{project_id}",
            generated_at=date.today().isoformat(),
            summary=summary,
            by_task=[],
            by_project=[summary],
            by_model=[],
            budget_status=budget_status,
            pending_approvals=len(pending),
        )

    def summary_dict(self, report: UsageReport) -> dict[str, Any]:
        """将报表转为字典"""
        return {
            "period": report.period,
            "generated_at": report.generated_at,
            "total_tokens": report.summary.get("total_tokens", 0),
            "prompt_tokens": report.summary.get("prompt_tokens", 0),
            "completion_tokens": report.summary.get("completion_tokens", 0),
            "call_count": report.summary.get("call_count", 0),
            "budget_status": report.budget_status,
            "pending_approvals": report.pending_approvals,
        }
