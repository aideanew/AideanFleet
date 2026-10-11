"""TASK-601：Steer 测试——对话 → PlanDiff → needs_user → approve/reject 原子应用。"""

from __future__ import annotations

import json

import pytest

import pytest

from fleet.kernel import Kernel
from fleet.kernel import state as st


@pytest.fixture()
def kernel(tmp_path, monkeypatch):
    monkeypatch.setenv('FLEET_DATA_DIR', str(tmp_path / 'data'))
    return Kernel(tmp_path / 'kernel.db')
from fleet.kernel.kernel import DecisionAlreadyMade
from fleet.planner.steer import extract_diff, run_steer_todo, validate_diff

DIFF = {
    "add": [{"id": "N1", "milestone": "M1", "title": "补日志", "role": "be-1",
             "depends_on": [], "allowed_files": ["src/**"], "verify": ["python -m pytest -q"],
             "done_when": "日志就位"}],
    "cancel": [],
    "modify": [],
}


def _steer_todo(kernel, message="加一个日志功能"):
    gid = kernel.create_goal("g")
    tid = kernel.create_todo(gid, kind="steer", title="调整计划", packet=message)
    return gid, tid


def test_extract_diff_tolerates_fence():
    text = "```json\n" + json.dumps(DIFF, ensure_ascii=False) + "\n```"
    assert extract_diff(text)["add"][0]["id"] == "N1"


def test_validate_diff_rejects_done_and_missing(kernel):
    gid = kernel.create_goal("g")
    done_tid = kernel.create_todo(gid, title="已完成", verify=["x"])
    kernel.claim(done_tid, "w")
    kernel.mark_running(done_tid, "w")
    kernel.mark_verifying(done_tid, "w")
    kernel.transition(done_tid, __import__("fleet.kernel.state", fromlist=["TurnResult"]).TurnResult(
        verdict="done", evidence_path="e"))
    problems = validate_diff(kernel, {"add": [], "cancel": [done_tid], "modify": []})
    assert any("已终态" in p for p in problems)
    problems = validate_diff(kernel, {"add": [], "cancel": ["T-NOPE"], "modify": []})
    assert any("不存在" in p for p in problems)


def test_steer_pending_then_approve_applies_atomically(kernel, monkeypatch):
    monkeypatch.setattr("fleet.core.fleet_toml.load_config",
                        lambda: __import__("fleet.core.fleet_toml", fromlist=["FleetConfig"]).FleetConfig(
                            path=None, scheduler="step", sources={}))
    gid, tid = _steer_todo(kernel)
    kernel.claim(tid, "w")
    kernel.mark_running(tid, "w")
    kernel.mark_verifying(tid, "w")
    result = run_steer_todo(kernel, tid, lambda prompt: json.dumps(DIFF, ensure_ascii=False))
    assert result.verdict == st.VERDICT_NEEDS_USER
    todo = kernel.get_todo(tid)
    assert todo["status"] == st.NEEDS_USER and todo["plan_decision"] == "pending"
    events = [e["kind"] for e in kernel.pending_events(50)]
    assert "plan:diff_proposed" in events

    updated = kernel.apply_plan_diff(tid, "approve")
    assert updated["plan_decision"] == "approved"
    added = [t for t in kernel.todos(gid) if t["title"] == "补日志"]
    assert added and added[0]["status"] == st.OPEN
    events = [e["kind"] for e in kernel.pending_events(100)]
    assert "plan:decided" in events


def test_steer_auto_mode_applies_directly(kernel, monkeypatch):
    monkeypatch.setattr("fleet.core.fleet_toml.load_config",
                        lambda: __import__("fleet.core.fleet_toml", fromlist=["FleetConfig"]).FleetConfig(
                            path=None, scheduler="auto", sources={}))
    gid, tid = _steer_todo(kernel, "取消实现任务")
    kernel.claim(tid, "w")
    kernel.mark_running(tid, "w")
    kernel.mark_verifying(tid, "w")
    diff = {"add": [], "cancel": [], "modify": []}
    result = run_steer_todo(kernel, tid, lambda prompt: json.dumps(diff), auto_apply=True)
    assert result.verdict == st.VERDICT_DONE
    assert kernel.get_todo(tid)["plan_decision"] == "approved"


def test_double_decision_rejected(kernel):
    gid, tid = _steer_todo(kernel)
    kernel.claim(tid, "w")
    kernel.propose_plan_diff(tid, {"add": [], "cancel": [], "modify": []})
    kernel.apply_plan_diff(tid, "reject")
    with pytest.raises(DecisionAlreadyMade):
        kernel.apply_plan_diff(tid, "approve")


def test_invalid_diff_becomes_successor_retry(kernel):
    gid, tid = _steer_todo(kernel, "改")
    kernel.claim(tid, "w")
    kernel.mark_running(tid, "w")
    kernel.mark_verifying(tid, "w")
    result = run_steer_todo(kernel, tid, lambda prompt: "不是 JSON")
    assert result.verdict == st.VERDICT_SUCCESSOR
    assert "重试" in result.note
