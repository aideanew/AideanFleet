"""CLI 与验收门模块测试：doclint / project_gate / fleet next+writeback / doctor --config。"""

from __future__ import annotations

import json

import pytest

from fleet.cli import main as cli
from fleet.gates import doclint, project_gate
from fleet.kernel import Kernel
from fleet.kernel import state as st


@pytest.fixture()
def isolated_root(tmp_path, monkeypatch):
    monkeypatch.setenv("FLEET_ROOT", str(tmp_path))
    monkeypatch.setenv("FLEET_DATA_DIR", str(tmp_path / "data"))
    return tmp_path


# ---------------------------------------------------------------------------
# doclint：设计文档实质校验（A5）
# ---------------------------------------------------------------------------

def _write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def test_doclint_passes_substantive_doc(tmp_path):
    doc = _write(tmp_path / "docs" / "design.md",
                 "# 架构设计\n\n## 技术选型\n采用 Vue3 + FastAPI，理由如下。\n" + "细节" * 150 +
                 "\n\n## 目录结构\nsrc/ 下分层。\n\n## 数据流\n前端经 API 网关到服务层。\n")
    assert doclint.main([str(doc)]) == 0


def test_doclint_rejects_shell_doc(tmp_path):
    doc = _write(tmp_path / "docs" / "design.md", "# Design\nTODO\n")
    assert doclint.main([str(doc)]) == 1


def test_doclint_missing_file(tmp_path):
    assert doclint.main([str(tmp_path / "nope.md")]) == 1


# ---------------------------------------------------------------------------
# project_gate：真实构建/编译/入口校验（A5）
# ---------------------------------------------------------------------------

def test_project_gate_python_compiles(tmp_path, monkeypatch):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text("print('ok')\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    assert project_gate.main([]) == 0


def test_project_gate_rejects_syntax_error(tmp_path, monkeypatch):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text("def broken(:\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    assert project_gate.main([]) == 1


def test_project_gate_rejects_empty_shell(tmp_path, monkeypatch):
    (tmp_path / "index.html").write_text("   \n  ", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    assert project_gate.main([]) == 1  # 空文件壳：无构建脚本、无 Python 源、HTML 空内容


def test_project_gate_no_deliverable(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert project_gate.main([]) == 1


# ---------------------------------------------------------------------------
# fleet next / writeback（P4 宿主内驱动）
# ---------------------------------------------------------------------------

def test_next_and_writeback_roundtrip(isolated_root):
    kernel = Kernel(isolated_root / "data" / "kernel.db")
    gid = kernel.create_goal("g")
    tid = kernel.create_todo(gid, title="t", role="fe-1", verify=["x"])

    code = cli.main(["next", "--agent", "claude", "--json"])
    assert code == 0
    todo = kernel.get_todo(tid)
    assert todo["status"] == st.CLAIMED
    assert todo["claimed_by"] == "claude"

    code = cli.main(["writeback", "--todo", tid, "--verdict", "blocked", "--note", "缺依赖"])
    assert code == 0
    assert kernel.get_todo(tid)["status"] == st.BLOCKED


def test_next_returns_no_runnable_when_empty(isolated_root, capsys):
    assert cli.main(["next", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["todo"] is None


# ---------------------------------------------------------------------------
# doctor --config
# ---------------------------------------------------------------------------

def test_doctor_config_prints_effective(isolated_root, capsys, monkeypatch):
    (isolated_root / "fleet.toml").write_text(
        '[workspace]\nallowed_roots = ["E:/Demo"]\n', encoding="utf-8")
    monkeypatch.delenv("FLEET_ALLOWED_ROOTS", raising=False)
    assert cli.main(["doctor", "--config"]) == 0
    out = capsys.readouterr().out
    assert "allowed_roots = ['E:/Demo']  [toml]" in out
