"""fleet.toml 配置层测试（F3/F4）：优先级 env > toml > 默认，来源标注，doctor 输出。"""

from __future__ import annotations

import pytest

from fleet.core import fleet_toml


@pytest.fixture()
def toml_file(tmp_path):
    path = tmp_path / "fleet.toml"
    path.write_text(
        '[workspace]\nallowed_roots = ["E:/Demo"]\n\n'
        "[models.agnes]\n"
        'base_url = "https://apihub.agnes-ai.com/v1"\n'
        'model_id = "agnes-3.0-flash"\n'
        'api_key_env = "AGNES_API_KEY"\n'
        "priority = 5\n\n"
        "[roles.fe-1]\n"
        'harness = ["codex", "opencode"]\n'
        'models = ["agnes"]\n\n'
        "[runtime]\n"
        'scheduler = "auto"\n'
        "lease_minutes = 20\n",
        encoding="utf-8",
    )
    return path


def test_load_toml_defaults(tmp_path):
    cfg = fleet_toml.load_config(tmp_path / "missing.toml" if False else None)
    # 无 toml：全默认
    assert cfg.allowed_roots == []
    assert cfg.scheduler == "auto"


def test_load_toml_parses_nested_structure(toml_file, monkeypatch):
    monkeypatch.delenv("FLEET_ALLOWED_ROOTS", raising=False)
    monkeypatch.delenv("FLEET_SCHEDULER", raising=False)
    cfg = fleet_toml.load_config(toml_file)
    assert cfg.allowed_roots == ["E:/Demo"]
    assert cfg.models["agnes"].model_id == "agnes-3.0-flash"
    assert cfg.roles["fe-1"].harness == ["codex", "opencode"]
    assert cfg.lease_minutes == 20
    assert cfg.sources["roles.fe-1"] == "toml"
    assert cfg.sources["allowed_roots"] == "toml"


def test_env_overrides_toml(toml_file, monkeypatch):
    monkeypatch.setenv("FLEET_ALLOWED_ROOTS", "D:/Work,X:/Y")
    monkeypatch.setenv("FLEET_SCHEDULER", "off")
    cfg = fleet_toml.load_config(toml_file)
    assert cfg.allowed_roots == ["D:/Work", "X:/Y"]
    assert cfg.sources["allowed_roots"] == "env"
    assert cfg.scheduler == "off"
    assert cfg.sources["scheduler"] == "env"


def test_explicit_missing_path_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        fleet_toml.load_config(tmp_path / "nope.toml")


def test_print_source_lists_effective_values(toml_file, monkeypatch):
    monkeypatch.delenv("FLEET_ALLOWED_ROOTS", raising=False)
    out = fleet_toml.print_config_source(fleet_toml.load_config(toml_file))
    assert "allowed_roots = ['E:/Demo']  [toml]" in out
    assert "agnes" in out and "fe-1" in out


def test_model_key_presence_check(toml_file, monkeypatch):
    monkeypatch.delenv("AGNES_API_KEY", raising=False)
    cfg = fleet_toml.load_config(toml_file)
    assert cfg.models["agnes"].key_present() is False
    monkeypatch.setenv("AGNES_API_KEY", "x")
    assert cfg.models["agnes"].key_present() is True


def test_save_roundtrip_and_secret_rejection(tmp_path, monkeypatch):
    """TASK-302：save → load_config 回读一致；含 sk- 值时拒绝。"""
    import pytest as _pytest
    from fleet.core import fleet_toml as ft
    from fleet.core.config import PlaintextSecretRejected

    target = tmp_path / "fleet.toml"
    cfg = ft.FleetConfig(path=None, allowed_roots=["E:/Demo"],
                         models={"agnes": ft.ModelCfg(name="agnes", base_url="https://x/v1",
                                                      model_id="agnes-1", api_key_env="AGNES_API_KEY",
                                                      priority=5)},
                         roles={"fe-1": ft.RoleCfg(name="fe-1", harness=["codex"], models=["agnes"])},
                         scheduler="auto", lease_minutes=20, sources={})
    written = ft.save(cfg, target)
    assert written == target
    reloaded = ft.load_config(target)
    assert reloaded.allowed_roots == ["E:/Demo"]
    assert reloaded.models["agnes"].model_id == "agnes-1"
    assert reloaded.roles["fe-1"].harness == ["codex"]
    assert reloaded.lease_minutes == 20

    bad = ft.FleetConfig(path=None, models={"x": ft.ModelCfg(name="x", base_url="https://x/v1",
                                                             model_id="sk-abc1234567890123456789xyz",  # nosec 测试夹具
                                                             api_key_env="X", priority=1)},
                         roles={}, scheduler="auto", lease_minutes=15, sources={})
    with _pytest.raises(PlaintextSecretRejected):
        ft.save(bad, tmp_path / "bad.toml")
