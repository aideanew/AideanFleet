"""P5-B-1: watchdog 超时检测测试

验证 fleet/rel/retry_timer.scan 对 DOING 任务的超时检测：到阈值发 task:stuck，
到 2 倍阈值升级 BLOCKED。
"""
import datetime
import sqlite3

from fleet.core import db, events
from fleet.core.paths import paths
from fleet.rel import retry_timer


def _set_old_updated_at(task_id: str, hours_ago: int = 2) -> None:
    """直接写 SQLite 设置 updated_at 为 N 小时前（绕过 update_task 的自动刷新）。"""
    old = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=hours_ago)).isoformat()
    conn = sqlite3.connect(paths().db_file)
    conn.execute("UPDATE tasks SET updated_at = ? WHERE task_id = ?", (old, task_id))
    conn.commit()
    conn.close()


def test_watchdog_stuck_detection(fleet_env):
    """DOING 任务超过 stuck_seconds → 发 task:stuck 事件。"""
    db.init_db()

    project_id = "WatchdogTest"
    ws = str(fleet_env["root"] / "watchdog-test")
    db.create_project(project_id, project_id, ws)

    task = db.create_task({
        "project_id": project_id,
        "task_id": f"{project_id}-T01",
        "title": "超时测试任务",
        "detail": "测试 watchdog",
        "assignee": "test",
        "reviewer": "reviewer-1",
        "verify_cmd": "true",
        "workspace": ws,
    })

    db.transition(task["task_id"], "ASSIGNED")
    db.transition(task["task_id"], "DOING")

    # 直接写 DB 设置 updated_at 为 2 小时前
    _set_old_updated_at(task["task_id"], hours_ago=2)

    # 扫描（stuck_seconds=60 → 1分钟阈值，2倍=120s → BLOCKED）
    actions = retry_timer.scan(project_id, stuck_seconds=60)

    # 2小时(7200s) > 120s(2x阈值) → 应该升级 BLOCKED
    assert len(actions) > 0, f"Expected stuck/block actions, got {len(actions)}"

    rows = events.read(project=project_id)
    stuck_events = [r for r in rows if r.get("action") in ("task:stuck", "task:stuck_escalated")]
    assert len(stuck_events) >= 1, f"Expected stuck event, got {len(stuck_events)}"


def test_watchdog_normal_task_not_flagged(fleet_env):
    """DOING 任务在阈值内 → 不触发 stuck。"""
    db.init_db()

    project_id = "WatchdogNormal"
    ws = str(fleet_env["root"] / "watchdog-normal")
    db.create_project(project_id, project_id, ws)

    task = db.create_task({
        "project_id": project_id,
        "task_id": f"{project_id}-T01",
        "title": "正常任务",
        "detail": "测试 watchdog",
        "assignee": "test",
        "reviewer": "reviewer-1",
        "verify_cmd": "true",
        "workspace": ws,
    })

    db.transition(task["task_id"], "ASSIGNED")
    db.transition(task["task_id"], "DOING")

    # 刚开始，不超时
    actions = retry_timer.scan(project_id, stuck_seconds=3600)
    assert len(actions) == 0, f"Normal task should not be flagged, got {actions}"
