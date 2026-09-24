"""这是什么：tests/rel 专用夹具。与 tests/core/conftest 同构：隔离 FLEET_ROOT，重置模块缓存。"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# 子进程演练目标（tests.rel.drill_target）需要能 import，故把仓库根挂进 PYTHONPATH 继承给子进程
env_path = os.environ.get("PYTHONPATH", "")
if str(REPO_ROOT) not in env_path.split(os.pathsep):
    os.environ["PYTHONPATH"] = str(REPO_ROOT) + (os.pathsep + env_path if env_path else "")

from fleet.core import config as fleet_config  # noqa: E402
from fleet.core import db, events  # noqa: E402
from fleet.manager import dag as dag_engine  # noqa: E402
from fleet.rel import maintenance  # noqa: E402

from tests.core.conftest import MINIMAL_ENV_EXAMPLE  # noqa: E402


def _reset_module_caches() -> None:
    events._CACHE["size"] = -1
    events._CACHE["seq"] = 0
    fleet_config._CACHE.mtime_ns = None
    fleet_config._CACHE.values = {}
    fleet_config._CACHE.section_of = {}
    dag_engine.reset_defer_dedup()
    maintenance.reset_for_tests()


@pytest.fixture()
def fleet_env(tmp_path, monkeypatch):
    """隔离环境：FLEET_ROOT 指向 tmp_path，预置 .env.example 并初始化 SQLite。"""
    root = tmp_path / "fleet-root"
    data = root / "data"
    root.mkdir(parents=True)
    (root / ".env.example").write_text(MINIMAL_ENV_EXAMPLE, encoding="utf-8")
    monkeypatch.setenv("FLEET_ROOT", str(root))
    monkeypatch.setenv("FLEET_DATA_DIR", str(data))
    monkeypatch.setenv("FLEET_CONFIG_WRITE", "1")
    _reset_module_caches()
    db.init_db()
    yield {"root": root, "data": data}
    _reset_module_caches()


@pytest.fixture()
def project(fleet_env):
    db.create_project("P-001", "演示项目", "E:/Code/DemoProject")
    return "P-001"


def read_events(project_id: str | None = None) -> list[dict]:
    return list(events.read(project=project_id))


def simulate_restart() -> None:
    """模拟进程重启：进程内缓存全部失效，只有 SQLite/文件里的状态还在。"""
    _reset_module_caches()
