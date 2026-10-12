"""这是什么：AideanFleet 端口唯一定义点（ADR-005，TASK-008）。
怎么用：from fleet.core.ports import DEFAULT_CONSOLE_PORT
约定（docs/架构.md §8）：AideanFleet 3100–3200；控制台默认 3100。
只依赖标准库。
"""

from __future__ import annotations

DEFAULT_CONSOLE_PORT = 3100
MANAGER_PORT = 9900
