"""P1.3：fleet.core.roots 单源单元测试（workspace 允许根唯一裁决层）。

统一回退链：FLEET_ALLOWED_ROOTS 环境变量 > fleet.toml > 旧 .env basic 段
> <data_dir>/workspaces 缺省（data_dir 必然可写，安装器部署不落安装目录）。
"""

from __future__ import annotations

import pytest

from fleet.core import roots


@pytest.fixture(autouse=True)
def _clean_roots_env(monkeypatch):
    """隔离宿主 shell 的 FLEET_ALLOWED_ROOTS，保证缺省回退断言确定性。"""
    monkeypatch.delenv("FLEET_ALLOWED_ROOTS", raising=False)


def _write_toml(fleet_env, text):
    (fleet_env["root"] / "fleet.toml").write_text(text, encoding="utf-8")


def test_env_overrides_toml(fleet_env, monkeypatch):
    _write_toml(fleet_env, '[workspace]\nallowed_roots = ["E:/Toml"]\n')
    monkeypatch.setenv("FLEET_ALLOWED_ROOTS", "D:/Env")
    assert roots.current() == ["D:/Env"]


def test_toml_before_default(fleet_env):
    _write_toml(fleet_env, '[workspace]\nallowed_roots = ["E:/Toml"]\n')
    assert roots.current() == ["E:/Toml"]
    assert roots.default_root() == str(fleet_env["data"] / "workspaces")


def test_default_never_empty(fleet_env):
    assert roots.current() == [str(fleet_env["data"] / "workspaces")]
