"""邮件提醒模块测试（pytest 形式：return → assert，消除 PytestReturnNotNoneWarning）"""

from pathlib import Path

from fleet.notify.triggers import (
    EventType,
    NotificationTrigger,
    DEFAULT_CONFIG,
)


def test_event_types():
    """7 种事件类型必须全部已定义"""
    for type_str in (
        "task_started", "task_completed", "manager_quota_low",
        "worker_quota_low", "task_escalated", "daily_summary", "task_failed",
    ):
        EventType(type_str)  # 未定义会抛 ValueError


def test_default_config():
    """默认开关与 DEFAULT_CONFIG 声明一致"""
    expected_defaults = {
        EventType.TASK_STARTED: False,
        EventType.TASK_COMPLETED: True,
        EventType.MANAGER_QUOTA_LOW: True,
        EventType.WORKER_QUOTA_LOW: True,
        EventType.TASK_ESCALATED: True,
        EventType.DAILY_SUMMARY: False,
        EventType.TASK_FAILED: True,
    }
    for event_type, expected_enabled in expected_defaults.items():
        config = DEFAULT_CONFIG.get(event_type)
        assert config is not None, f"DEFAULT_CONFIG 缺少 {event_type.value}"
        assert config.default_enabled == expected_enabled, \
            f"{event_type.value} 默认值应为 {expected_enabled}"


def test_trigger_config(tmp_path, monkeypatch):
    """触发器默认配置与 DEFAULT_CONFIG 一致"""
    monkeypatch.chdir(tmp_path)
    trigger = NotificationTrigger("config/test_notifications.json")
    for event_type, expected_config in DEFAULT_CONFIG.items():
        assert trigger.is_enabled(event_type) == expected_config.default_enabled, \
            f"{event_type.value} 默认开关不符"


def test_trigger_set_enabled(tmp_path, monkeypatch):
    """开关设置后立即生效"""
    monkeypatch.chdir(tmp_path)
    trigger = NotificationTrigger("config/test_notifications_set.json")
    trigger.set_enabled(EventType.TASK_STARTED, True)
    assert trigger.is_enabled(EventType.TASK_STARTED) is True
    trigger.set_enabled(EventType.TASK_COMPLETED, False)
    assert trigger.is_enabled(EventType.TASK_COMPLETED) is False


def test_trigger_without_sender():
    """无发送回调时 trigger 返回失败而非抛异常"""
    trigger = NotificationTrigger()
    trigger.register_sender(None)
    trigger.set_enabled(EventType.TASK_COMPLETED, True)
    success, message = trigger.trigger(EventType.TASK_COMPLETED, "测试", "测试内容")
    assert success is False, f"无回调时应返回失败，实际 success={success}"
    assert "未注册发送回调" in message
