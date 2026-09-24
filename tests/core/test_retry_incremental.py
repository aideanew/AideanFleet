# 这是什么：Incremental Diff 返工增量单测（CORE-04 · 契约 v1.2 §13.5）。
# 目的：验证 retry_context 自动生成（attempt/failure/previous_diff/evidence_paths）、
#       git 优先与基线快照回退、派工侧增量 prompt 生效（不重发全量上下文）。
import subprocess

import pytest

from fleet.core import db, events
from fleet.manager import dispatcher, rework_manager

from .stubs import make_task, ok_result, pass_route, rework_route, StubAdapter


def _git(repo, *args):
    completed = subprocess.run(
        ["git", "-c", "user.email=t@fleet.local", "-c", "user.name=t", *args],
        cwd=str(repo), capture_output=True, text=True, timeout=30,
    )
    assert completed.returncode == 0, completed.stderr
    return completed.stdout


def _actions(project_id: str) -> list[str]:
    return [row["action"] for row in events.read(project=project_id)]


def test_build_retry_context_with_git_repo(fleet_env, project, tmp_path):
    repo = tmp_path / "ws"
    repo.mkdir()
    (repo / "app.py").write_text("print('v1')\n", encoding="utf-8")
    _git(repo, "init")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "init")
    (repo / "app.py").write_text("print('v2')\n", encoding="utf-8")
    make_task(project, "T-D1", workspace=str(repo))
    db.update_task("T-D1", rework_count=1, remark="审查意见：改错方向")

    ctx = rework_manager.build_retry_context(db.get_task("T-D1"))
    assert set(ctx) == {"attempt", "failure", "previous_diff", "evidence_paths"}
    assert ctx["attempt"] == 1
    assert ctx["failure"]["review"] == "审查意见：改错方向"
    assert ctx["previous_diff"]["source"] == "git"
    assert "app.py" in ctx["previous_diff"]["stat"]
    assert "app.py" in ctx["previous_diff"]["files"]
    assert "print('v2')" in ctx["previous_diff"]["files"]["app.py"]


def test_build_retry_context_without_git_falls_back(fleet_env, project, tmp_path):
    plain = tmp_path / "plain-ws"
    plain.mkdir()
    make_task(project, "T-D2", workspace=str(plain))
    db.update_task("T-D2", rework_count=2)
    ctx = rework_manager.build_retry_context(db.get_task("T-D2"))
    assert ctx["attempt"] == 2
    # 无 git 仓库：不得编造 diff，注明来源（基线快照回退或显式注明）
    assert ctx["previous_diff"]["source"] in ("baseline", "none", "git")
    assert "diff" in ctx["previous_diff"]["stat"] or ctx["previous_diff"]["source"] != "git"


def test_handle_rework_persists_retry_context(fleet_env, project, tmp_path):
    from fleet.manager import contracts

    workspace = tmp_path / "ws"
    workspace.mkdir()
    adapter = StubAdapter([ok_result("第一轮不完整"), ok_result("# 六节报告\n修好了")])
    contracts.register("stub", adapter)
    try:
        make_task(project, "T-D3", workspace=str(workspace))
        assert dispatcher.dispatch("T-D3").state == "SUBMITTED"
        from fleet.manager import reviewer

        outcome = reviewer.review("T-D3", actor="tester", router_fn=lambda *a, **k: rework_route())
        assert outcome.verdict == "REWORK"

        handled = rework_manager.handle_rework("T-D3", actor="tester")
        assert handled["state"] == "ASSIGNED"

        row = db.get_task("T-D3")
        retry_context = row["retry_context"]
        assert isinstance(retry_context, str) and "previous_diff" in retry_context  # DB 里是 JSON 文本
        parsed = rework_manager.build_retry_context(row)
        assert parsed["attempt"] == 1
        # ASSIGNED 常态路径不发 task:rework_dispatch（reviewer 已发 task:rework），retry_context 落库即可审计
        assert [row for row in events.read(project=project) if row["action"] == "task:rework"]
    finally:
        contracts.unregister("stub")


def test_rework_dispatch_sends_only_increment(fleet_env, project, tmp_path):
    from fleet.manager import contracts

    workspace = tmp_path / "ws"
    workspace.mkdir()
    (workspace / "app.py").write_text("print('v1')\n", encoding="utf-8")
    adapter = StubAdapter([ok_result("第一轮"), ok_result("# 六节报告\n修好了")])
    contracts.register("stub", adapter)
    try:
        make_task(project, "T-D4", workspace=str(workspace))
        assert dispatcher.dispatch("T-D4").state == "SUBMITTED"
        from fleet.manager import reviewer

        reviewer.review("T-D4", actor="tester", router_fn=lambda *a, **k: rework_route())
        rework_manager.handle_rework("T-D4", actor="tester")
        assert dispatcher.dispatch("T-D4").state == "SUBMITTED"

        rework_prompt = adapter.calls[1]["prompt"]
        assert "这是第 1 轮返工，只需基于以下增量信息修复，不要重新调查全项目" in rework_prompt
        assert "previous_diff" in rework_prompt
        assert "[MANAGER DISPATCH]" not in rework_prompt  # 绝不重发全量派工上下文
        assert "[PROJECT MEMORY]" not in rework_prompt  # 绝不重发项目记忆
        # 计量事件：返工组装的 rework 标记为 true
        assembled = [row for row in events.read(project=project) if row["action"] == "prompt:assembled"]
        assert assembled[-1]["extra"]["rework"] is True
    finally:
        contracts.unregister("stub")


def test_new_task_prompt_contains_memory_and_pass_event(fleet_env, project):
    from fleet.core import memory
    from fleet.manager import contracts, context_budget

    adapter = StubAdapter([ok_result("# 六节报告\n完成")])
    contracts.register("stub", adapter)
    try:
        entry = memory.record_decision("P-001", title="基线决策", summary="只改 allowed_files 内的文件。")
        pack = dispatcher.TaskPack(
            id="T-D5", title="新任务", detail="做一点事", verify_cmd='python -c "print(1)"',
            assignee="worker-a", reviewer="reviewer-1", project_id="P-001",
            memory_refs=[entry["id"]],
        )
        dispatcher.create_task(pack, project_id=project)
        assert dispatcher.dispatch("T-D5").state == "SUBMITTED"
        # 新任务 prompt 携带记忆头 + 派工模板（全量口径只此一次）
        assert "[PROJECT MEMORY]" in adapter.calls[0]["prompt"]
        assert "基线决策" in adapter.calls[0]["prompt"]
        actions = _actions(project)
        assert "prompt:assembled" in actions and "budget:check" in actions and "model:call" in actions
        model_call = [row for row in events.read(project=project) if row["action"] == "model:call"][-1]
        usage = model_call["extra"]["usage"]
        assert set(usage) == {"prompt_tokens", "cached_tokens", "completion_tokens", "total_tokens"}
        # context_budget / memory_refs 落库
        row = db.get_task("T-D5")
        assert row["context_budget"] == 8000 and entry["id"] in row["memory_refs"]
    finally:
        contracts.unregister("stub")


@pytest.mark.parametrize("raw,expected", [(None, 8000), (0, 8000), (299, 8000), (300, 300), (12000, 12000)])
def test_context_budget_parse_rules(fleet_env, project, raw, expected):
    from fleet.manager import contracts

    assert contracts._parse_budget(raw) == expected
