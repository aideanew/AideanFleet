"""Fake执行体适配器测试（pytest 形式：return → assert，消除 PytestReturnNotNoneWarning）"""

import inspect

from fleet.executors import FakeAdapter, ErrorCode, Capabilities
from fleet.executors.base import ADAPTER_REGISTRY, get_adapter, BaseAdapter


def test_fake_adapter_success():
    adapter = FakeAdapter()

    caps = adapter.capabilities()
    assert isinstance(caps, Capabilities)
    assert caps.streaming is False
    assert caps.structured_output is False

    result = adapter.run("测试任务", ".", "test-model", timeout=30)
    assert result.ok is True
    assert "FakeAdapter" in result.output
    assert result.error_code is None
    assert result.error_msg == ""
    assert result.usage is not None

    stats = adapter.get_call_stats()
    assert stats["call_count"] == 1
    assert stats["last_prompt"] == "测试任务"
    assert stats["last_workdir"] == "."
    assert stats["last_model"] == "test-model"
    assert stats["fail_with"] is None

    adapter.reset_stats()
    stats = adapter.get_call_stats()
    assert stats["call_count"] == 0
    assert stats["last_prompt"] is None


def test_fake_adapter_fail_429():
    adapter = FakeAdapter(fail_with="429")
    result = adapter.run("测试任务", ".", "test-model", timeout=30)
    assert result.ok is False
    assert result.error_code == ErrorCode.RATE_LIMITED
    assert "429" in result.error_msg


def test_fake_adapter_fail_401():
    adapter = FakeAdapter(fail_with="401")
    result = adapter.run("测试任务", ".", "test-model", timeout=30)
    assert result.ok is False
    assert result.error_code == ErrorCode.BAD_REQUEST
    assert "401" in result.error_msg


def test_fake_adapter_fail_timeout():
    adapter = FakeAdapter(fail_with="TIMEOUT")
    result = adapter.run("测试任务", ".", "test-model", timeout=30)
    assert result.ok is False
    assert result.error_code == ErrorCode.TIMEOUT
    assert "timed out" in result.error_msg.lower()


def test_fake_adapter_send_test_mail():
    adapter = FakeAdapter()
    success, message = adapter.send_test_mail()
    if not success:
        # SMTP 配置不完整时必须返回失败而非抛异常
        assert "邮件配置不完整" in message or "发送失败" in message


def test_fake_adapter_registration():
    assert "fake" in ADAPTER_REGISTRY
    assert ADAPTER_REGISTRY["fake"] == FakeAdapter
    adapter = get_adapter("fake")
    assert adapter is not None
    assert isinstance(adapter, FakeAdapter)
    assert adapter.name == "fake"


def test_fake_adapter_injectable_failures():
    for mode in ("429", "401", "TIMEOUT", "UNKNOWN"):
        adapter = FakeAdapter(fail_with=mode)
        result = adapter.run("测试", ".", "model", timeout=10)
        if mode == "429":
            assert result.error_code == ErrorCode.RATE_LIMITED
        elif mode == "401":
            assert result.error_code == ErrorCode.BAD_REQUEST
        elif mode == "TIMEOUT":
            assert result.error_code == ErrorCode.TIMEOUT
        else:
            assert result.error_code == ErrorCode.TOOL_FAIL


def test_fake_adapter_signature_compliance():
    """FakeAdapter.run 签名与 BaseAdapter.run 保持字段冻结契约一致。"""
    base_sig = inspect.signature(BaseAdapter.run)
    fake_sig = inspect.signature(FakeAdapter.run)

    base_params = list(base_sig.parameters.keys())
    fake_params = list(fake_sig.parameters.keys())
    assert base_params == fake_params, f"签名参数不匹配: {base_params} vs {fake_params}"

    def _annotation_name(ann):
        if isinstance(ann, str):
            return ann
        if isinstance(ann, type):
            return ann.__name__
        return str(ann)

    base_return = _annotation_name(base_sig.return_annotation)
    fake_return = _annotation_name(fake_sig.return_annotation)
    assert base_return == fake_return, f"返回类型不匹配: {base_return} vs {fake_return}"
