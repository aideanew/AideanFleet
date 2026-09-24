"""执行体运行时登记表（需求4：谁在执行 / PID / 进程名 / 运行时长）

定位：控制台与调度器同进程（fleet/console/server.py 的 _on_startup 线程 +
/api 内联派工），因此进程内登记表即可覆盖"当前执行体"读数，无需 IPC。

链路：
  dispatcher._run_with_chain → run_context(task_id/role/adapter/project) 线程上下文
  → adapter.run → base.run_subprocess_tree_safe 的 Popen 创建点
  → begin() 登记（pid/进程名/命令行/cwd/上下文/起始时刻）
  → finally end() 注销；长驻进程（hermes Manager 网关）登记后不注销，靠 poll() 判活。

线程安全：登记表单锁；上下文 threading.local，跨线程取用为零副作用默认空。
任何内部异常都被吞掉——可观测性是旁路，绝不允许拖垮执行体本身。
"""

from __future__ import annotations

import itertools
import os
import threading
import time
from contextlib import contextmanager
from typing import Any

#: 登记键的代际计数器：Windows 下 time.time() 约 15ms 分辨率，同进程连续 spawn
#: 会撞 key 互相覆盖，必须用进程内单调递增的代际号做后缀。
_seq = itertools.count(1)

#: 登记表容量上限（防泄漏：异常路径漏 end() 时按最早登记丢弃）
_MAX_ENTRIES = 256

_local = threading.local()
_entries: dict[tuple[int, float], dict[str, Any]] = {}
_lock = threading.RLock()


# ---------------------------------------------------------------------------
# 线程上下文：dispatcher 在进入 adapter.run 前写入，Popen 创建点读取
# ---------------------------------------------------------------------------

def set_run_context(**fields: Any) -> None:
    """写入当前线程的执行上下文（task_id/role/adapter/project/model）。"""
    ctx = getattr(_local, "ctx", None)
    if ctx is None:
        ctx = {}
        _local.ctx = ctx
    ctx.update(fields)


def get_run_context() -> dict[str, Any]:
    """读取当前线程执行上下文（未设置返回空 dict，不抛异常）。"""
    return dict(getattr(_local, "ctx", {}) or {})


def clear_run_context() -> None:
    """清空当前线程执行上下文。"""
    _local.ctx = {}


@contextmanager
def run_context(**fields: Any):
    """上下文管理器版：with run_context(task_id=...): adapter.run(...)。

    previous 必须存副本：set_run_context 是对 _local.ctx 的原地 update，
    若存引用则退出时恢复的还是被改过的同一个 dict，任务上下文会泄漏到后续派工。
    """
    previous = dict(getattr(_local, "ctx", {}) or {})
    try:
        set_run_context(**fields)
        yield
    finally:
        _local.ctx = previous


# ---------------------------------------------------------------------------
# 登记表：begin/end/snapshot
# ---------------------------------------------------------------------------

def _process_name(cmd: Any) -> str:
    first = str(cmd[0]) if cmd else ""
    return os.path.basename(first.replace("\\", "/"))


def begin(cmd: Any, cwd: str | None = None, adapter: str = "", proc: Any = None,
          label: str = "") -> "tuple[int, float] | None":
    """Popen 创建后登记一条运行记录，返回登记表键（失败返回 None，绝不上抛）。"""
    try:
        pid = int(getattr(proc, "pid", 0) or 0)
        if not pid:
            return None
        ctx = get_run_context()
        key = (pid, next(_seq))
        entry = {
            "key": f"{pid}@{key[1]}",
            "pid": pid,
            "process_name": label or _process_name(cmd),
            "adapter": adapter or str(ctx.get("adapter") or ""),
            "task_id": str(ctx.get("task_id") or ""),
            "role": str(ctx.get("role") or ""),
            "project": str(ctx.get("project") or ""),
            "model": str(ctx.get("model") or ""),
            "cwd": str(cwd or ""),
            "cmd": [str(item) for item in list(cmd)[:8]] if cmd else [],
            "proc": proc,
            "started_monotonic": time.monotonic(),
            "started_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        }
        with _lock:
            if len(_entries) >= _MAX_ENTRIES:
                for stale in sorted(_entries.keys())[: len(_entries) - _MAX_ENTRIES + 1]:
                    _entries.pop(stale, None)
            _entries[key] = entry
        return key
    except Exception:
        return None


def end(key: tuple[int, float] | None) -> None:
    """注销一条运行记录（Popen 退出后的 finally 里调用；幂等）。"""
    if key is None:
        return
    try:
        with _lock:
            _entries.pop(key, None)
    except Exception:
        pass


def snapshot() -> list[dict[str, Any]]:
    """当前登记表快照（不含 Popen 对象）；按开始时间倒序。顺带回收已死的普通条目。"""
    now = time.monotonic()
    rows: list[dict[str, Any]] = []
    with _lock:
        for key, entry in list(_entries.items()):
            proc = entry.get("proc")
            try:
                alive = bool(proc is not None and proc.poll() is None)
            except Exception:
                alive = False
            if not alive:
                _entries.pop(key, None)  # 进程已退出：回收，避免泄漏（长驻网关同样按存活回收）
                continue
            row = {k: v for k, v in entry.items() if k != "proc"}
            row["alive"] = alive
            row["elapsed_s"] = round(now - entry["started_monotonic"], 1)
            rows.append(row)
    rows.sort(key=lambda item: item["started_at"], reverse=True)
    return rows
