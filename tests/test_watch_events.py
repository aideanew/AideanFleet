"""事件监控循环测试（新契约：全局事件流 data/events.jsonl + action 字段；monkeypatch 隔离真实流）"""

import json
import threading
from pathlib import Path

import fleet.core.events as events_module
import fleet.notify.triggers as triggers_module
from fleet.notify.triggers import EventType, NotificationTrigger, watch_events_loop


def _make_trigger(test_results):
    """构造触发器：TASK_COMPLETED 开启 + 测试回调（不真发邮件）"""
    trigger = NotificationTrigger()
    trigger.set_enabled(EventType.TASK_COMPLETED, True)

    def test_callback(subject, body):
        test_results.append({"subject": subject, "body": body})
        return True, "测试发送成功"

    trigger.register_sender(test_callback)
    return trigger


def _run_watch_once(project_id, trigger, monkeypatch, events_file):
    """在隔离事件文件上跑 watch loop，两轮后中断；返回监控线程"""
    monkeypatch.setattr(events_module, "events_file", lambda: events_file)
    stop_event = threading.Event()
    call_count = [0]
    original_sleep = triggers_module.time.sleep

    def mock_sleep(seconds):
        call_count[0] += 1
        if call_count[0] > 2:
            stop_event.set()
            raise KeyboardInterrupt()
        original_sleep(0.05)

    monkeypatch.setattr(triggers_module.time, "sleep", mock_sleep)
    thread = threading.Thread(
        target=lambda: _watch_guarded(project_id, trigger, stop_event, triggers_module, original_sleep),
        daemon=True,
    )
    thread.start()
    stop_event.wait(timeout=5)
    thread.join(timeout=2)
    return thread


def _watch_guarded(project_id, trigger, stop_event, triggers_module, original_sleep):
    call_count = [0]

    def mock_sleep(seconds):
        call_count[0] += 1
        if call_count[0] > 2:
            stop_event.set()
            raise KeyboardInterrupt()
        original_sleep(0.05)

    triggers_module.time.sleep = mock_sleep
    try:
        watch_events_loop(project_id, trigger)
    except KeyboardInterrupt:
        pass
    finally:
        triggers_module.time.sleep = original_sleep


def _event(action="task:done", task_id="T-1", summary="任务完成测试", project="test-project"):
    """按 core/events 契约构造真实形态事件（含 project 字段：watch 循环按项目过滤）"""
    return {
        "timestamp": "2026-09-16T10:00:00",
        "action": action,
        "taskId": task_id,
        "summary": summary,
        "project": project,
    }


def _last_seq_file(project_id):
    last_seq_file = Path(f"data/notify/{project_id}.last_seq")
    last_seq_file.parent.mkdir(parents=True, exist_ok=True)
    return last_seq_file


def test_watch_events_loop_basic(tmp_path, monkeypatch):
    """基本功能：本项目 task:done 触发通知回调，last_seq 持久化到新路径"""
    events_file = tmp_path / "events.jsonl"
    events_file.write_text(
        json.dumps(_event(project="test-watch-basic"), ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    last_seq_file = _last_seq_file("test-watch-basic")
    last_seq_file.write_text("0", encoding="utf-8")  # 从头处理预写事件

    test_results = []
    trigger = _make_trigger(test_results)
    _run_watch_once("test-watch-basic", trigger, monkeypatch, events_file)

    assert len(test_results) == 1
    # 新契约：主题携带当前进度百分比（空项目/无任务时为 0%）
    assert test_results[0]["subject"] == "[AideanFleet][test-watch-basic] 任务已完成 · 进度 0%"
    assert "任务完成测试" in test_results[0]["body"]
    assert int(last_seq_file.read_text(encoding="utf-8").strip()) == 1
    last_seq_file.unlink()


def test_watch_events_loop_project_filter(tmp_path, monkeypatch):
    """项目过滤：其他项目与无 project 字段的通知类事件一律跳过（根修跨项目重复刷屏）"""
    events_file = tmp_path / "events.jsonl"
    events_file.write_text(
        json.dumps(_event(task_id="T-other", summary="别的事件", project="other-project"), ensure_ascii=False) + "\n"
        + json.dumps({"timestamp": "2026-09-16T10:00:01", "action": "task:done", "taskId": "T-noproj",
                      "summary": "无项目字段事件"}, ensure_ascii=False) + "\n"
        + json.dumps(_event(task_id="T-mine", summary="本项目事件", project="test-watch-filter"), ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    last_seq_file = _last_seq_file("test-watch-filter")
    last_seq_file.write_text("0", encoding="utf-8")

    test_results = []
    trigger = _make_trigger(test_results)
    _run_watch_once("test-watch-filter", trigger, monkeypatch, events_file)

    assert len(test_results) == 1
    assert "本项目事件" in test_results[0]["body"]
    # 三个事件全部推进 seq（含被项目过滤跳过的两个）
    assert int(last_seq_file.read_text(encoding="utf-8").strip()) == 3
    last_seq_file.unlink()


def test_watch_events_loop_idempotent(tmp_path, monkeypatch):
    """幂等性：last_seq=1 时只处理第二个事件"""
    events_file = tmp_path / "events.jsonl"
    events_file.write_text(
        json.dumps(_event(task_id="T-1", summary="第一条", project="test-watch-idempotent"), ensure_ascii=False) + "\n"
        + json.dumps(_event(task_id="T-2", summary="第二条", project="test-watch-idempotent"), ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    last_seq_file = _last_seq_file("test-watch-idempotent")
    last_seq_file.write_text("1", encoding="utf-8")  # 模拟第一条已处理

    test_results = []
    trigger = _make_trigger(test_results)
    _run_watch_once("test-watch-idempotent", trigger, monkeypatch, events_file)

    assert len(test_results) == 1
    assert "第二条" in test_results[0]["body"]
    last_seq_file.unlink()


def test_watch_events_loop_invalid_event(tmp_path, monkeypatch):
    """无效事件：JSON 解析失败与非触发类 action（chat）均被跳过，有效事件正常触发"""
    events_file = tmp_path / "events.jsonl"
    events_file.write_text(
        "invalid json\n"
        + json.dumps(_event(action="chat", task_id="T-x", summary="非通知类事件", project="test-watch-invalid"), ensure_ascii=False) + "\n"
        + json.dumps(_event(task_id="T-ok", summary="有效事件", project="test-watch-invalid"), ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    last_seq_file = _last_seq_file("test-watch-invalid")
    last_seq_file.write_text("0", encoding="utf-8")

    test_results = []
    trigger = _make_trigger(test_results)
    _run_watch_once("test-watch-invalid", trigger, monkeypatch, events_file)

    assert len(test_results) == 1
    assert "有效事件" in test_results[0]["body"]
    # 无效 JSON 与非通知类事件也推进 seq（新契约：无条件持久化）
    assert int(last_seq_file.read_text(encoding="utf-8").strip()) == 3
    last_seq_file.unlink()
