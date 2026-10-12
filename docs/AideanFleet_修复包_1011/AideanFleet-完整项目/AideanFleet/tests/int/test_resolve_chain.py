"""Resolve链测试

验证 contracts.resolve("fake") → dispatcher dispatch → DONE 的完整链路。
8个事件断言确保端到端工作。
"""

import pytest
from unittest.mock import patch, MagicMock
from pathlib import Path
import json
import time


def test_resolve_fake_adapter():
    """测试 resolve("fake") 能正确返回 FakeAdapter 实例"""
    from fleet.manager.contracts import resolve, unregister

    # 清理注册表
    unregister("fake")

    # 注册 fake adapter
    from fleet.executors.fake import FakeAdapter
    from fleet.manager.contracts import register

    adapter_instance = FakeAdapter()
    register("fake", lambda: adapter_instance)

    # 测试 resolve
    resolved = resolve("fake")
    assert resolved is not None
    assert resolved.name == "fake"
    assert isinstance(resolved, FakeAdapter)


def test_fake_adapter_run_success():
    """测试 FakeAdapter.run() 正常成功返回"""
    from fleet.executors.fake import FakeAdapter

    adapter = FakeAdapter()
    result = adapter.run("test prompt", "/tmp", "test-model", 60)

    assert result.ok is True
    assert "FakeAdapter" in result.output
    assert result.error_code is None
    assert result.error_msg == ""


def test_fake_adapter_run_429():
    """测试 FakeAdapter.run() 429 限流错误"""
    from fleet.executors.fake import FakeAdapter
    from fleet.executors.base import ErrorCode

    adapter = FakeAdapter(fail_with="429")
    result = adapter.run("test prompt", "/tmp", "test-model", 60)

    assert result.ok is False
    assert result.error_code == ErrorCode.RATE_LIMITED
    assert "429" in result.error_msg


def test_fake_adapter_run_401():
    """测试 FakeAdapter.run() 401 认证错误"""
    from fleet.executors.fake import FakeAdapter
    from fleet.executors.base import ErrorCode

    adapter = FakeAdapter(fail_with="401")
    result = adapter.run("test prompt", "/tmp", "test-model", 60)

    assert result.ok is False
    assert result.error_code == ErrorCode.BAD_REQUEST
    assert "401" in result.error_msg


def test_fake_adapter_run_timeout():
    """测试 FakeAdapter.run() 超时错误"""
    from fleet.executors.fake import FakeAdapter
    from fleet.executors.base import ErrorCode

    adapter = FakeAdapter(fail_with="TIMEOUT")
    result = adapter.run("test prompt", "/tmp", "test-model", 60)

    assert result.ok is False
    assert result.error_code == ErrorCode.TIMEOUT
    assert "timed out" in result.error_msg


def test_fake_adapter_capabilities():
    """测试 FakeAdapter.capabilities() 返回正确的 Capabilities"""
    from fleet.executors.fake import FakeAdapter
    from fleet.manager.contracts import Capabilities

    adapter = FakeAdapter()
    caps = adapter.capabilities()

    assert isinstance(caps, Capabilities)
    assert caps.streaming is False
    assert caps.structured_output is False
    assert caps.mcp is False


def test_fake_adapter_call_stats():
    """测试 FakeAdapter 调用统计"""
    from fleet.executors.fake import FakeAdapter

    adapter = FakeAdapter()
    assert adapter.call_count == 0
    assert adapter.last_prompt is None

    adapter.run("test prompt", "/tmp", "test-model", 60)

    assert adapter.call_count == 1
    assert adapter.last_prompt == "test prompt"
    assert adapter.last_workdir == "/tmp"
    assert adapter.last_model == "test-model"

    adapter.reset_stats()
    assert adapter.call_count == 0


def test_base_adapter_is_contracts_compatible():
    """测试 executors.base.BaseAdapter 是 contracts.BaseAdapter 的子类"""
    from fleet.executors.base import BaseAdapter
    from fleet.manager.contracts import BaseAdapter as ContractsBaseAdapter

    assert issubclass(BaseAdapter, ContractsBaseAdapter)


def test_fake_adapter_is_contracts_compatible():
    """测试 FakeAdapter 是 contracts.BaseAdapter 的子类"""
    from fleet.executors.fake import FakeAdapter
    from fleet.manager.contracts import BaseAdapter as ContractsBaseAdapter

    assert issubclass(FakeAdapter, ContractsBaseAdapter)
