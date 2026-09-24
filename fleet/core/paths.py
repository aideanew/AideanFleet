"""这是什么：全项目统一的路径解析（根目录 / 数据目录 / db / 事件流 / plan / 证据目录）。
怎么用：from fleet.core.paths import paths;  p = paths();  p.db_file / p.plan_file("P-001")
覆盖方式：环境变量 FLEET_ROOT 覆盖仓库根；FLEET_DATA_DIR 覆盖数据目录；FLEET_ENV_FILE 覆盖 .env 路径。
本模块不读 .env、不写盘，只做纯路径计算，供 config/db/events/plan/gates 共用。
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

# fleet/core/paths.py -> parents[0]=core, [1]=fleet, [2]=仓库根
_DEFAULT_ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class FleetPaths:
    """一套不可变的路径集合。所有模块都通过它取路径，避免各自拼字符串。"""

    root: Path
    data_dir: Path

    # ---- 配置文件 ----
    @property
    def env_example_file(self) -> Path:
        """模板文件：运行期永远不会被写入。"""
        return self.root / ".env.example"

    @property
    def env_file(self) -> Path:
        """真实配置：首次运行由 .env.example 原样复制而来。"""
        return self.root / ".env"

    # ---- 状态与事件（初始设计/d7.md：SQLite 存状态、JSONL 存事件、目录存证据） ----
    @property
    def db_file(self) -> Path:
        return self.data_dir / "fleet.db"

    @property
    def events_file(self) -> Path:
        return self.data_dir / "events.jsonl"

    @property
    def projects_dir(self) -> Path:
        return self.data_dir / "projects"

    def memory_dir(self) -> Path:
        """Project Memory 目录（CORE-04 契约 v1.2 §13.3：data/memory/）。"""
        return self.data_dir / "memory"

    def memory_file(self, project_id: str) -> Path:
        """某项目的记忆存储文件（data/memory/<project_id>.json，原子写）。"""
        return self.memory_dir() / f"{project_id}.json"

    @property
    def reports_dir(self) -> Path:
        return self.root / "reports"

    # ---- 按项目 / 任务切分 ----
    def project_dir(self, project_id: str) -> Path:
        return self.projects_dir / project_id

    def plan_file(self, project_id: str) -> Path:
        return self.project_dir(project_id) / "plan.json"

    def evidence_dir(self, project_id: str, task_id: str) -> Path:
        return self.project_dir(project_id) / "evidence" / task_id

    def ensure_dir(self, target: Path) -> Path:
        target.mkdir(parents=True, exist_ok=True)
        return target


def paths(root: str | os.PathLike[str] | None = None, data_dir: str | os.PathLike[str] | None = None) -> FleetPaths:
    """计算路径集合。

    环境变量优先，其次传入参数，最后是仓库默认位置。
    这样单测可以用临时目录（tmp_path）完全隔离，不污染真实 data/。
    """
    env_root = os.environ.get("FLEET_ROOT")
    if env_root:
        root_path = Path(env_root).expanduser()
    elif root is not None:
        root_path = Path(root).expanduser()
    else:
        root_path = _DEFAULT_ROOT

    env_data = os.environ.get("FLEET_DATA_DIR")
    if env_data:
        data_path = Path(env_data).expanduser()
    elif data_dir is not None:
        data_path = Path(data_dir).expanduser()
    else:
        data_path = root_path / "data"

    return FleetPaths(root=root_path.resolve(), data_dir=data_path.resolve())
