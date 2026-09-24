"""卡死检测与升级测试（REL-01 §9.3）：task:stuck 幂等、2 倍阈值升级 BLOCKED、配置读取回退。"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from fleet.core import db, events
from fleet.core.paths import paths
from fleet.rel import retry_timer

from tests.core.stubs import make_task
from tests.rel.conftest import read_events

NOW = datetime(2026, 9, 15, 12, 0, 0).astimezone()


def _doing_at(task_id: str, started_at: datetime) -> None:
    """造一条指定时刻的 task:doing 事件，并把任务推进到 DOING。"""
    db.transition_and_log(task_id, "ASSIGNED", actor="tester", summary="x")
    row = db.transition_and_log(task_id, "DOING", actor="tester", summary="进入执行")
    # 把刚写的 task:doing（以及 task:assigned）时间戳回拨到 started_at（测试造数）
    target = events.events_file()
    import json

    lines = []
    for line in target.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        event = json.loads(line)
        if event.get("taskId") == task_id:
            event["timestamp"] = started_at.isoformat(timespec="seconds")
        lines.append(json.dumps(event, ensure_ascii=False))
    target.write_text("\n".join(lines) + "\n", encoding="utf-8")
    events._CACHE["size"] = -1
    _ = row


def test_scan_below_threshold_is_noop(fleet_env, tmp_path):
    make_task("P-001", "T-S1", workspace=str(tmp_path / "ws1"))
    (tmp_path / "ws1").mkdir()
    _doing_at("T-S1", NOW - timedelta(seconds=60))
    actions = retry_timer.scan(stuck_seconds=1800, now=NOW)
    assert actions == []
    assert not [row for row in read_events() if row["action"].startswith("task:stuck")]


def test_scan_marks_stuck_once_then_stays_quiet(fleet_env, tmp_path):
    """到达阈值 -> task:stuck 恰好一次；再扫不发第二条（幂等）。"""
    ws = tmp_path / "ws2"
    ws.mkdir()
    make_task("P-001", "T-S2", workspace=str(ws))
    _doing_at("T-S2", NOW - timedelta(seconds=1900))

    first = retry_timer.scan(stuck_seconds=1800, now=NOW)
    assert first == [{"task_id": "T-S2", "action": "marked_stuck", "elapsed_seconds": 1900}]
    second = retry_timer.scan(stuck_seconds=1800, now=NOW)
    assert second == []
    stuck_rows = [row for row in read_events() if row["action"] == "task:stuck"]
    assert len(stuck_rows) == 1
    assert stuck_rows[0]["extra"]["threshold_seconds"] == 1800


def test_scan_escalates_to_blocked_at_double_threshold(fleet_env, tmp_path):
    """超过 2 倍阈值 -> DOING -> BLOCKED + task:stuck_escalated 事件，等人工释放。"""
    ws = tmp_path / "ws3"
    ws.mkdir()
    make_task("P-001", "T-S3", workspace=str(ws))
    _doing_at("T-S3", NOW - timedelta(seconds=3601))

    actions = retry_timer.scan(stuck_seconds=1800, now=NOW)
    assert actions == [{"task_id": "T-S3", "action": "escalated_blocked", "elapsed_seconds": 3601}]
    assert db.get_task("T-S3")["exec_status"] == "BLOCKED"
    escalated = [row for row in read_events() if row["action"] == "task:stuck_escalated"]
    assert len(escalated) == 1 and escalated[0]["extra"]["stuck_seconds"] == 3601
    # BLOCKED -> ASSIGNED 人工释放后重新计时（新 task:doing 周期）
    db.transition_and_log("T-S3", "ASSIGNED", actor="human", action="task:blocked_release", summary="人工释放")
    assert retry_timer.scan(stuck_seconds=1800, now=NOW) == []


def test_scan_ignores_non_doing_tasks(fleet_env, tmp_path):
    """SUBMITTED/REVIEWING 停留再久也不归卡死守望管（只管 DOING）。"""
    ws = tmp_path / "ws4"
    ws.mkdir()
    make_task("P-001", "T-S4", workspace=str(ws))
    db.transition_and_log("T-S4", "ASSIGNED", actor="tester", summary="x")
    db.transition_and_log("T-S4", "DOING", actor="tester", summary="y")
    db.transition_and_log("T-S4", "SUBMITTED", actor="tester", summary="z")
    assert retry_timer.scan(stuck_seconds=60, now=NOW + timedelta(hours=5)) == []


def test_task_stuck_seconds_default_and_env_override(fleet_env, monkeypatch):
    """缺省回 1800；.env [settings] 合法值生效；非法值回默认。"""
    assert retry_timer.task_stuck_seconds() == 1800  # 测试 .env 无 settings 段 -> 默认

    env_file = paths().env_file
    env_file.write_text(
        env_file.read_text(encoding="utf-8")
        + "\n# ===== [SECTION: settings] 可靠性参数 =====\nFLEET_SETTINGS_TASK_STUCK_SECONDS=60\n",
        encoding="utf-8",
    )
    from fleet.core import config

    config._CACHE.mtime_ns = None
    config._CACHE.values = {}
    config._CACHE.section_of = {}
    assert retry_timer.task_stuck_seconds() == 60

    env_file.write_text(
        env_file.read_text(encoding="utf-8").replace("FLEET_SETTINGS_TASK_STUCK_SECONDS=60", "FLEET_SETTINGS_TASK_STUCK_SECONDS=oops")
    )
    config._CACHE.mtime_ns = None
    config._CACHE.values = {}
    config._CACHE.section_of = {}
    assert retry_timer.task_stuck_seconds() == 1800


def test_stuck_event_seq_ordered_after_new_doing_cycle(fleet_env, tmp_path):
    """重新派工后的新 DOING 周期允许发新的 task:stuck（seq 必须晚于新 task:doing）。"""
    ws = tmp_path / "ws5"
    ws.mkdir()
    make_task("P-001", "T-S5", workspace=str(ws))
    _doing_at("T-S5", NOW - timedelta(seconds=2000))
    assert retry_timer.scan(stuck_seconds=1800, now=NOW)  # 第一周期标记

    # 人工释放并重新进入 DOING（新周期）：把新 task:doing 时间戳同样回拨，模拟卡了又一轮
    db.transition_and_log("T-S5", "BLOCKED", actor="human", summary="x")
    db.transition_and_log("T-S5", "ASSIGNED", actor="human", action="task:blocked_release", summary="y")
    db.transition_and_log("T-S5", "DOING", actor="tester", summary="第二轮执行")
    target = events.events_file()
    import json

    lines = []
    for line in target.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        event = json.loads(line)
        if event.get("taskId") == "T-S5" and event.get("action") == "task:doing" and event["seq"] >= 4:
            event["timestamp"] = (NOW - timedelta(seconds=2000)).isoformat(timespec="seconds")
        lines.append(json.dumps(event, ensure_ascii=False))
    target.write_text("\n".join(lines) + "\n", encoding="utf-8")
    events._CACHE["size"] = -1

    again = retry_timer.scan(stuck_seconds=1800, now=NOW)
    assert [item["action"] for item in again] == ["marked_stuck"]  # 新周期可再标记
    assert len([row for row in read_events() if row["action"] == "task:stuck"]) == 2
