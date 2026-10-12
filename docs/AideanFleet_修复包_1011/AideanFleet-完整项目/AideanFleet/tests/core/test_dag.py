"""这是什么：dag 引擎单测（环检测 / READY 判定 / 写冲突暂缓 / 依赖释放）。"""

from __future__ import annotations

import pytest

from fleet.core import db
from fleet.manager import dag as dag_engine

from .conftest import read_events
from .stubs import make_task


def test_detect_cycles_finds_cycle():
    deps = {"A": ["B"], "B": ["C"], "C": ["A"], "D": []}
    cycles = dag_engine.detect_cycles(deps)
    assert len(cycles) == 1
    assert set(cycles[0]) == {"A", "B", "C"}


def test_detect_cycles_acyclic_returns_empty():
    assert dag_engine.detect_cycles({"A": ["B"], "B": [], "C": []}) == []


def test_assert_acyclic_raises():
    with pytest.raises(dag_engine.CycleDetected):
        dag_engine.assert_acyclic({"A": ["A"]})


def test_create_task_rejects_cycle(project):
    from fleet.core import db as _db
    from fleet.manager import dispatcher
    from fleet.manager.contracts import TaskPack

    dispatcher.create_task(TaskPack(id="T-A", title="A", detail=""), project_id=project)
    dispatcher.create_task(TaskPack(id="T-B", title="B", detail=""), project_id=project, dependencies=["T-A"])
    # 把图改成环：A -> B -> A，之后任何新任务建入都应被拒绝
    _db.update_task("T-A", dependencies=["T-B"])
    with pytest.raises(dag_engine.CycleDetected):
        dispatcher.create_task(TaskPack(id="T-C", title="C", detail=""), project_id=project, dependencies=["T-A"])
    assert db.get_task("T-C") is None  # 成环不落库
    assert all(row["action"] != "task:created" or row["taskId"] != "T-C" for row in read_events(project))


def test_get_ready_tasks_dependency_and_conflict(project):
    make_task(project, "T-1", dependencies=["T-2"], allowed="report/**")
    make_task(project, "T-2")
    make_task(project, "T-4", allowed="src/**")
    for task_id in ("T-1", "T-2", "T-4"):
        db.transition(task_id, "ASSIGNED")
    # T-2 尚未 DONE：T-1 不 READY；T-4 无冲突：READY
    ready = [t["task_id"] for t in dag_engine.get_ready_tasks(project)]
    assert ready == ["T-2", "T-4"]

    # T-2 DONE 后 T-1 释放；与 T-4 无冲突时同批 READY
    db.transition("T-2", "DOING")
    db.transition("T-2", "SUBMITTED")
    db.transition("T-2", "REVIEWING")
    db.transition("T-2", "DONE")
    ready = [t["task_id"] for t in dag_engine.get_ready_tasks(project)]
    assert ready == ["T-1", "T-4"]


def test_get_ready_tasks_defers_on_write_conflict(project):
    make_task(project, "T-1", allowed="report/**")
    make_task(project, "T-2", allowed="src/**")
    db.transition("T-2", "ASSIGNED")
    db.transition("T-2", "DOING")
    make_task(project, "T-3", allowed="src/main.py")
    make_task(project, "T-4", allowed="docs/**")
    db.transition("T-1", "ASSIGNED")
    db.transition("T-3", "ASSIGNED")
    db.transition("T-4", "ASSIGNED")

    ready = [t["task_id"] for t in dag_engine.get_ready_tasks(project)]
    assert "T-3" not in ready  # 与 DOING 的 T-2 写范围冲突 -> 暂缓
    assert "T-1" in ready and "T-4" in ready
    deferred = [row for row in read_events(project) if row["action"] == "task:deferred"]
    assert len(deferred) == 1 and deferred[0]["taskId"] == "T-3"

    # 冲突集不变时事件去重（不刷屏）
    dag_engine.get_ready_tasks(project)
    assert len([row for row in read_events(project) if row["action"] == "task:deferred"]) == 1


def test_release_dependents(project):
    make_task(project, "T-1")
    make_task(project, "T-2", dependencies=["T-1"])
    make_task(project, "T-3", dependencies=["T-2"])
    db.transition("T-2", "ASSIGNED")  # 只有 ASSIGNED 的候选会被"标记释放"
    db.transition("T-3", "ASSIGNED")
    # T-1 不是 DONE：不放行任何后继
    assert dag_engine.release_dependents("T-1") == []
    for target in ("ASSIGNED", "DOING", "SUBMITTED", "REVIEWING", "DONE"):
        db.transition("T-1", target)
    assert dag_engine.release_dependents("T-1") == ["T-2"]
