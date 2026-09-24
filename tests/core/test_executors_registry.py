"""执行体运行时登记表（需求4）：begin/end/snapshot 与线程上下文。"""

import threading

from fleet.executors import registry


class FakeProc:
    """替身 Popen：poll()=None 表示存活；置 code 模拟进程退出。"""

    def __init__(self, pid, code=None):
        self.pid = pid
        self.code = code

    def poll(self):
        return self.code


def _clear():
    registry._entries.clear()


def test_begin_snapshot_end_roundtrip():
    _clear()
    proc = FakeProc(4242)
    key = registry.begin(["C:/tools/opencode.exe", "run"], cwd="E:/ws", adapter="opencode", proc=proc, label="opencode")
    assert key is not None
    rows = registry.snapshot()
    assert len(rows) == 1
    row = rows[0]
    assert row["pid"] == 4242
    assert row["process_name"] == "opencode"
    assert row["adapter"] == "opencode"
    assert row["alive"] is True
    assert row["elapsed_s"] >= 0
    assert "proc" not in row
    registry.end(key)
    assert registry.snapshot() == []
    _clear()


def test_same_pid_multiple_spawns_do_not_collide():
    """回归：Windows 时钟 ~15ms 分辨率时代键曾互相覆盖，代际计数器保证不丢条目。"""
    _clear()
    k1 = registry.begin(["python"], proc=FakeProc(7))
    k2 = registry.begin(["python"], proc=FakeProc(7))
    assert k1 != k2
    assert len(registry.snapshot()) == 2
    registry.end(k1)
    registry.end(k2)
    _clear()


def test_dead_process_is_reaped_by_snapshot():
    _clear()
    proc = FakeProc(8)
    registry.begin(["python"], proc=proc)
    assert len(registry.snapshot()) == 1
    proc.code = 0  # 进程退出
    assert registry.snapshot() == []
    assert registry._entries == {}
    _clear()


def test_run_context_capture_and_restore():
    registry.clear_run_context()
    proc = FakeProc(9)
    with registry.run_context(task_id="P-1-T01", role="fe-1", adapter="opencode", project="P-1", model="m"):
        key = registry.begin(["python"], proc=proc)
        row = registry.snapshot()[0]
        assert row["task_id"] == "P-1-T01"
        assert row["role"] == "fe-1"
        assert row["project"] == "P-1"
    # 上下文退出后线程本地恢复为空
    assert registry.get_run_context() == {}
    registry.end(key)
    _clear()


def test_context_is_thread_local():
    registry.clear_run_context()
    registry.set_run_context(task_id="MAIN")
    seen = {}

    def worker():
        seen["ctx"] = registry.get_run_context()

    thread = threading.Thread(target=worker)
    thread.start()
    thread.join()
    assert seen["ctx"] == {}
    assert registry.get_run_context() == {"task_id": "MAIN"}
    registry.clear_run_context()


def test_begin_without_pid_returns_none():
    _clear()
    assert registry.begin(["python"], proc=FakeProc(0)) is None
    assert registry.begin(["python"], proc=None) is None
    registry.end(None)  # 幂等：None 安全
    _clear()
