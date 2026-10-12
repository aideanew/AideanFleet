"""CLI 与验收门模块测试：doclint / project_gate / fleet next+writeback / doctor --config。"""

from __future__ import annotations

import json
import sys

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
    assert todo["status"] == st.RUNNING  # TASK-401：next 直接进 running（宿主随时可 writeback）
    assert todo["claimed_by"] == "claude"

    code = cli.main(["writeback", "--todo", tid, "--agent", "claude", "--verdict", "blocked", "--note", "缺依赖"])
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


def test_next_enters_running_state(isolated_root):
    """TASK-401/F-03：fleet next 后 todo 处于 running（此前停在 claimed，writeback done 必失败）。"""
    kernel = Kernel(isolated_root / "data" / "kernel.db")
    gid = kernel.create_goal("g")
    tid = kernel.create_todo(gid, title="t", role="fe-1", verify=["x"], workspace=str(isolated_root))

    cli.main(["next", "--agent", "claude", "--json"])
    todo = kernel.get_todo(tid)
    assert todo["status"] == st.RUNNING
    assert todo["claimed_by"] == "claude"


def test_writeback_done_runs_gate_and_succeeds(isolated_root, capsys):
    """TASK-401/F-04：writeback done 先跑机器门；verify 通过 → done。"""
    kernel = Kernel(isolated_root / "data" / "kernel.db")
    gid = kernel.create_goal("g")
    checker = isolated_root / "ok_checker.py"
    checker.write_text("import sys; sys.exit(0)\n", encoding="utf-8")
    tid = kernel.create_todo(gid, title="t", role="fe-1",
                             verify=[f'"{sys.executable}" "{str(checker).replace(chr(92), "/")}"'],
                             workspace=str(isolated_root))
    cli.main(["next", "--agent", "claude"])
    code = cli.main(["writeback", "--todo", tid, "--agent", "claude",
                     "--verdict", "done", "--note", "改完了"])
    assert code == 0
    out = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert out["status"] == st.DONE
    # 证据落盘：gate.json
    gate_file = isolated_root / "data" / "evidence" / tid / "gate.json"
    assert gate_file.is_file() and json.loads(gate_file.read_text(encoding="utf-8"))["ok"] is True


def test_writeback_done_gate_fail_becomes_successor(isolated_root, capsys):
    """TASK-401：verify 失败 → superseded + 新 successor open（packet 带失败摘要）。"""
    kernel = Kernel(isolated_root / "data" / "kernel.db")
    gid = kernel.create_goal("g")
    checker = isolated_root / "fail_checker.py"
    checker.write_text("import sys; print('boom'); sys.exit(2)\n", encoding="utf-8")
    tid = kernel.create_todo(gid, title="实现", role="fe-1",
                             verify=[f'"{sys.executable}" "{str(checker).replace(chr(92), "/")}"'],
                             workspace=str(isolated_root))
    cli.main(["next", "--agent", "claude"])
    code = cli.main(["writeback", "--todo", tid, "--agent", "claude", "--verdict", "done"])
    assert code == 0
    assert kernel.get_todo(tid)["status"] == st.SUPERSEDED
    rework = [t for t in kernel.todos() if t["status"] == st.OPEN]
    assert rework and rework[0]["lineage"] == tid
    assert "机器门未通过" in rework[0]["packet"]


def test_writeback_agent_mismatch_rejected(isolated_root):
    """B4：--agent 与 claimed_by 不一致 → 退出码非 0 且状态不变。"""
    kernel = Kernel(isolated_root / "data" / "kernel.db")
    gid = kernel.create_goal("g")
    tid = kernel.create_todo(gid, title="t", verify=["x"], workspace=str(isolated_root))
    kernel.claim(tid, worker="other-host")
    code = cli.main(["writeback", "--todo", tid, "--agent", "claude", "--verdict", "blocked"])
    assert code == 3
    assert kernel.get_todo(tid)["status"] == st.CLAIMED  # 状态不变
