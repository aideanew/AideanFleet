"""审批门管理器：三种场景触发审批（delete/overwrite、SMTP首次发送、预算超80%）"""

from __future__ import annotations

import os
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from .store import (
    create_approval, get_approval, list_pending_approvals,
    decide_approval, init_db,
)


# 审批超时：24 小时
APPROVAL_TIMEOUT_HOURS = int(os.getenv("APPROVAL_TIMEOUT_HOURS", "24"))


@dataclass
class ApprovalRequest:
    """审批请求"""
    approval_id: str = ""
    action_type: str = ""
    description: str = ""
    task_id: str = ""
    project_id: str = ""
    requested_by: str = "system"
    status: str = "pending"
    decision: str = ""
    decided_by: str = ""
    decided_at: str = ""
    created_at: str = ""
    expires_at: str = ""

    def __post_init__(self):
        if not self.approval_id:
            self.approval_id = f"appr-{uuid.uuid4().hex[:12]}"
        if not self.created_at:
            self.created_at = datetime.utcnow().isoformat()
        if not self.expires_at:
            self.expires_at = (
                datetime.utcnow() + timedelta(hours=APPROVAL_TIMEOUT_HOURS)
            ).isoformat()


@dataclass
class ApprovalDecision:
    """审批决定"""
    approved: bool
    approval_id: str
    decision: str  # "approve" or "reject"
    decided_by: str = "user"
    decided_at: str = ""


class ApprovalManager:
    """
    审批门管理器
    - 场景1：delete/overwrite 超出红线
    - 场景2：首次真实 SMTP 发送
    - 场景3：任务预算超 80% 阈值（仅告警，不阻断）
    - 超时：24h → 自动拒绝 + approval:expired 事件
    """

    # 触发审批的动作类型
    TRIGGER_ACTIONS = {
        "delete_overwrite": "delete/overwrite command outside redlines",
        "smtp_first_send": "first real SMTP send",
        "budget_warning": "task budget >80% threshold (warn only)",
    }

    def __init__(self):
        init_db()
        self._requests: dict[str, ApprovalRequest] = {}

    def request_approval(
        self,
        action_type: str,
        description: str = "",
        task_id: str = "",
        project_id: str = "",
        requested_by: str = "system",
    ) -> ApprovalRequest:
        """创建审批请求"""
        if action_type not in self.TRIGGER_ACTIONS:
            raise ValueError(
                f"Unknown action_type: {action_type}. "
                f"Valid: {list(self.TRIGGER_ACTIONS.keys())}"
            )

        req = ApprovalRequest(
            action_type=action_type,
            description=description or self.TRIGGER_ACTIONS[action_type],
            task_id=task_id,
            project_id=project_id,
            requested_by=requested_by,
        )

        create_approval(
            approval_id=req.approval_id,
            action_type=req.action_type,
            description=req.description,
            task_id=req.task_id,
            project_id=req.project_id,
            requested_by=req.requested_by,
            created_at=req.created_at,
            expires_at=req.expires_at,
        )
        self._requests[req.approval_id] = req
        return req

    def approve(self, approval_id: str, decided_by: str = "user") -> ApprovalDecision:
        """批准请求"""
        now = datetime.utcnow().isoformat()
        success = decide_approval(approval_id, "approve", decided_by, now)
        if success:
            return ApprovalDecision(
                approved=True, approval_id=approval_id,
                decision="approve", decided_by=decided_by, decided_at=now,
            )
        return ApprovalDecision(
            approved=False, approval_id=approval_id,
            decision="reject", decided_by=decided_by, decided_at=now,
        )

    def reject(self, approval_id: str, decided_by: str = "user") -> ApprovalDecision:
        """拒绝请求"""
        now = datetime.utcnow().isoformat()
        success = decide_approval(approval_id, "reject", decided_by, now)
        if success:
            return ApprovalDecision(
                approved=False, approval_id=approval_id,
                decision="reject", decided_by=decided_by, decided_at=now,
            )
        return ApprovalDecision(
            approved=False, approval_id=approval_id,
            decision="reject", decided_by=decided_by, decided_at=now,
        )

    def check_expired(self) -> list[str]:
        """检查并自动拒绝过期的审批请求，返回已过期的 approval_id 列表"""
        init_db()
        expired_ids = []
        now = datetime.utcnow()

        for req in list_pending_approvals():
            expires_str = req.get("expires_at", "")
            if not expires_str:
                continue
            try:
                expires_dt = datetime.fromisoformat(expires_str)
            except (ValueError, TypeError):
                continue

            if now > expires_dt:
                approval_id = req.get("approval_id", "")
                self.reject(approval_id, decided_by="system:timeout")
                expired_ids.append(approval_id)

        return expired_ids

    def get_status(self, approval_id: str) -> dict[str, Any] | None:
        """获取审批状态"""
        row = get_approval(approval_id)
        return row

    def list_pending(self) -> list[dict[str, Any]]:
        """列出所有待审批请求"""
        return list_pending_approvals()

    def request_delete_overwrite(
        self, task_id: str = "", project_id: str = "",
        description: str = "",
    ) -> ApprovalRequest:
        """请求 delete/overwrite 审批"""
        return self.request_approval(
            "delete_overwrite", description, task_id, project_id
        )

    def request_smtp_first_send(
        self, task_id: str = "", project_id: str = "",
        description: str = "",
    ) -> ApprovalRequest:
        """请求首次 SMTP 发送审批"""
        return self.request_approval(
            "smtp_first_send", description, task_id, project_id
        )

    def request_budget_warning(
        self, task_id: str = "", project_id: str = "",
        description: str = "",
    ) -> ApprovalRequest:
        """请求预算超 80% 告警（仅告警，不阻断）"""
        return self.request_approval(
            "budget_warning", description, task_id, project_id
        )
