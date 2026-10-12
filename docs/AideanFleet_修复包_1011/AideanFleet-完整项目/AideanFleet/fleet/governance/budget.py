"""预算管理器：三层预算池（任务/项目/日）+ 熔断器"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any

from .store import get_budget, upsert_budget, consume_budgets


@dataclass
class BudgetLimit:
    """单条预算限制"""
    level: str = "task"
    scope: str = ""
    limit_tokens: int = 0
    used_tokens: int = 0
    action: str = "pause"

    @property
    def remaining(self) -> int:
        return max(0, self.limit_tokens - self.used_tokens)

    @property
    def usage_pct(self) -> float:
        if self.limit_tokens <= 0:
            return 0.0
        return (self.used_tokens / self.limit_tokens) * 100

    @property
    def is_exceeded(self) -> bool:
        return self.limit_tokens > 0 and self.used_tokens >= self.limit_tokens

    @property
    def is_warning(self) -> bool:
        return self.limit_tokens > 0 and self.usage_pct >= 80


@dataclass
class BudgetExceeded(Exception):
    """预算超限异常"""
    level: str
    scope: str
    used: int
    limit: int
    action: str

    def __str__(self) -> str:
        return (
            f"Budget exceeded at {self.level}/{self.scope}: "
            f"{self.used}/{self.limit} tokens (action={self.action})"
        )


# 默认预算配置（当 .env 未配置时使用）
DEFAULT_BUDGETS = {
    "task": int(os.getenv("BUDGET_TASK_TOKENS", "200000")),
    "project": int(os.getenv("BUDGET_PROJECT_TOKENS", "2000000")),
    "daily": int(os.getenv("BUDGET_DAILY_TOKENS", "500000")),
}
DEFAULT_ACTION = os.getenv("BUDGET_ACTION", "pause")


class BudgetManager:
    """
    预算管理器
    - 三层预算池：task → project → daily
    - 超限动作：pause（默认）/ warn
    - 安全守则：配置缺失时按默认值执行，不放任无限消耗
    """

    def __init__(self):
        self._limits: dict[tuple[str, str], BudgetLimit] = {}

    def _load_from_config(self, level: str, scope: str) -> BudgetLimit:
        """从数据库加载预算配置，返回 BudgetLimit"""
        # 多个 Manager 共用数据库，读状态时不信任实例内的旧用量。
        key = (level, scope)
        row = get_budget(level, scope)
        if row:
            bl = BudgetLimit(
                level=level,
                scope=scope,
                limit_tokens=row.get("limit_tokens", 0),
                used_tokens=row.get("used_tokens", 0),
                action=row.get("action", DEFAULT_ACTION),
            )
        else:
            # 使用默认值，不放任无限消耗
            default_limit = DEFAULT_BUDGETS.get(level, DEFAULT_BUDGETS["task"])
            bl = BudgetLimit(
                level=level,
                scope=scope,
                limit_tokens=default_limit,
                used_tokens=0,
                action=DEFAULT_ACTION,
            )
            upsert_budget(
                level, scope,
                used_tokens=0,
                limit_tokens=default_limit,
                action=DEFAULT_ACTION,
            )

        self._limits[key] = bl
        return bl

    def check(self, task_id: str = "", project_id: str = "") -> BudgetLimit:
        """
        检查预算是否超限。
        顺序：task → project → daily
        """
        # 1. 检查任务级
        if task_id:
            task_limit = self._load_from_config("task", task_id)
            if task_limit.is_exceeded:
                raise BudgetExceeded(
                    level="task", scope=task_id,
                    used=task_limit.used_tokens, limit=task_limit.limit_tokens,
                    action=task_limit.action,
                )

        # 2. 检查项目级
        if project_id:
            proj_limit = self._load_from_config("project", project_id)
            if proj_limit.is_exceeded:
                raise BudgetExceeded(
                    level="project", scope=project_id,
                    used=proj_limit.used_tokens, limit=proj_limit.limit_tokens,
                    action=proj_limit.action,
                )

        # 3. 检查日级
        from datetime import date
        daily_scope = date.today().isoformat()
        daily_limit = self._load_from_config("daily", daily_scope)
        if daily_limit.is_exceeded:
            raise BudgetExceeded(
                level="daily", scope=daily_scope,
                used=daily_limit.used_tokens, limit=daily_limit.limit_tokens,
                action=daily_limit.action,
            )

        return daily_limit

    def consume(self, tokens: int, task_id: str = "", project_id: str = "") -> BudgetLimit:
        """三层原子扣款后检查是否超限（超限不撤销已发生的消费）。"""
        from datetime import date

        scopes = []
        if task_id:
            scopes.append(("task", task_id))
        if project_id:
            scopes.append(("project", project_id))
        scopes.append(("daily", date.today().isoformat()))
        consume_budgets(tokens, scopes, DEFAULT_BUDGETS, DEFAULT_ACTION)
        for key in scopes:
            self._limits.pop(key, None)
        return self.check(task_id=task_id, project_id=project_id)

    def get_status(self, task_id: str = "", project_id: str = "") -> dict[str, Any]:
        """获取当前预算状态"""
        result = {}
        if task_id:
            result["task"] = self._load_from_config("task", task_id).__dict__
        if project_id:
            result["project"] = self._load_from_config("project", project_id).__dict__
        from datetime import date
        daily_scope = date.today().isoformat()
        result["daily"] = self._load_from_config("daily", daily_scope).__dict__
        return result

    def set_limit(self, level: str, scope: str, limit_tokens: int, action: str = "pause") -> None:
        """设置预算限制"""
        upsert_budget(level, scope, limit_tokens=limit_tokens, action=action)
        self._limits.pop((level, scope), None)

    def reset(self, level: str, scope: str) -> None:
        """重置预算用量"""
        upsert_budget(level, scope, used_tokens=0)
        self._limits.pop((level, scope), None)

    def sync_from_events(self, aggregator: Any = None) -> int:
        """从 UsageAggregator 同步已聚合的用量到预算池"""
        if aggregator is None:
            from .usage import UsageAggregator
            aggregator = UsageAggregator()

        total_synced = 0

        # 同步任务级
        from .store import sum_usage
        task_rows = sum_usage(group_by="task_id")
        for row in task_rows:
            scope = row.get("period", "")
            if not scope:
                continue
            tl = self._load_from_config("task", scope)
            new_used = row.get("total_tokens", 0)
            if new_used > tl.used_tokens:
                tl.used_tokens = new_used
                upsert_budget("task", scope, used_tokens=tl.used_tokens,
                             limit_tokens=tl.limit_tokens, action=tl.action)
                total_synced += 1

        # 同步项目级
        proj_rows = sum_usage(group_by="project_id")
        for row in proj_rows:
            scope = row.get("period", "")
            if not scope:
                continue
            pl = self._load_from_config("project", scope)
            new_used = row.get("total_tokens", 0)
            if new_used > pl.used_tokens:
                pl.used_tokens = new_used
                upsert_budget("project", scope, used_tokens=pl.used_tokens,
                             limit_tokens=pl.limit_tokens, action=pl.action)
                total_synced += 1

        return total_synced
