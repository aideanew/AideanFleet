"""需求建册到 DONE，再以真实派工事件核对项目与任务用量（全程离线）。"""

from pathlib import Path
from unittest.mock import Mock

from fleet.core import db, events, plan
from fleet.governance import store as governance_store
from fleet.governance.usage import UsageAggregator
from fleet.manager import contracts, intake, reviewer, scheduler

from .stubs import StubAdapter, ok_result, pass_route


def test_intake_to_done_aggregates_real_dispatch_usage(fleet_env, monkeypatch):
    """仅替换外部执行体与审查模型，其余生产链路使用真实实现。"""
    project_id = "IntakeUsage"
    workspace_root = fleet_env["root"] / "workspaces"
    workspace_root.mkdir()
    workspace = workspace_root / project_id
    monkeypatch.setenv("FLEET_ALLOWED_ROOTS", str(workspace_root))
    monkeypatch.setattr(governance_store, "_db_path", fleet_env["data"] / "governance.db")

    class DeliveringExecutor(StubAdapter):
        name = "intake-usage-test"

        def run(self, prompt, workdir, model, timeout=600):
            root = Path(workdir)
            (root / "docs").mkdir(exist_ok=True)
            (root / "docs" / "design.md").write_text(
                "# Design\nPython entry point: src/main.py\n", encoding="utf-8"
            )
            (root / "src").mkdir(exist_ok=True)
            (root / "src" / "main.py").write_text("print('OK')\n", encoding="utf-8")
            return super().run(prompt, workdir, model, timeout)

    adapter = DeliveringExecutor([ok_result(
        "# 六节报告\n## 1. 改动清单\ndocs/design.md、src/main.py\n"
        "## 2. 命令记录\n离线测试执行体创建交付文件\n"
        "## 3. 证据链\n工作区文件\n## 4. 四要素\n目标、范围、交付、验收\n"
        "## 5. 未完成事项\n无\n## 6. 模型自述\n测试替身\n"
    )])
    review_model = Mock(side_effect=lambda *args, **kwargs: pass_route())
    monkeypatch.setattr(reviewer.router, "call", review_model)
    contracts.register(adapter.name, adapter)
    try:
        created = intake.start_project(
            project_id, project_id, str(workspace),
            "创建一个输出 OK 的 Python 程序及设计文档。",
            default_adapter=adapter.name,
        )
        assert created["tasks"] == 5
        for _ in range(12):
            scheduler.schedule_once(project_id)
            if all(t["exec_status"] == "DONE" for t in db.list_tasks(project_id)):
                break

        tasks = db.list_tasks(project_id)
        assert len(tasks) == 5
        assert {t["exec_status"] for t in tasks} == {"DONE"}
        assert adapter.total_calls == 5
        assert review_model.call_count == 5
        assert all(t["state"] == "DONE" for t in plan.snapshot(project_id)["tasks"])

        rows = events.read(project=project_id)
        calls = [row for row in rows if row["action"] == "model:call"]
        assert len(calls) == 5
        assert all(row["extra"]["usage"]["total_tokens"] == 2 for row in calls)
        for task in tasks:
            chain = [r["action"] for r in rows if r.get("taskId") == task["task_id"]]
            assert chain.count("gate:pass") == 1
            assert chain.count("task:done") == 1
            assert chain.index("gate:pass") < chain.index("task:done")
            assert Path(task["report_path"]).is_file()

        aggregator = UsageAggregator()
        assert aggregator.scan() == 5
        assert aggregator.by_project(project_id)["total_tokens"] == 10
        for task in tasks:
            usage = aggregator.by_task(task["task_id"])
            assert usage["total_tokens"] == 2
            assert usage["call_count"] == 1
            assert usage["unknown_usage"] == 0
            stored = governance_store.query_usage(task_id=task["task_id"])
            assert stored[0]["role"] == task["assignee"]
            call = next(row for row in calls if row["taskId"] == task["task_id"])
            assert stored[0]["model"] == call["extra"]["model"]
    finally:
        contracts.unregister(adapter.name)


def test_repeated_event_scan_does_not_duplicate_usage(fleet_env, monkeypatch):
    """重复扫描及新聚合器实例不能再次计入同一事件，新事件仍正常入账。"""
    monkeypatch.setattr(governance_store, "_db_path", fleet_env["data"] / "governance.db")
    events.append(
        actor="manager", action="model:call", task_id="T-usage", project="P-usage",
        extra={"role": "worker", "model": "demo", "usage": {
            "prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5,
        }},
    )
    aggregator = UsageAggregator()
    assert aggregator.scan() == 1
    second_scan = UsageAggregator().scan()
    assert aggregator.by_project("P-usage")["total_tokens"] == 5
    assert second_scan == 0
    assert aggregator.by_task("T-usage")["call_count"] == 1

    events.append(
        actor="manager", action="model:call", task_id="T-usage", project="P-usage",
        extra={"role": "worker", "model": "demo", "usage": {"total_tokens": 5}},
    )
    assert aggregator.scan() == 1
    assert aggregator.by_project("P-usage")["total_tokens"] == 10
    assert aggregator.by_task("T-usage")["call_count"] == 2

