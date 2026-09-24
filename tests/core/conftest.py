"""这是什么：tests/core 专用夹具。每个测试拿到完全隔离的 FLEET_ROOT / FLEET_DATA_DIR。
要点：paths() 每次调用时读环境变量，所以 monkeypatch.setenv 即可整体切换；
     events/config 模块有按文件大小/mtime 的缓存，必须逐项重置；dag 的防刷屏去重同理。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from fleet.core import config as fleet_config  # noqa: E402
from fleet.core import db, events  # noqa: E402
from fleet.manager import dag as dag_engine  # noqa: E402

#: 最小 .env.example（config.ensure_env_file 需要；隔离环境里内容自足，不依赖真实模板）
MINIMAL_ENV_EXAMPLE = """\
# ===== [SECTION: basic] 基础信息 =====
FLEET_PROJECT_NAME=AideanFleet
FLEET_CONSOLE_PORT=5000
FLEET_LOCK_TTL_MINUTES=60

# ===== [SECTION: model_pool] 模型池 =====
FLEET_MODEL_1_NAME=m1
FLEET_MODEL_1_LEVEL=1
FLEET_MODEL_1_BASE_URL=https://m1.example/v1
FLEET_MODEL_1_MODEL_ID=demo-1
FLEET_MODEL_1_API_KEY=${M1_KEY}

FLEET_MODEL_2_NAME=m2
FLEET_MODEL_2_LEVEL=2
FLEET_MODEL_2_BASE_URL=https://m2.example/v1
FLEET_MODEL_2_MODEL_ID=demo-2
FLEET_MODEL_2_API_KEY=${M2_KEY}

# ===== [SECTION: roles] 角色 =====
FLEET_ROLE_1_NAME=worker-a
FLEET_ROLE_1_BIND_MODEL_NAME=m1,m2
FLEET_ROLE_1_ADAPTER=stub

FLEET_ROLE_2_NAME=reviewer-1
FLEET_ROLE_2_BIND_MODEL_NAME=m2
FLEET_ROLE_2_ADAPTER=stub

# ===== [SECTION: executors] 执行体 =====
FLEET_EXECUTOR_1_NAME=stub
FLEET_EXECUTOR_1_COMMAND=stub
FLEET_EXECUTOR_1_TIMEOUT=60

# ===== [SECTION: email] 邮件 =====
FLEET_SMTP_ENABLED=0

# ===== [SECTION: notify] 通知 =====
FLEET_NOTIFY_ON_TASK_END=1

# ===== [SECTION: request] 请求 =====
FLEET_REQUEST_TIMEOUT=60
FLEET_REQUEST_RETRY_MAX=10
FLEET_REQUEST_RETRY_DELAY=0
"""


def _reset_module_caches() -> None:
    events._CACHE["size"] = -1
    events._CACHE["seq"] = 0
    fleet_config._CACHE.mtime_ns = None
    fleet_config._CACHE.values = {}
    fleet_config._CACHE.section_of = {}
    dag_engine.reset_defer_dedup()


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
    """预置一个项目 P-001 并返回其 id。"""
    db.create_project("P-001", "演示项目", "E:/Code/DemoProject")
    return "P-001"


def read_events(project_id: str | None = None) -> list[dict]:
    """测试断言用的快捷读取。"""
    return list(events.read(project=project_id))


def write_json(target: Path, payload: dict) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
