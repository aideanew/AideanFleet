"""这是什么：AideanFleet 可靠性工程包（REL-01，Phase 3）。
怎么用：
    from fleet.rel import archive, recovery, retry_timer, watchdog, maintenance
职责边界：
    recovery    崩溃恢复（四态 ASSIGNED/DOING/SUBMITTED/REVIEWING 的续跑入口）
    retry_timer 卡死检测与升级（只管"还活着吗"，与 Machine Gate 正交）
    watchdog    控制台进程守护（独立进程，health 探活，防风暴）
    archive     events.jsonl 月度轮转 + evidence 归档 + seq 连续性校验
    maintenance server 进程内的轻维护挂载点（轮转 + 卡死扫描循环）
铁律：新代码全部在本包内；对既有模块只做 try import 探测式挂载（server.py/launch_core.py 各 ≤10 行）。
"""

from __future__ import annotations

from . import archive, recovery, retry_timer  # noqa: F401

__all__ = ["archive", "recovery", "retry_timer"]
