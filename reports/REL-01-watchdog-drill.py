# 这是什么：REL-01 watchdog 实杀实拉演练（真实子进程 + 真实 HTTP 探活 + 真实事件落盘）。
# 运行：.venv/Scripts/python.exe reports/REL-01-watchdog-drill.py
# 说明：目标进程用最小 HTTP 服务（tests.rel.drill_target，探活语义与控制台 /api/health 一致）；
#       事件写入重定向到临时 FLEET_ROOT，结束自清理，不污染仓库 data/。
"""REL-01 watchdog 杀-拉演练：kill 子进程 -> watchdog 自动拉起 -> rel:restart 事件落盘。"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

_TMP = Path(tempfile.mkdtemp(prefix="rel01-drill-"))
os.environ["FLEET_ROOT"] = str(_TMP)
os.environ["FLEET_DATA_DIR"] = str(_TMP / "data")

import threading  # noqa: E402

from fleet.core import events  # noqa: E402
from fleet.rel.watchdog import Watchdog, WatchdogConfig  # noqa: E402

PORT = 5977
URL = f"http://127.0.0.1:{PORT}/api/health"


def probe() -> bool:
    try:
        with urllib.request.urlopen(URL, timeout=1) as resp:
            return resp.status == 200
    except OSError:
        return False


def main() -> None:
    print("=== REL-01 watchdog 实杀实拉演练 ===")
    print(f"目标：{URL}（tests.rel.drill_target 最小 HTTP 服务）")

    config = WatchdogConfig(
        port=PORT,
        interval=0.3,
        max_failures=2,
        restart_window=300.0,
        max_restarts=3,
        restart_cmd=[sys.executable, "-m", "tests.rel.drill_target", str(PORT)],
        spawner=lambda cmd: subprocess.Popen(cmd),
        probe=lambda _url: probe(),
        sleep=time.sleep,
        now=time.monotonic,
    )
    wd = Watchdog(config)
    threading.Thread(target=wd.run, daemon=True).start()

    deadline = time.time() + 15
    while time.time() < deadline and (wd.child is None or not probe()):
        time.sleep(0.1)
    assert wd.child is not None and probe(), "watchdog 未能拉起目标进程"
    first_pid = wd.child.pid
    print(f"[T0] 目标进程已由 watchdog 拉起：pid={first_pid}，探活 OK")

    wd.child.kill()
    wd.child.wait(timeout=10)
    print(f"[T1] 实杀完成：pid={first_pid} 已终止，探活 {'OK' if probe() else 'FAIL（符合预期）'}")

    deadline = time.time() + 20
    while time.time() < deadline:
        child = wd.child
        if child is not None and child.pid != first_pid and probe():
            break
        time.sleep(0.1)
    else:
        raise SystemExit("演练失败：watchdog 未能在时限内自动拉起新进程")
    new_pid = wd.child.pid
    print(f"[T2] watchdog 自动拉起新进程：pid={first_pid} -> {new_pid}，探活 OK")

    time.sleep(0.5)
    rows = [row for row in events.read() if row["action"] == "rel:restart"]
    assert len(rows) == 1, f"rel:restart 事件数量异常：{len(rows)}"
    extra = rows[0]["extra"]
    print(f"[T3] rel:restart 事件已落盘：restarts={extra['restarts']} old_pid={extra['old_pid']} new_pid={extra['new_pid']} port={extra['port']}")

    wd.stopped = True
    try:
        wd.child.terminate()
    except Exception:
        pass
    shutil.rmtree(_TMP, ignore_errors=True)
    print("=== 演练通过：kill -> 自动拉起 -> 事件留痕，全链真实 ===")


if __name__ == "__main__":
    main()
