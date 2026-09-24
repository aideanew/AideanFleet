"""这是什么：控制台进程守护（REL-01 §9.2）。独立进程运行，health 端点探活，崩溃自动拉起。
怎么用：
    python -m fleet.rel.watchdog --port 5000            # 前台常驻（由 launch_core 以子进程拉起）
语义：
  · 每 interval 秒探活 GET http://host:port/api/health（HTTP 200 即活）；连续 max_failures 次失败判死。
  · 判死后以相同参数重启（restart_cmd），写事件 rel:restart（含重启计数/新旧 pid）。
  · 防风暴：restart_window 秒内重启超过 max_restarts 次即停止拉起，写 rel:escalate 等人工。
开启方式：FLEET_WATCHDOG=1 时由 launch_core 第⑨步随服务拉起（缺省关闭，遵循 FLEET_SCHEDULER 模式）。
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
import urllib.error
import urllib.request
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Callable

from fleet.core import events

#: 默认参数（工作包 §9.2：间隔 10s，连续 3 次失败判死；防风暴窗口 5 分钟 3 次）
DEFAULT_INTERVAL = 10.0
DEFAULT_MAX_FAILURES = 3
DEFAULT_RESTART_WINDOW = 300.0
DEFAULT_MAX_RESTARTS = 3


@dataclass
class WatchdogConfig:
    """守护参数；probe/spawner/sleep/now 可注入以便离线测试。"""

    port: int = 5000
    host: str = "127.0.0.1"
    interval: float = DEFAULT_INTERVAL
    max_failures: int = DEFAULT_MAX_FAILURES
    restart_window: float = DEFAULT_RESTART_WINDOW
    max_restarts: int = DEFAULT_MAX_RESTARTS
    #: 判死后拉起的命令；为空则只探活不拉起（纯监控模式）
    restart_cmd: list[str] | None = None
    probe: Callable[[str], bool] | None = None
    spawner: Callable[[list[str]], Any] | None = None
    sleep: Callable[[float], None] | None = None
    now: Callable[[], float] | None = None


def _default_probe(url: str) -> bool:
    """HTTP 200 即存活（/api/health 免会话鉴权，契约 §4）。"""
    try:
        with urllib.request.urlopen(url, timeout=5) as resp:
            return resp.status == 200
    except (urllib.error.URLError, OSError, ValueError):
        return False


class Watchdog:
    """守护器本体。run() 常驻循环；所有注入点都有真实默认。"""

    def __init__(self, config: WatchdogConfig) -> None:
        self.config = config
        self.child: Any = None
        self.restarts = 0
        self.consecutive_failures = 0
        self.escalated = False
        self.stopped = False
        self._restart_times: deque[float] = deque()
        self._sleep = config.sleep or time.sleep
        self._now = config.now or time.monotonic

    # ---- 探活 ---------------------------------------------------------------

    @property
    def health_url(self) -> str:
        return f"http://{self.config.host}:{self.config.port}/api/health"

    def probe_once(self) -> bool:
        if self.config.probe is not None:
            return bool(self.config.probe(self.health_url))
        return _default_probe(self.health_url)

    # ---- 拉起 ---------------------------------------------------------------

    def spawn_child(self) -> Any:
        if not self.config.restart_cmd:
            return None
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        spawner = self.config.spawner or (lambda cmd: subprocess.Popen(cmd, creationflags=flags))
        self.child = spawner(list(self.config.restart_cmd))
        return self.child

    def restart(self) -> Any:
        old_pid = getattr(self.child, "pid", None)
        child = self.spawn_child()
        self.restarts += 1
        self._restart_times.append(self._now())
        events.append(
            actor="rel",
            action="rel:restart",
            summary=f"watchdog 重启控制台（第 {self.restarts} 次，端口 {self.config.port}）",
            url=f"http://{self.config.host}:{self.config.port}",
            extra={
                "restarts": self.restarts,
                "old_pid": old_pid,
                "new_pid": getattr(child, "pid", None),
                "port": self.config.port,
            },
        )
        return child

    # ---- 防风暴 -------------------------------------------------------------

    def _storm(self) -> bool:
        window_start = self._now() - self.config.restart_window
        recent = [t for t in self._restart_times if t >= window_start]
        return len(recent) >= self.config.max_restarts

    # ---- 主循环 -------------------------------------------------------------

    def run(self, *, max_cycles: int | None = None) -> dict[str, Any]:
        """常驻循环。max_cycles 供测试/演练限次退出；返回过程摘要。"""
        if self.child is None:
            self.spawn_child()
        cycles = 0
        failures = 0
        while max_cycles is None or cycles < max_cycles:
            if self.stopped:  # 外部停止信号（测试/运维手动收线）
                break
            cycles += 1
            if self.probe_once():
                failures = 0
                self.consecutive_failures = 0
            else:
                failures += 1
                self.consecutive_failures = failures
                if failures >= self.config.max_failures:
                    if self._storm():
                        events.append(
                            actor="rel",
                            action="rel:escalate",
                            summary=(
                                f"watchdog 防风暴触发：{self.config.restart_window:.0f}s 内已重启 "
                                f"{len(self._restart_times)} 次，停止拉起等人工"
                            ),
                            extra={
                                "restarts": self.restarts,
                                "window_seconds": self.config.restart_window,
                                "max_restarts": self.config.max_restarts,
                                "port": self.config.port,
                            },
                        )
                        self.escalated = True
                        self.stopped = True
                        break
                    self.restart()
                    failures = 0
            if max_cycles is not None and cycles >= max_cycles:
                break
            self._sleep(self.config.interval)
        self.stopped = True
        return {
            "cycles": cycles,
            "restarts": self.restarts,
            "escalated": self.escalated,
            "consecutive_failures": self.consecutive_failures,
        }


def spawn_for_console(port: int, host: str = "127.0.0.1") -> subprocess.Popen:
    """launch_core 挂载点：以独立进程拉起 watchdog 守护控制台。"""
    cmd = [sys.executable, "-m", "fleet.rel.watchdog", "--port", str(port), "--host", host]
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    return subprocess.Popen(cmd, creationflags=flags)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="AideanFleet 控制台 watchdog（REL-01）")
    parser.add_argument("--port", type=int, default=5000)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--interval", type=float, default=DEFAULT_INTERVAL)
    parser.add_argument("--max-failures", type=int, default=DEFAULT_MAX_FAILURES)
    args = parser.parse_args(argv)

    restart_cmd = [sys.executable, "-m", "fleet.console.server"]
    config = WatchdogConfig(
        port=args.port,
        host=args.host,
        interval=args.interval,
        max_failures=args.max_failures,
        restart_cmd=restart_cmd,
    )
    print(
        f"watchdog 已启动：监视 http://{args.host}:{args.port}/api/health"
        f"（interval={args.interval}s, max_failures={args.max_failures}，重启命令 {restart_cmd}）"
    )
    summary = Watchdog(config).run()
    print("watchdog 退出：" + json.dumps(summary, ensure_ascii=False))
    return 0 if not summary["escalated"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
