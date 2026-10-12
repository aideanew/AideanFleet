"""Planner 测试（A2/A5）：schema 硬校验 + 服务写回语义 + 伪验收拒绝。"""

from __future__ import annotations

import json

import pytest

from fleet.kernel import Kernel
from fleet.kernel import state as st
from fleet.planner import PlanValidationError, validate_plan
from fleet.planner.service import apply_plan, extract_json, run_plan_todo

GOOD_PLAN = {
    "milestones": [{"id": "M1", "title": "骨架"}],
    "todos": [
        {"id": "T1", "milestone": "M1", "title": "初始化", "role": "fe-1",
         "depends_on": [], "allowed_files": ["web/**"],
         "verify": ["pnpm -C web build"], "done_when": "build 通过"},
        {"id": "T2", "milestone": "M1", "title": "接口", "role": "be-1",
         "depends_on": ["T1"], "allowed_files": ["server/**"],
         "verify": ["python -m pytest -q"]},
    ],
}


def test_validate_plan_accepts_good_plan():
    plan = validate_plan(GOOD_PLAN)
    assert [t["id"] for t in plan["todos"]] == ["T1", "T2"]


@pytest.mark.parametrize("mutation,snippet", [
    (lambda p: p["todos"][0].update(verify=[]), "verify"),
    (lambda p: p["todos"][0].update(verify=["python -c \"import pathlib; pathlib.Path('x').exists()\""]), "伪验收"),
    (lambda p: p["todos"][1].update(depends_on=["T9"]), "依赖不存在"),
    (lambda p: p["todos"][0].pop("role"), "role"),
    (lambda p: p["todos"][0].update(id="T2"), "重复"),
])
def test_validate_plan_rejects_bad_plans(mutation, snippet):
    plan = json.loads(json.dumps(GOOD_PLAN))
    mutation(plan)
    with pytest.raises(PlanValidationError) as exc:
        validate_plan(plan)
    assert snippet in str(exc.value)


def test_cycle_detection():
    plan = json.loads(json.dumps(GOOD_PLAN))
    plan["todos"][0]["depends_on"] = ["T2"]
    with pytest.raises(PlanValidationError, match="成环"):
        validate_plan(plan)


def test_extract_json_tolerates_fence_and_chatter():
    text = "好的，这是计划：\n```json\n{\"a\": 1}\n```\n以上。"
    assert extract_json(text) == {"a": 1}


def test_run_plan_todo_success_writes_todos(tmp_path):
    kernel = Kernel(tmp_path / "k.db")
    gid = kernel.create_goal("做官网")
    tid = kernel.create_todo(gid, kind="plan", title="拆解", packet="做官网需求全文")
    result = run_plan_todo(kernel, tid, lambda prompt: json.dumps(GOOD_PLAN, ensure_ascii=False))
    assert result.verdict == st.VERDICT_DONE
    exec_todos = [t for t in kernel.todos(gid) if t["kind"] == "exec"]
    assert len(exec_todos) == 2
    assert exec_todos[1]["depends_on"] == [exec_todos[0]["id"]]


def test_run_plan_todo_invalid_plan_becomes_successor_retry(tmp_path):
    kernel = Kernel(tmp_path / "k.db")
    gid = kernel.create_goal("g")
    tid = kernel.create_todo(gid, kind="plan", title="拆解")
    result = run_plan_todo(kernel, tid, lambda prompt: "这不是 JSON")
    assert result.verdict == st.VERDICT_SUCCESSOR
    assert "重试" in result.note


def test_run_plan_todo_model_failure_blocks(tmp_path):
    kernel = Kernel(tmp_path / "k.db")
    gid = kernel.create_goal("g")
    tid = kernel.create_todo(gid, kind="plan", title="拆解")
    def boom(prompt):
        raise RuntimeError("no key")
    result = run_plan_todo(kernel, tid, boom)
    assert result.verdict == st.VERDICT_BLOCKED


def test_apply_plan_respects_base_depends(tmp_path):
    kernel = Kernel(tmp_path / "k.db")
    gid = kernel.create_goal("g")
    anchor = kernel.create_todo(gid, title="前置")
    created = apply_plan(kernel, gid, validate_plan(GOOD_PLAN), base_depends=[anchor])
    assert created[0] in kernel.get_todo(created[1])["depends_on"] or \
           kernel.get_todo(created[1])["depends_on"] == [created[0]]
