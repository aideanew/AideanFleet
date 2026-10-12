"""邮件提醒模块"""

from .smtp import send_email, test_email_config, load_env_config
from .triggers import (
    EventType,
    NotificationTrigger,
    get_trigger,
    notify_task_completed,
    notify_manager_quota_low,
    notify_worker_quota_low,
    notify_task_escalated,
    notify_task_failed,
    watch_events_loop,
)

__all__ = [
    "send_email",
    "test_email_config",
    "load_env_config",
    "EventType",
    "NotificationTrigger",
    "get_trigger",
    "notify_task_completed",
    "notify_manager_quota_low",
    "notify_worker_quota_low",
    "notify_task_escalated",
    "notify_task_failed",
    "watch_events_loop",
]
