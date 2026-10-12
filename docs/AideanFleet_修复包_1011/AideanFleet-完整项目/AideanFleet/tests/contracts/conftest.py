"""tests/contracts 专用夹具：与 tests/core/conftest.py 同口径的隔离环境。"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from fleet.core import config as fleet_config  # noqa: E402
from fleet.core import db, events  # noqa: E402

MINIMAL_ENV_EXAMPLE = """\
# ===== [SECTION: basic] 基础信息 =====
FLEET_PROJECT_NAME=AideanFleet
FLEET_CONSOLE_PORT=3100
FLEET_LOCK_TTL_MINUTES=60
"""


@pytest.fixture()
def fleet_env(tmp_path, monkeypatch):
    root = tmp_path / "fleet-root"
    data = root / "data"
    root.mkdir(parents=True)
    (root / ".env.example").write_text(MINIMAL_ENV_EXAMPLE, encoding="utf-8")
    monkeypatch.setenv("FLEET_ROOT", str(root))
    monkeypatch.setenv("FLEET_DATA_DIR", str(data))
    monkeypatch.setenv("FLEET_CONFIG_WRITE", "1")
    events._CACHE["size"] = -1
    events._CACHE["seq"] = 0
    fleet_config._CACHE.mtime_ns = None
    fleet_config._CACHE.values = {}
    fleet_config._CACHE.section_of = {}
    db.init_db()
    yield {"root": root, "data": data}
    events._CACHE["size"] = -1
    fleet_config._CACHE.mtime_ns = None
    fleet_config._CACHE.values = {}
    fleet_config._CACHE.section_of = {}


@pytest.fixture()
def project(fleet_env):
    db.create_project("P-001", "演示项目", "E:/Code/DemoProject")
    return "P-001"
