"""对话驱动项目启动（intake）测试：指令识别 → 建册 → 调度推进（fleet_env 隔离环境）"""
from fleet.manager import intake, scheduler


def test_detect_launch_intent():
    msg = ("启动新项目 Test09161119（工作区 E:\\Demo\\Test09161119）："
           "开发一个网页版坦克大战游戏。执行策略切换为「自动执行」（auto）。")
    intent = intake.detect_launch_intent(msg)
    assert intent is not None
    pid, workspace = intent
    assert pid == "Test09161119"
    assert workspace.replace("/", "\\").lower().startswith("e:\\demo")
    assert intake.detect_mode(msg) == "auto"
    # 反例：普通对话不触发
    assert intake.detect_launch_intent("今天天气怎么样？") is None
    assert intake.detect_mode("今天天气怎么样？") is None


def test_start_project_creates_plan_and_tasks(fleet_env, monkeypatch):
    from fleet.core import db as fleet_db
    from fleet.core import plan as plan_mod

    ws_parent = fleet_env["root"] / "demo"
    ws_parent.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("FLEET_ALLOWED_ROOTS", str(ws_parent))
    workspace = str(ws_parent / "Test09161119")

    result = intake.start_project(
        "Test09161119", "Test09161119", workspace,
        "开发一个网页版坦克大战游戏。执行策略切换为「自动执行」（auto）。",
        default_adapter="stub",
    )
    assert result["tasks"] == 5
    assert result["stages"] == 3
    assert fleet_db.get_project("Test09161119") is not None
    tasks = fleet_db.list_tasks("Test09161119")
    assert len(tasks) == 5
    assert all(t["exec_status"] == "DRAFT" for t in tasks)

    # 计划快照应含三级阶段（中文键），任务已登记
    snap = plan_mod.snapshot("Test09161119")
    assert len(snap.get("阶段") or snap.get("stages") or []) == 3


def test_schedule_progresses_tasks(fleet_env, monkeypatch):
    """建册后调度一轮：至少一个任务离开 DRAFT（进入派工/执行/门/审查/返工任一环节）"""
    from fleet.core import db as fleet_db

    ws_parent = fleet_env["root"] / "demo"
    ws_parent.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("FLEET_ALLOWED_ROOTS", str(ws_parent))

    intake.start_project(
        "DemoProj", "DemoProj", str(ws_parent / "DemoProj"),
        "做一个坦克大战（自动执行）", default_adapter="stub",
    )
    outcomes = scheduler.schedule_once("DemoProj")
    assert outcomes, "首轮调度应有 READY 任务被派工"

    tasks = fleet_db.list_tasks("DemoProj")
    states = {t["task_id"]: t["exec_status"] for t in tasks}
    progressed = [s for s in states.values() if s != "DRAFT"]
    assert progressed, f"首轮调度后应有任务推进：{states}"
