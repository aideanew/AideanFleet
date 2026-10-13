"""P1 完成标准 e2e：fake harness 从 goal 到 done（真实子进程 + 真实机器门 + 真实写回）。

覆盖三条完成标准：
1. test_fake_harness_goal_to_done：goal → plan(planner) → exec → verify → done，
   事件/attempt/额度全程落库；
2. test_worker_restarts_from_expired_lease：kill worker（租约到期）后重新认领接续；
3. test_wrong_implementation_is_caught_by_gate：故意写错的实现被机器门拦下并生成返工 successor。
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import pytest

from fleet.kernel import Kernel
from fleet.kernel import state as st
from fleet.kernel.state import TurnResult
from fleet.runner import worker as worker_mod

PY = sys.executable.replace("\\", "/")


@pytest.fixture()
def fake_harness(tmp_path, monkeypatch):
    """生成一个真实可执行的 fake harness profile：
    脚本按指令在 workspace 写 src/main.py（内容由环境变量控制，可注入错误实现）。"""
    script = tmp_path / "fake_harness.py"
    script.write_text(
        "import os, sys, pathlib\n"
        "workspace = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else pathlib.Path.cwd()\n"
        "mode = os.environ.get('FAKE_MODE', 'ok')\n"
        "(workspace / 'src').mkdir(parents=True, exist_ok=True)\n"
        "if mode == 'broken':\n"
        "    (workspace / 'src' / 'main.py').write_text('def main():\\n    return 1 / 0\\n', encoding='utf-8')\n"
        "else:\n"
        "    (workspace / 'src' / 'main.py').write_text('def main():\\n    return 42\\n', encoding='utf-8')\n"
        "print('FAKE-REPORT: 六节报告\\n改动: src/main.py\\n模型自述: fake')\n",
        encoding="utf-8",
    )
    profiles = tmp_path / "profiles"
    profiles.mkdir()
    (profiles / "fakeh.yaml").write_text(
        f"name: fakeh\n"
        f"detect: [\"{PY}\", \"--version\"]\n"
        f"auth_check: [\"{PY}\", \"-c\", \"pass\"]\n"
        f"invoke: [\"{PY}\", \"{str(script).replace(chr(92), '/')}\"]\n"
        f"prompt_via: stdin\n"
        f"model_protocol: none\n"
        f"output_parser: plain\n"
        f"timeout_idle_s: 60\n",
        encoding="utf-8",
    )
    monkeypatch.setattr("fleet.harness.profile.PROFILES_DIR", profiles)
    monkeypatch.setattr(worker_mod, "_harness_chain_for", lambda role: ["fakeh"])
    return script


def _verify_cmd(tmp_path: Path) -> list[str]:
    """真实验收命令：main() 返回 42 才通过（exit 0），否则 exit 1。"""
    checker = tmp_path / "checker.py"
    checker.write_text(
        "import importlib.util, pathlib, sys\n"
        "target = pathlib.Path('src/main.py')\n"
        "if not target.is_file():\n"
        "    sys.exit(3)\n"
        "spec = importlib.util.spec_from_file_location('m', target)\n"
        "mod = importlib.util.module_from_spec(spec)\n"
        "spec.loader.exec_module(mod)\n"
        "sys.exit(0 if mod.main() == 42 else 1)\n",
        encoding="utf-8",
    )
    return [f"\"{PY}\" \"{str(checker).replace(chr(92), '/')}\""]


def _planner_client(plan_builder):
    def client(prompt: str) -> str:
        return json.dumps(plan_builder, ensure_ascii=False)
    return client


PLAN = {
    "milestones": [{"id": "M1", "title": "可运行骨架"}],
    "todos": [
        {"id": "T1", "milestone": "M1", "title": "实现 main", "role": "fe-1",
         "depends_on": [], "allowed_files": ["src/**"],
         "verify": [], "done_when": "main() == 42"},
        {"id": "T2", "milestone": "M1", "title": "编写测试", "role": "qa-1",
         "depends_on": ["T1"], "allowed_files": ["tests/**"],
         "verify": [], "done_when": "测试通过"},
    ],
}


def test_fake_harness_goal_to_done(tmp_path, fake_harness, monkeypatch):
    """goal → plan → 两个 exec（依赖串联）→ 全部 done → goal:done 事件。"""
    kernel = Kernel(tmp_path / "kernel.db", lease_seconds=120)
    workspace = tmp_path / "ws"
    workspace.mkdir()

    plan = json.loads(json.dumps(PLAN))
    plan["todos"][0]["verify"] = _verify_cmd(tmp_path)
    plan["todos"][1]["verify"] = [f"\"{PY}\" -c \"pass\""]
    for t in plan["todos"]:
        t["allowed_files"] = ["**"]  # 单 worker 串行，避免文件域互斥挡住第二个任务

    gid = kernel.create_goal("实现返回 42 的程序")
    kernel.create_todo(gid, kind="plan", title="拆解需求", packet="实现一个 main()==42 的程序",
                       workspace=str(workspace))
    rounds: list[dict] = []
    worker_mod.run_loop(
        kernel, worker="w1", max_rounds=4, interval_s=0.01,
        planner_client=_planner_client(plan),
        workspace_root=str(workspace),
        on_round=rounds.append,
    )
    todos = kernel.todos(gid)
    statuses = {t["status"] for t in todos}
    assert statuses == {st.DONE}, [ (t["title"], t["status"]) for t in todos ]
    assert len(todos) == 3  # 1 plan + 2 exec
    events = [e["kind"] for e in kernel.pending_events(100)]
    assert "goal:done" in events
    # 验证通过并写回才计费：exec 任务各计 1 次
    assert kernel.quota_remaining("fe-1") is None  # 未设限 → None，但 used 已记
    # attempts 有 harness 记录
    exec_todos = [t for t in todos if t["kind"] == "exec"]
    for t in exec_todos:
        attempts = kernel.attempts_of(t["id"])
        assert attempts and attempts[0]["harness"] == "fakeh"
    # 证据落盘
    for t in exec_todos:
        gate_json = tmp_path / "evidence" / t["id"] / "gate.json"
        assert gate_json.is_file(), gate_json
        assert json.loads(gate_json.read_text(encoding="utf-8"))["ok"] is True


def test_worker_restarts_from_expired_lease(tmp_path, fake_harness):
    """kill worker：租约到期回收 → 第二个 worker 接续并完成（kill-safe）。"""
    kernel = Kernel(tmp_path / "kernel.db", lease_seconds=1)
    workspace = tmp_path / "ws"
    workspace.mkdir()
    gid = kernel.create_goal("g")
    kernel.create_todo(gid, title="实现 main", role="fe-1",
                       allowed_files=["**"], verify=_verify_cmd(tmp_path),
                       workspace=str(workspace))

    # worker-1 认领后"死掉"（不写回）
    kernel.claim(kernel.todos()[0]["id"], worker="worker-dead")
    time.sleep(1.2)
    # worker-2 上线：run_once 会先回收过期租约再认领
    outcome = worker_mod.run_once(kernel, worker="worker-2")
    assert outcome["action"] == "writeback"
    kernel.transition(outcome["todo"], outcome["result"])
    assert kernel.get_todo(outcome["todo"])["status"] == st.DONE
    events = [e["kind"] for e in kernel.pending_events(100)]
    assert "todo:lease_expired" in events


def test_wrong_implementation_is_caught_by_gate(tmp_path, fake_harness, monkeypatch):
    """故意写错的实现被机器门拦下 → successor 返工 todo（同 lineage），修正后通过。"""
    kernel = Kernel(tmp_path / "kernel.db", lease_seconds=120)
    workspace = tmp_path / "ws"
    workspace.mkdir()
    gid = kernel.create_goal("g")
    kernel.create_todo(gid, title="实现 main", role="fe-1",
                       allowed_files=["**"], verify=_verify_cmd(tmp_path),
                       workspace=str(workspace))

    monkeypatch.setenv("FAKE_MODE", "broken")
    outcome = worker_mod.run_once(kernel, worker="w1")
    kernel.transition(outcome["todo"], outcome["result"])
    after_fail = kernel.get_todo(outcome["todo"])
    assert after_fail["status"] == st.SUPERSEDED
    rework = [t for t in kernel.todos() if t["status"] == st.OPEN]
    assert len(rework) == 1
    assert rework[0]["lineage"] == outcome["todo"]
    assert "机器门未通过" in rework[0]["packet"]

    # 修正后的实现：返工任务执行成功 → done
    monkeypatch.setenv("FAKE_MODE", "ok")
    outcome2 = worker_mod.run_once(kernel, worker="w2")
    kernel.transition(outcome2["todo"], outcome2["result"])
    assert kernel.get_todo(outcome2["todo"])["status"] == st.DONE


def test_all_harness_unavailable_blocks_with_reason(tmp_path, monkeypatch):
    """卸载任一 CLI 的语义等价物：执行体链全部不可用 → blocked 且带原因（P3 完成标准）。"""
    from fleet.kernel import Kernel as K
    kernel = K(tmp_path / "kernel.db", lease_seconds=60)
    workspace = tmp_path / "ws"
    workspace.mkdir()
    gid = kernel.create_goal("g")
    tid = kernel.create_todo(gid, title="t", role="fe-1", verify=["x"], workspace=str(workspace))

    monkeypatch.setattr(worker_mod, "_harness_chain_for", lambda role: ["no-such-harness"])
    outcome = worker_mod.run_once(kernel, worker="w1")
    assert outcome["action"] == "writeback"
    kernel.transition(tid, outcome["result"])
    todo = kernel.get_todo(tid)
    assert todo["status"] == st.BLOCKED


def test_model_only_fallback_goal_to_done(tmp_path, monkeypatch):
    """P4：无任何 CLI harness——goal → plan → exec 全走模型直写回退 → 同一道真实机器门 → done。"""
    monkeypatch.setattr(worker_mod, "_harness_chain_for", lambda role: ["no-such-harness"])
    kernel = Kernel(tmp_path / "kernel.db", lease_seconds=120)
    workspace = tmp_path / "ws"
    workspace.mkdir()

    plan = json.loads(json.dumps(PLAN))
    plan["todos"][0]["verify"] = _verify_cmd(tmp_path)
    plan["todos"][1]["verify"] = [f"\"{PY}\" -c \"pass\""]
    for t in plan["todos"]:
        t["allowed_files"] = ["**"]

    ops_reply = json.dumps({
        "ops": [{"op": "write", "path": "src/main.py",
                 "content": "def main():\n    return 42\n"}],
        "report": "改动: src/main.py；模型自述: 模型直写回退",
    }, ensure_ascii=False)
    replies = [json.dumps(plan, ensure_ascii=False), ops_reply, ops_reply]

    def client(prompt: str) -> str:
        assert replies, "模型客户端被调用次数超出预期"
        return replies.pop(0)

    gid = kernel.create_goal("无 CLI 环境下完成 42 程序")
    kernel.create_todo(gid, kind="plan", title="拆解需求", packet="实现一个 main()==42 的程序",
                       workspace=str(workspace))
    worker_mod.run_loop(kernel, worker="mw1", max_rounds=4, interval_s=0.01,
                        planner_client=client, workspace_root=str(workspace))

    todos = kernel.todos(gid)
    assert {t["status"] for t in todos} == {st.DONE}, [(t["title"], t["status"]) for t in todos]
    exec_todos = [t for t in todos if t["kind"] == "exec"]
    for t in exec_todos:
        attempts = kernel.attempts_of(t["id"])
        assert attempts and attempts[0]["harness"] == "model-write"
    assert "goal:done" in [e["kind"] for e in kernel.pending_events(100)]
    for t in exec_todos:  # 证据照常落盘（机器门不因回退而放松）
        gate_json = tmp_path / "evidence" / t["id"] / "gate.json"
        assert gate_json.is_file() and json.loads(gate_json.read_text(encoding="utf-8"))["ok"] is True


def test_model_only_out_of_scope_write_is_refused(tmp_path, monkeypatch):
    """P4 安全边界：模型越界写（未命中 allowed_files）→ 整批拒绝 → blocked，文件不落盘。"""
    monkeypatch.setattr(worker_mod, "_harness_chain_for", lambda role: ["no-such-harness"])
    kernel = Kernel(tmp_path / "kernel.db", lease_seconds=60)
    workspace = tmp_path / "ws"
    workspace.mkdir()
    gid = kernel.create_goal("g")
    tid = kernel.create_todo(gid, title="只许改 docs", role="fe-1",
                             allowed_files=["docs/**"], verify=[f"\"{PY}\" -c \"pass\""],
                             workspace=str(workspace))
    evil = json.dumps({"ops": [{"op": "write", "path": "src/evil.py", "content": "pwned"}],
                       "report": "越界"}, ensure_ascii=False)
    outcome = worker_mod.run_once(kernel, worker="w1", planner_client=lambda p: evil)
    kernel.transition(tid, outcome["result"])
    assert kernel.get_todo(tid)["status"] == st.BLOCKED
    assert not (workspace / "src" / "evil.py").exists()
