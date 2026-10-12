"""P3-A-3: MockWriteAdapter 端到端测试

验证 MockWriteAdapter 能从 intake 跑到 DONE（无真 LLM）。
"""
import os
import pathlib

from fleet.core import db, events, config
from fleet.executors.mock_write import MockWriteAdapter
from fleet.governance import store as governance_store
from fleet.governance.usage import UsageAggregator
from fleet.manager import contracts, intake, reviewer, scheduler

from tests.core.stubs import pass_route
from unittest.mock import Mock


def test_e2e_mock_write(fleet_env, monkeypatch):
    """MockWriteAdapter 从 intake 到 DONE 全流程。"""
    config.allow_write(True)
    db.init_db()

    project_id = "MockWriteE2E"
    workspace = fleet_env["root"] / project_id
    workspace.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("FLEET_ALLOWED_ROOTS", str(fleet_env["root"]))

    adapter = MockWriteAdapter()
    contracts.register("mock-write", adapter)

    # reviewer 放行
    review_model = Mock(side_effect=lambda *args, **kwargs: pass_route())
    monkeypatch.setattr(reviewer.router, "call", review_model)

    created = intake.start_project(
        project_id, project_id, str(workspace),
        "创建一个输出 OK 的 Python 程序及设计文档。",
        default_adapter="mock-write",
    )
    assert created["tasks"] == 5

    # 清空 allowed_files 避免 cross-task 干扰（与 P1-B-1 测试同因）
    for t in db.list_tasks(project_id):
        db.update_task(t["task_id"], allowed_files="", forbidden_files="")

    # 跑调度循环
    for _ in range(15):
        scheduler.schedule_once(project_id)
        if all(t["exec_status"] == "DONE" for t in db.list_tasks(project_id)):
            break

    tasks = db.list_tasks(project_id)
    assert len(tasks) == 5
    statuses = {t["exec_status"] for t in tasks}
    assert statuses == {"DONE"}, f"Expected all DONE, got {statuses}"

    # 验证文件实际存在
    assert (workspace / "docs" / "design.md").exists(), "docs/design.md should exist"
    assert (workspace / "src").exists(), "src/ should exist"

    # 验证 adapter 被调用
    assert adapter.call_count >= 5, f"Expected >= 5 calls, got {adapter.call_count}"
