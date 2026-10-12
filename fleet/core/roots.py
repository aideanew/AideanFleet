"""这是什么：workspace 允许根唯一裁决层（P1.3 单源收敛）。
怎么用：
    from fleet.core import roots
    roots.current()       # 当前生效的允许根列表（永不返回空）
    roots.default_root()  # 缺省根：<data_dir>/workspaces（保证可写）
要点：
- 历史三处消费方回退链互不一致：
    config_api:  body → toml → 422（新装机器保存模型必失败）；
    kernel_api:  toml → intake._allowed_roots（.env basic → env → 仓库根）；
    intake:      .env basic → env → 仓库根（F2 曾回退仓库根，安装器部署写保护）。
- 统一为一条：FLEET_ALLOWED_ROOTS 环境变量 > fleet.toml [workspace].allowed_roots
  > 旧 .env basic.allowed_roots（旧链兼容）> <data_dir>/workspaces 缺省。
- 缺省放 data_dir 下而非仓库根：data_dir 必然可写（kernel.db 所在），
  安装器部署（FLEET_DATA_DIR 指向用户目录）不会把用户工作区写进安装目录。
"""

from __future__ import annotations

import os
from pathlib import Path


def current() -> list[str]:
    """当前生效的 workspace 允许根（env > toml > 旧 .env basic > data_dir/workspaces）。"""
    roots = _toml_roots()          # 含 FLEET_ALLOWED_ROOTS 环境变量覆盖（fleet_toml 内置）
    if not roots:
        roots = _legacy_env_roots()  # 旧链兼容：.env basic 段
    if not roots:
        roots = [default_root()]
    return roots


def default_root() -> str:
    """缺省允许根：数据目录下 workspaces（data_dir 必然可写）。"""
    from .paths import paths

    return str(Path(paths().data_dir) / "workspaces")


def _toml_roots() -> list[str]:
    """新链路：fleet.toml（含 FLEET_ALLOWED_ROOTS 环境变量覆盖，优先级 env > toml）。"""
    from . import fleet_toml

    try:
        cfg = fleet_toml.load_config()
        return [str(r).strip() for r in cfg.allowed_roots if str(r).strip()]
    except Exception:
        return []


def _legacy_env_roots() -> list[str]:
    """旧链兼容：.env basic 段 allowed_roots，回退 FLEET_ALLOWED_ROOTS 环境变量。"""
    from . import config as fleet_config

    try:
        cfg = fleet_config.load("basic") or {}
        raw = cfg.get("allowed_roots", "")
    except Exception:
        raw = ""
    roots: list[str] = []
    if isinstance(raw, list):
        roots = [str(r).strip() for r in raw if str(r).strip()]
    elif isinstance(raw, str) and raw.strip():
        roots = [r.strip() for r in raw.split(",") if r.strip()]
    if not roots:
        env_roots = os.environ.get("FLEET_ALLOWED_ROOTS", "")
        roots = [r.strip() for r in env_roots.split(",") if r.strip()]
    return roots
