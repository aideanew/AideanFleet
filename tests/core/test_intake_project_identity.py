"""CLI 注册后从对话启动，必须复用同一项目。"""

from fleet.core import db
from fleet.manager import intake


def test_dialogue_intake_reuses_cli_registered_project(fleet_env, monkeypatch):
    workspace_root = fleet_env["root"] / "workspaces"
    workspace_root.mkdir()
    workspace = workspace_root / "Test09171500"
    workspace.mkdir()
    monkeypatch.setenv("FLEET_ALLOWED_ROOTS", str(workspace_root))
    db.create_project("P-007", "Test09171500", str(workspace))
    print("CLI-registered project:", [
        {key: project.get(key) for key in ("project_id", "name", "path")}
        for project in db.list_projects()
    ])

    intent = intake.detect_launch_intent(
        f"启动新项目 Test09171500（工作区：{workspace}）"
    )
    assert intent is not None
    name, directory = intent
    result = intake.start_project(name, name, directory, "最简动态表格")

    matching = [p for p in db.list_projects() if p["name"] == name]
    assert len(matching) == 1
    assert result["project"] == "P-007"
    assert len(db.list_tasks("P-007")) == 5
    assert db.list_tasks(name) == []


def test_manager_owns_planning_not_implementation():
    stages = intake._plan_templates("创建最简动态表格；Manager 负责规划，其他角色实现与测试")
    assert stages[0][1][0]["assignee"] == "manager"
    assert all(task["assignee"] != "manager" for _, tasks in stages[1:] for task in tasks)
