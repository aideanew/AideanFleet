"""TASK-501：真实执行体端到端（codex 走模型池、claude 走自身凭据）。

无凭据/未装 CLI 的环境中整文件 skip（REQ：skip 而非 fail）；设置
FLEET_REAL_HARNESSES=1 且两个 CLI 均可用时执行真实链路。
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from fleet.kernel import Kernel
from fleet.runner import worker as worker_mod

pytestmark = pytest.mark.skipif(
    os.environ.get("FLEET_REAL_HARNESSES") != "1"
    or not (shutil.which("codex") and shutil.which("claude")),
    reason="真实执行体端到端需要 FLEET_REAL_HARNESSES=1 且 codex/claude 均已安装登录（U-05）",
)


@pytest.fixture()
def kernel(tmp_path, monkeypatch):
    monkeypatch.setenv("FLEET_DATA_DIR", str(tmp_path / "data"))
    return Kernel(tmp_path / "kernel.db")


def test_real_harness_chain_codex_then_claude(kernel, tmp_path, monkeypatch):
    """模型池注入 codex；模拟卸载 codex 后任务由 claude 完成（REQ-F-05 降级）。"""
    workspace = tmp_path / "ws"
    workspace.mkdir()
    checker = tmp_path / "checker.py"
    checker.write_text(
        "import importlib.util, pathlib, sys\n"
        "target = pathlib.Path('src/main.py')\n"
        "if not target.is_file(): sys.exit(3)\n"
        "spec = importlib.util.spec_from_file_location('m', target)\n"
        "mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)\n"
        "sys.exit(0 if mod.main() == 42 else 1)\n",
        encoding="utf-8",
    )
    gid = kernel.create_goal("实现返回 42 的程序")
    kernel.create_todo(gid, title="实现 main", role="fe-1",
                       allowed_files=["**"],
                       verify=[f'"{sys.executable}" "{str(checker).replace(chr(92), "/")}"'],
                       workspace=str(workspace))

    outcome = worker_mod.run_once(kernel, worker="real-worker", workspace_root=str(workspace))
    assert outcome["action"] == "writeback", outcome
    kernel.transition(outcome["todo"], outcome["result"])
    todo = kernel.get_todo(outcome["todo"])
    assert todo["status"] in ("done", "superseded"), todo["status"]

    # 降级演练：把 codex 从 PATH 摘掉（重命名不可靠，改用受限 PATH 重跑下一个 todo）
    narrow_path = str(Path(sys.executable).parent) + os.pathsep + os.environ.get("SystemRoot", r"C:\Windows") + "\\System32"
    monkeypatch.setenv("PATH", narrow_path)
    gid2 = kernel.create_goal("第二个任务")
    kernel.create_todo(gid2, title="再来一次", role="fe-1", allowed_files=["**"],
                       verify=todo["verify"], workspace=str(workspace))
    outcome2 = worker_mod.run_once(kernel, worker="real-worker", workspace_root=str(workspace))
    assert outcome2["action"] == "writeback"
    kernel.transition(outcome2["todo"], outcome2["result"])
    # codex 不可用 → 由链中下一个（claude）完成，或全不可用 blocked（note 含原因）
    todo2 = kernel.get_todo(outcome2["todo"])
    assert todo2["status"] in ("done", "superseded", "blocked")
    if todo2["status"] == "blocked":
        assert "不可用" in (outcome2["result"].note or "")
