"""Harness Profiles 测试：yaml_min 解析、profile 加载、流解析器、doctor 探测语义。"""

from __future__ import annotations

import pytest

from fleet.harness import yaml_min
from fleet.harness.parsers import get_parser
from fleet.harness.profile import HarnessProfile, load_profile
from fleet.harness.runner import _build_command


def test_yaml_min_parses_profile_subset():
    data = yaml_min.parse(
        "# 注释\n"
        "name: claude\n"
        "timeout_idle_s: 180\n"
        "prompt_via: stdin\n"
        "invoke: [\"claude\", \"-p\"]\n"
        "detect:\n"
        "  - claude\n"
        "  - --version\n"
    )
    assert data["name"] == "claude"
    assert data["timeout_idle_s"] == 180
    assert data["invoke"] == ["claude", "-p"]
    assert data["detect"] == ["claude", "--version"]


def test_yaml_min_rejects_nesting_and_bare_text():
    with pytest.raises(yaml_min.YamlMiniError):
        yaml_min.parse("a:\n  b: 1\n")
    with pytest.raises(yaml_min.YamlMiniError):
        yaml_min.parse("just text")


def test_load_profile_bundled_profiles():
    for name in ("claude", "codex", "opencode"):
        profile = load_profile(name)
        assert isinstance(profile, HarnessProfile)
        assert profile.invoke and profile.invoke[0] == name
        assert profile.detect


def test_load_profile_rejects_bad_name_and_missing(tmp_path):
    with pytest.raises(ValueError):
        load_profile("../escape")
    with pytest.raises(FileNotFoundError):
        load_profile("nope", profiles_dir=tmp_path)


def test_build_command_resolves_cli_and_model_flag():
    profile = load_profile("codex")
    cmd = _build_command(profile, model="agnes-3.0-flash")
    assert cmd[0].lower().endswith(("codex", "codex.cmd", "codex.exe")) or "codex" in cmd[0]
    assert "-m" in cmd and "agnes-3.0-flash" in cmd


def test_claude_ignores_pool_model(monkeypatch):
    """C3 口径：anthropic 协议不吃 OpenAI 兼容模型池——不注入 -m 参数。"""
    profile = load_profile("claude")
    cmd = _build_command(profile, model="agnes-3.0-flash")
    assert "-m" not in cmd


def test_claude_stream_json_parser():
    lines = [
        '{"type":"assistant","message":{"content":[{"type":"text","text":"hello"}]}}',
        '{"type":"result","result":"done text","session_id":"s1","usage":{"input_tokens":3,"output_tokens":5}}',
        'not-json-garbage',
    ]
    events = list(get_parser("claude_stream_json")(iter(lines)))
    assert any(e.type == "text" and e.text == "hello" for e in events)
    result = next(e for e in events if e.type == "result")
    assert result.text == "done text" and result.data["session_id"] == "s1"
    usage = next(e for e in events if e.type == "usage")
    assert usage.data == {"tokens_in": 3, "tokens_out": 5}
    assert any(e.type == "raw" for e in events)  # 容错降级


def test_codex_jsonl_parser():
    lines = [
        '{"msg":{"type":"agent_message","message":"step one"}}',
        '{"msg":{"type":"task_complete","last_agent_message":"final","usage":{"input_tokens":1,"output_tokens":2}}}',
    ]
    events = list(get_parser("codex_jsonl")(iter(lines)))
    assert [e.text for e in events if e.type == "text"] == ["step one"]
    assert next(e for e in events if e.type == "result").text == "final"


def test_opencode_parser():
    lines = [
        '{"parts":[{"type":"text","text":"part-1"}],"sessionID":"op-1","usage":{"input_tokens":2,"output_tokens":3}}',
    ]
    events = list(get_parser("opencode_json")(iter(lines)))
    assert any(e.type == "text" and e.text == "part-1" for e in events)
    assert any(e.type == "session" and e.text == "op-1" for e in events)
