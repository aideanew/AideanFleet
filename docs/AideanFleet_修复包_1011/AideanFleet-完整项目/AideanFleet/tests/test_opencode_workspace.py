"""OpenCode 工作区绑定：父 shell 目录不能泄漏到执行会话。"""
import json
import subprocess

import pytest

from fleet.executors import opencode
from fleet.manager import dispatcher, intake
from fleet.manager.contracts import TaskPack


@pytest.fixture
def invocation(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setenv("PWD", "E:/Code/AideanFleet")
    monkeypatch.setenv("INIT_CWD", "E:/Code/AideanFleet")
    monkeypatch.setattr(opencode, "save_evidence", lambda *args: None)
    monkeypatch.setattr(opencode, "pool_entry_for", lambda model: None)
    def run(cmd, **kwargs):
        calls.append((cmd, kwargs))
        return subprocess.CompletedProcess(cmd, 0, "报告", "")
    monkeypatch.setattr(opencode, "run_subprocess_tree_safe", run)
    return calls, tmp_path / "中文 space project"


def test_explicit_directory_and_environment(invocation):
    calls, workspace = invocation
    workspace.mkdir()
    result = opencode.OpenCodeAdapter().run("任务", str(workspace), "provider/model")
    assert result.ok
    cmd, kwargs = calls[0]
    target = workspace.resolve().as_posix()
    assert cmd[cmd.index("--dir") + 1] == target
    assert kwargs["cwd"] == target
    assert kwargs["env"]["PWD"] == target
    assert kwargs["env"]["INIT_CWD"] == target
    assert "--auto" not in cmd
    permissions = json.loads(kwargs["env"]["OPENCODE_PERMISSION"])
    assert permissions["external_directory"] == "deny"


def test_missing_workspace_never_launches(invocation):
    calls, workspace = invocation
    result = opencode.OpenCodeAdapter().run("任务", str(workspace), "")
    assert not result.ok
    assert calls == []


@pytest.mark.parametrize("workdir", ["", "relative/path"])
def test_ambiguous_workspace_never_launches(invocation, workdir):
    calls, _ = invocation
    result = opencode.OpenCodeAdapter().run("任务", workdir, "")
    assert not result.ok
    assert calls == []


def test_report_is_returned_not_written_outside_workspace():
    prompt = TaskPack(id="T", title="目录", detail="测试", workspace="E:/Demo/test",
                      report_path="E:/Code/AideanFleet/data/report.md").to_prompt()
    assert "证据写到：" not in prompt
    assert "由 Fleet" in prompt


def test_no_powershell_assumption_in_prompt(monkeypatch):
    monkeypatch.setattr(dispatcher, "_system_prompt_for", lambda _: "")
    monkeypatch.setattr(dispatcher.context_budget, "_emit", lambda **kwargs: None)
    pack = TaskPack(id="T", title="目录", detail="测试", workspace="E:/Demo/中文 space")
    prompt = dispatcher._build_prompt(pack)
    assert "本机为 Windows + PowerShell" not in prompt
    assert "正斜杠" in prompt
    assert "标准输出" in prompt
    for _, tasks in intake._plan_templates("简单表格"):
        assert all("禁止 bash 语法" not in task["detail"] for task in tasks)
