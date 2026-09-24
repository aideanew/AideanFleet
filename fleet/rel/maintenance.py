"""这是什么：server 进程内的轻维护挂载（REL-01 §9.4 + §9.3）。由 server.py startup 探测式调用。
职责：启动时做一次事件归档轮转（幂等），并起一个后台线程周期性跑卡死扫描。
边界：绝不阻塞/影响请求处理——轮转与扫描全部包在 try/except 里，失败只记录不抛出。
"""

from __future__ import annotations

import threading
import time
from typing import Any

from . import archive, retry_timer

#: 卡死扫描周期（秒）
STUCK_SCAN_INTERVAL = 60.0

_state = {"started": False, "lock": threading.Lock()}


def start(*, rotate: bool = True, stuck_interval: float = STUCK_SCAN_INTERVAL) -> dict[str, Any]:
    """进程内只启动一次（幂等）：同步轮转一次 + 后台卡死扫描线程。"""
    with _state["lock"]:
        if _state["started"]:
            return {"started": False, "reason": "already_started"}
        _state["started"] = True

    result: dict[str, Any] = {"started": True}
    if rotate:
        try:
            result["rotated"] = archive.rotate_events()
        except Exception as error:  # 归档失败不阻塞控制台启动
            result["rotate_error"] = str(error)

    def _loop() -> None:
        while True:
            time.sleep(stuck_interval)
            try:
                retry_timer.scan()
            except Exception:
                pass  # 守望循环绝不允许带崩 server

    threading.Thread(target=_loop, daemon=True, name="rel-maintenance").start()
    return result


def reset_for_tests() -> None:
    """测试夹具用：允许同一进程内重复 start()。"""
    with _state["lock"]:
        _state["started"] = False
