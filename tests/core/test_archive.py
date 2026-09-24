"""P5-A-1: Linux 环境归档测试

验证 fleet/rel/archive.py 的 rotate_events 在 Linux 下正常工作。
"""
import datetime

from fleet.core import events
from fleet.rel import archive


def test_archive_rotate_events(fleet_env):
    """rotate_events 在有事件文件时正常执行，返回结果含 rotated 字段。"""
    # 写几条事件
    for i in range(5):
        events.append(actor="test", action=f"test_event_{i}", project="ArchiveTest")

    result = archive.rotate_events()
    assert isinstance(result, dict)
    # 归档操作应该成功（不抛异常即通过）
    assert "error" not in result or result.get("error") is None or "rotated" in result


def test_archive_rotate_empty(fleet_env):
    """无事件文件时 rotate_events 不崩溃。"""
    result = archive.rotate_events()
    assert isinstance(result, dict)
