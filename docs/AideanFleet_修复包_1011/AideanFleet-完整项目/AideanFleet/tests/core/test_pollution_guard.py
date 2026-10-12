"""执行体路径污染守卫：机器门必须拦截把绝对路径压扁成单层目录的产物。"""

from __future__ import annotations

import json
from pathlib import Path

from fleet.core import db
from fleet.gates import verify
from fleet.manager import contracts, intake, reviewer, scheduler
from tests.core.stubs import StubAdapter, ok_result, pass_route

# 2026-09-17 事故在 E:/Demo/Test09171131 留下的全部 40 个压扁目录名（执行日志核实）
ACCIDENT_FLATTENED_NAMES = [
    ".githubworkflows", "publicimages", "srcapp", "srcapplayout", "srcappproviders",
    "srcfeatures", "srcfeaturestable", "srcfeaturestablecore", "srcfeaturestabledata",
    "srcfeaturestablehooks", "srcfeaturestablestore", "srcfeaturestabletypes",
    "srcfeaturestableui", "srcfeaturestableuianimations", "srcfeaturestableuirenderers",
    "srcpages", "srcpagesDashboard", "srcpagesSettings", "srcpagesTableView",
    "srcshared", "srcsharedcomponents", "srcsharedcomponentsAvatar",
    "srcsharedcomponentsBadge", "srcsharedcomponentsButton", "srcsharedcomponentsDropdown",
    "srcsharedcomponentsInput", "srcsharedcomponentsModal", "srcsharedcomponentsSelect",
    "srcsharedcomponentsSkeleton", "srcsharedcomponentsSpinner", "srcsharedcomponentsTooltip",
    "srcsharedconstants", "srcsharedhooks", "srcsharedstyles", "srcsharedtypes",
    "srcsharedutils", "testse2e", "testsfixtures", "testsintegration", "testsunit",
]

SIX_SECTION_REPORT = (
    "# 六节报告\n## 1. 改动清单\ndocs/design.md\n## 2. 命令记录\nmkdir src\\features\\table\\store\n"
    "## 3. 证据链\n见工作区\n## 4. 四要素\n目标、范围、交付、验收\n"
    "## 5. 未完成事项\n无\n## 6. 模型自述\n测试"
)


class PollutingExecutor(StubAdapter):
    """复刻真实事故：交付合法文件的同时，在工作区根目录留下压扁路径空目录。"""

    name = "polluting-test"

    def run(self, prompt, workdir, model, timeout=600):
        root = Path(workdir)
        (root / "docs").mkdir(parents=True, exist_ok=True)
        (root / "docs" / "design.md").write_text("# Design\n", encoding="utf-8")
        (root / "srcfeaturestablestore").mkdir(exist_ok=True)
        return super().run(prompt, workdir, model, timeout)


def test_accident_names_all_detected():
    """事故真实 40 个压扁名必须全量命中，正常结构与合法单层目录零误报。"""
    import tempfile

    with tempfile.TemporaryDirectory() as ws:
        root = Path(ws)
        for name in ACCIDENT_FLATTENED_NAMES:
            (root / name).mkdir()
        # 反例：正常嵌套树 + 合法单层目录 + 与压扁名并存的真实层级
        (root / "src" / "features" / "table" / "store").mkdir(parents=True)
        (root / "src" / "shared" / "components" / "Avatar").mkdir(parents=True)
        (root / "docs").mkdir()
        (root / "tests").mkdir()
        (root / "public").mkdir()
        (root / "srcapp").mkdir(exist_ok=True)  # 事故名与真实层级并存的形态
        hits = verify.flattened_path_dirs(root)
        missed = set(ACCIDENT_FLATTENED_NAMES) - set(hits)
        assert not missed, f"守卫漏报 {len(missed)} 个事故形态: {sorted(missed)[:8]}"
        assert "src" not in hits and "docs" not in hits and "tests" not in hits and "public" not in hits


def test_gate_rejects_flattened_path_pollution(fleet_env, monkeypatch):
    """压扁路径空目录存在 → 机器门必须 failed 并给出 flattened_path 原因，任务不得 DONE。"""
    monkeypatch.setenv("FLEET_ALLOWED_ROOTS", str(fleet_env["root"] / "ws"))
    adapter = PollutingExecutor([ok_result(SIX_SECTION_REPORT)])
    contracts.register(adapter.name, adapter)
    monkeypatch.setattr(reviewer.router, "call",
                        lambda *args, **kwargs: __import__("tests.core.stubs", fromlist=["pass_route"]).pass_route())
    project_id = "Pollute01"
    intake.start_project(
        project_id, project_id, str(fleet_env["root"] / "ws" / project_id),
        "做动态表格。", default_adapter=adapter.name,
    )
    task_id = f"{project_id}-T01"
    for _ in range(12):
        scheduler.schedule_once(project_id)
        if db.get_task(task_id)["exec_status"] in ("DONE", "REWORK", "BLOCKED", "ESCALATED"):
            break

    task = db.get_task(task_id)
    assert task["exec_status"] != "DONE", "压扁路径污染未拦截，任务带污染到达 DONE"
    gate_file = (fleet_env["data"] / "projects" / project_id / "evidence" / task_id / "gate.json")
    assert gate_file.exists(), "机器门没有落盘结果"
    reasons = json.loads(gate_file.read_text(encoding="utf-8")).get("reasons", [])
    assert any("flattened_path_dirs" in reason for reason in reasons), reasons
