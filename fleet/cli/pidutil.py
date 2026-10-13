"""fleet CLI 进程管理辅助（pidfile + down 命令）。

pidfile 格式（JSON）：
  {"api": <pid>, "worker": <pid>, "watchdog": <pid|null>, "port": <port>, "started": <iso8601>}
"""

from __future__ import annotations

import json
import os
import signal
import time
from pathlib import Path

from fleet.core.paths import paths


def pidfile_path() -> Path:
    return paths().data_dir / "fleet.pid"


def write_pidfile(info: dict) -> None:
    pidfile_path().parent.mkdir(parents=True, exist_ok=True)
    pidfile_path().write_text(json.dumps(info, ensure_ascii=False), encoding="utf-8")


def read_pidfile() -> dict | None:
    p = pidfile_path()
    if not p.is_file():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def _kill_pid(pid: int, gentle: bool = True) -> bool:
    """终止进程，先 SIGTERM 再 SIGKILL。"""
    if pid <= 0:
        return False
    try:
        if gentle:
            os.kill(pid, signal.SIGTERM)
            for _ in range(10):
                time.sleep(0.3)
                try:
                    os.kill(pid, 0)
                except ProcessLookupError:
                    return True
            os.kill(pid, signal.SIGKILL)
        else:
            os.kill(pid, signal.SIGKILL)
        return True
    except ProcessLookupError:
        return True
    except Exception:
        return False


def stop_fleet() -> dict:
    """停止 fleet up 拉起的所有进程。返回 {watchdog/api/worker} 各自的停止结果。
    停止顺序：watchdog → api → worker（watchdog 先停，避免它把刚停下的 api 又拉起）。"""
    info = read_pidfile()
    if not info:
        return {"stopped": False, "reason": "无 pidfile（fleet 未运行或未通过 fleet up 启动）"}
    results = {}
    for key in ("watchdog", "api", "worker"):
        pid = info.get(key)
        if pid:
            ok = _kill_pid(pid)
            results[key] = {"pid": pid, "stopped": ok}
        else:
            results[key] = {"pid": None, "stopped": True, "reason": "未启动"}
    # 清理 pidfile
    try:
        pidfile_path().unlink()
    except Exception:
        pass
    return {"stopped": True, "details": results}
