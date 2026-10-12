"""Kernel 单元测试：claim/lease/transition/lineage/quota/依赖门（全程离线临时库）。"""

from __future__ import annotations

import time

import pytest

from fleet.kernel import Kernel, KernelError
from fleet.kernel import state as st
from fleet.kernel.state import TurnResult


@pytest.fixture()
def kernel(tmp_path):
    return Kernel(tmp_path / "kernel.db", lease_seconds=60, lineage_limit=3)


def test_create_and_claim_basic_flow(kernel):
    gid = kernel.create_goal("做一个网站")
    tid = kernel.create_todo(gid, title="搭骨架", role="fe-1",
                             allowed_files=["web/**"], verify=["pnpm build"])
    assert kernel.get_todo(tid)["status"] == st.OPEN

    claimed = kernel.claim(tid, worker="w1", harness="codex")
    assert claimed["status"] == st.CLAIMED
    assert claimed["claimed_by"] == "w1"
    assert claimed["attempt_count"] == 1

    with pytest.raises(KernelError):
        kernel.claim(tid, worker="w2")  # 已被认领

    kernel.mark_running(tid, "w1")
    with pytest.raises(KernelError):
        kernel.mark_running(tid, "w1")  # running 不能再 running

    kernel.mark_verifying(tid, "w1")
    done = kernel.transition(tid, TurnResult(verdict=st.VERDICT_DONE, evidence_path="e"))
    assert done["status"] == st.DONE
    attempts = kernel.attempts_of(tid)
    assert attempts[-1]["turn_result"] == "done"
    assert attempts[-1]["harness"] == "codex"


def test_done_requires_verifying_state(kernel):
    gid = kernel.create_goal("g")
    tid = kernel.create_todo(gid, title="t", verify=["x"])
    kernel.claim(tid, "w1")
    with pytest.raises(KernelError):
        kernel.transition(tid, TurnResult(verdict=st.VERDICT_DONE))
    kernel.mark_running(tid, "w1")
    with pytest.raises(KernelError):
        kernel.transition(tid, TurnResult(verdict=st.VERDICT_DONE))


def test_done_requires_evidence_when_no_verify(kernel):
    gid = kernel.create_goal("g")
    tid = kernel.create_todo(gid, title="t", verify=[])
    kernel.claim(tid, "w1")
    kernel.mark_running(tid, "w1")
    kernel.mark_verifying(tid, "w1")
    with pytest.raises(KernelError):
        kernel.transition(tid, TurnResult(verdict=st.VERDICT_DONE))
    ok = kernel.transition(tid, TurnResult(verdict=st.VERDICT_DONE, evidence_path="有证据"))
    assert ok["status"] == st.DONE


def test_lease_expiry_requeue_enables_continuation(kernel):
    gid = kernel.create_goal("g")
    tid = kernel.create_todo(gid, title="t", verify=["x"])
    kernel.claim(tid, "w1", lease_seconds=1)
    time.sleep(1.1)
    reclaimed = kernel.requeue_expired_leases()
    assert reclaimed == [tid]
    todo = kernel.get_todo(tid)
    assert todo["status"] == st.OPEN
    assert todo["claimed_by"] == ""
    # 另一个 worker 可以接续
    kernel.claim(tid, "w2")
    assert kernel.get_todo(tid)["claimed_by"] == "w2"


def test_dependency_gating_and_parallel_conflict(kernel):
    gid = kernel.create_goal("g")
    t1 = kernel.create_todo(gid, title="前端", role="fe-1", allowed_files=["web/**"], verify=["x"])
    t2 = kernel.create_todo(gid, title="后端", role="be-1", allowed_files=["server/**"], verify=["x"])
    t3 = kernel.create_todo(gid, title="联调", role="be-1",
                            depends_on=[t1, t2], allowed_files=["server/**"], verify=["x"])

    claimable = {t["id"] for t in kernel.claimable()}
    assert {t1, t2} <= claimable
    assert t3 not in claimable  # 依赖未完成

    kernel.claim(t1, "w1")
    claimable = {t["id"] for t in kernel.claimable()}
    assert t1 not in claimable           # 已被认领
    assert t2 in claimable               # 无文件域冲突可并行
    t4 = kernel.create_todo(gid, title="文档", role="docs", allowed_files=["web/**"], verify=["x"])
    assert t4 not in {t["id"] for t in kernel.claimable()}  # web/** 与 t1 冲突

    kernel.mark_running(t1, "w1")
    kernel.mark_verifying(t1, "w1")
    kernel.transition(t1, TurnResult(verdict=st.VERDICT_DONE))
    kernel.claim(t2, "w2")
    kernel.mark_running(t2, "w2")
    kernel.mark_verifying(t2, "w2")
    kernel.transition(t2, TurnResult(verdict=st.VERDICT_DONE))
    assert t3 in {t["id"] for t in kernel.claimable()}


def test_successor_keeps_lineage_and_cap_becomes_needs_user(tmp_path):
    kernel = Kernel(tmp_path / "k.db", lease_seconds=60, lineage_limit=2)
    gid = kernel.create_goal("g")
    t0 = kernel.create_todo(gid, title="实现", role="be-1", allowed_files=["src/**"], verify=["x"])
    kernel.claim(t0, "w1")
    kernel.mark_running(t0, "w1")
    r1 = kernel.transition(t0, TurnResult(
        verdict=st.VERDICT_SUCCESSOR, note="第一轮没过",
        successor={"title": "实现（返工）"}))
    assert r1["status"] == st.SUPERSEDED
    events = [e["kind"] for e in kernel.pending_events(100)]
    assert "todo:successor" in events
    succ = [t for t in kernel.todos() if t["status"] == st.OPEN][0]
    assert succ["lineage"] == t0  # 同一 lineage
    assert succ["successor_of"] == t0

    # 第二轮 successor 请求：lineage 轮数达上限（limit=2 已用 2 轮 attempt）→ needs_user
    kernel.claim(succ["id"], "w2")
    kernel.mark_running(succ["id"], "w2")
    r2 = kernel.transition(succ["id"], TurnResult(
        verdict=st.VERDICT_SUCCESSOR, successor={"title": "再返工"}))
    assert r2["status"] == st.NEEDS_USER
    assert not [t for t in kernel.todos() if t["successor_of"] == succ["id"]]


def test_quota_charged_only_on_done_and_gates_claimable(kernel):
    gid = kernel.create_goal("g")
    t1 = kernel.create_todo(gid, title="a", role="fe-1", verify=["x"])
    kernel.set_quota("fe-1", limit_per_day=1)
    kernel.claim(t1, "w1")
    kernel.mark_running(t1, "w1")
    kernel.mark_verifying(t1, "w1")
    kernel.transition(t1, TurnResult(verdict=st.VERDICT_DONE))
    assert kernel.quota_remaining("fe-1") == 0

    t2 = kernel.create_todo(gid, title="b", role="fe-1", verify=["x"])
    assert t2 not in {t["id"] for t in kernel.claimable()}  # 额度耗尽不可认领
    ok, reason = kernel.should_run()
    assert not ok and reason == "quota_exhausted:fe-1"  # 可执行但额度耗尽，原因要报出来

    blocked = kernel.create_todo(gid, title="c", role="fe-1", verify=["x"])
    kernel.claim(blocked, "w")
    kernel.transition(blocked, TurnResult(verdict=st.VERDICT_BLOCKED))
    kernel.claim(t2, "w")  # 直接绕过 claimable 模拟额度重置后写回
    kernel.mark_running(t2, "w")
    kernel.mark_verifying(t2, "w")
    kernel.transition(t2, TurnResult(verdict=st.VERDICT_DONE))


def test_should_run_and_attention_projection(kernel):
    ok, reason = kernel.should_run()
    assert not ok and reason == "no_runnable_todo"
    gid = kernel.create_goal("g")
    kernel.create_todo(gid, title="t", verify=["x"])
    ok, reason = kernel.should_run()
    assert ok and reason == "ok"

    tid = kernel.todos()[0]["id"]
    kernel.claim(tid, "w1")
    kernel.mark_running(tid, "w1")
    view = kernel.attention()
    assert view["counts"]["running"] == 1
    assert view["running"][0]["id"] == tid


def test_packet_contains_goal_todo_and_writeback_format(kernel):
    gid = kernel.create_goal("做官网")
    tid = kernel.create_todo(gid, title="搭骨架", role="fe-1",
                             allowed_files=["web/**"], verify=["pnpm build"],
                             done_when="build 退出码 0")
    packet = kernel.packet_for(tid)
    assert packet["goal"]["title"] == "做官网"
    assert packet["todo"]["verify"] == ["pnpm build"]
    assert "done" in packet["writeback"]["verdicts"]


def test_blocked_todo_can_be_reopened(kernel):
    gid = kernel.create_goal("g")
    tid = kernel.create_todo(gid, title="t", verify=["x"])
    kernel.claim(tid, "w1")
    kernel.transition(tid, TurnResult(verdict=st.VERDICT_BLOCKED, note="缺依赖"))
    assert kernel.get_todo(tid)["status"] == st.BLOCKED
    kernel.reopen(tid, actor="user")
    assert tid in {t["id"] for t in kernel.claimable()}


def test_needs_user_reopen_and_supersede(kernel):
    gid = kernel.create_goal("g")
    tid = kernel.create_todo(gid, title="t", verify=["x"])
    kernel.claim(tid, "w1")
    kernel.transition(tid, TurnResult(verdict=st.VERDICT_NEEDS_USER, note="需要用户拍板"))
    assert kernel.get_todo(tid)["status"] == st.NEEDS_USER
    view = kernel.attention()
    assert view["counts"]["needs_user"] == 1
    kernel.reopen(tid, actor="user")
    assert kernel.get_todo(tid)["status"] == st.OPEN
