"""TASK-102：worker 接线测试——planner_client/model_for 注入 + create_goal_with_plan。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from fleet.cli import clients
from fleet.kernel import Kernel
from fleet.kernel import state as st
from fleet.runner import worker as worker_mod

GOOD_PLAN = {
    "milestones": [{"id": "M1", "title": "骨架"}],
    "todos": [
        {"id": "T1", "milestone": "M1", "title": "实现", "role": "fe-1",
         "depends_on": [], "allowed_files": ["src/**"],
         "verify": ["python -m pytest -q"], "done_when": "测试通过"},
    ],
}


@pytest.fixture()
def kernel(tmp_path, monkeypatch):
    monkeypatch.setenv("FLEET_DATA_DIR", str(tmp_path / "data"))
    return Kernel(tmp_path / "kernel.db")


def test_create_goal_with_plan_same_transaction(kernel):
    gid, tid = kernel.create_goal_with_plan("做计算器", "实现一个命令行计算器", "E:/Demo/Calc")
    goal = kernel.attention()["goals"][0]
    assert goal["id"] == gid
    assert goal["requirements"] == "实现一个命令行计算器"
    assert goal["workspace"] == "E:/Demo/Calc"
    todo = kernel.get_todo(tid)
    assert todo["kind"] == "plan" and todo["goal_id"] == gid and todo["role"] == "planner"
    events = [e["kind"] for e in kernel.pending_events(50)]
    assert events.count("goal:created") == 1 and events.count("todo:created") == 1


def test_model_for_from_fleet_toml(tmp_path, monkeypatch, kernel):
    monkeypatch.setenv("FLEET_ROOT", str(tmp_path))
    (tmp_path / "fleet.toml").write_text(
        '[models.agnes]\n'
        'base_url = "https://api.example/v1"\n'
        'model_id = "agnes-3.0-flash"\n'
        'api_key_env = "AGNES_API_KEY"\n'
        'priority = 1\n\n'
        '[roles.fe-1]\n'
        'harness = ["codex"]\n'
        'models = ["agnes"]\n',
        encoding="utf-8",
    )
    monkeypatch.delenv("AGNES_API_KEY", raising=False)
    assert clients.model_for("fe-1") == ""  # key 未配置 → 不桥接
    monkeypatch.setenv("AGNES_API_KEY", "k" * 10)
    assert clients.model_for("fe-1") == "agnes-3.0-flash"
    chain = clients.model_chain("fe-1")
    assert chain[0].source == "fleet.toml"


def test_model_chain_falls_back_to_env_pool(tmp_path, monkeypatch, kernel):
    """A-12：fleet.toml 无 models → 回退旧 .env 模型池。"""
    root = tmp_path / "root"
    root.mkdir()
    (root / ".env.example").write_text(
        "FLEET_MODEL_1_NAME=m1\nFLEET_MODEL_1_LEVEL=1\nFLEET_MODEL_1_BASE_URL=https://m1.example/v1\n"
        "FLEET_MODEL_1_MODEL_ID=demo-1\nFLEET_MODEL_1_API_KEY=${M1_KEY}\n\n"
        "FLEET_ROLE_1_NAME=fe-1\nFLEET_ROLE_1_BIND_MODEL_NAME=m1\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("FLEET_ROOT", str(root))
    monkeypatch.setenv("FLEET_DATA_DIR", str(tmp_path / "data2"))
    monkeypatch.setenv("M1_KEY", "present")
    chain = clients.model_chain("fe-1")
    assert chain and chain[0].source == "env_pool"
    assert clients.model_for("fe-1") == "demo-1"


def test_worker_runs_plan_todo_with_injected_client(kernel, monkeypatch):
    """核心验收：run_once 对 plan todo 用注入的 planner_client 出计划，不再 blocked。"""
    fake_candidate = clients.ModelCandidate(name="fake", base_url="http://fake.example/v1",
                                            model_id="fake-1", api_key_env="", source="test",
                                            entry=None)
    monkeypatch.setattr(clients, "model_chain", lambda role: [fake_candidate])
    gid, tid = kernel.create_goal_with_plan("做计算器", "需求全文", "E:/Demo/Calc")

    def fake_transport(entry, prompt, *a, **kw):
        return type("R", (), {"ok": True, "text": json.dumps(GOOD_PLAN, ensure_ascii=False),
                              "error_code": None, "error_msg": ""})()

    planner_client = clients.make_planner_client("planner", transport_fn=fake_transport)
    outcome = worker_mod.run_once(kernel, worker="w1", planner_client=planner_client,
                                  workspace_root="E:/Demo/Calc")
    assert outcome["action"] == "writeback"
    kernel.transition(outcome["todo"], outcome["result"])
    assert kernel.get_todo(tid)["status"] == st.DONE
    exec_todos = [t for t in kernel.todos(gid) if t["kind"] == "exec"]
    assert len(exec_todos) == 1 and exec_todos[0]["verify"] == ["python -m pytest -q"]


def test_worker_without_client_still_blocks(kernel):
    """回归保护：不注入 planner_client 时行为保持 blocked（未配置），不误吞。"""
    gid, tid = kernel.create_goal_with_plan("g", "r")
    outcome = worker_mod.run_once(kernel, worker="w1", planner_client=None)
    assert outcome["action"] == "writeback"
    kernel.transition(outcome["todo"], outcome["result"])
    assert kernel.get_todo(tid)["status"] == st.BLOCKED


def test_cmd_worker_injects_clients(monkeypatch, tmp_path):
    """cmd_worker 必须把 planner_client/model_for 传给 run_loop（F-01 修复的接线断言）。"""
    import fleet.cli.main as cli_main

    captured: dict = {}

    def fake_run_loop(kernel, *, worker, planner_client=None, model_for=None,
                      on_round=None, workspace_root="", interval_s=2.0, max_rounds=0):
        captured["planner_client"] = planner_client
        captured["model_for"] = model_for

    monkeypatch.setattr("fleet.runner.run_loop", fake_run_loop)
    monkeypatch.setattr("sys.argv", ["fleet", "worker", "--loop"])
    cli_main.main(["worker", "--loop"])
    assert callable(captured["planner_client"])
    assert callable(captured["model_for"])
