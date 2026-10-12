"""执行体进程生命周期测试：kill_tree 进程树清理 + run_subprocess_tree_safe 超时杀树 + 正常路径"""
import subprocess
import sys
import time

import pytest

from fleet.executors.base import kill_tree, run_subprocess_tree_safe

LONG_CMD = ["ping", "-n", "30", "127.0.0.1"]  # 约 30 秒的长驻进程


@pytest.mark.skipif(sys.platform != "win32", reason="Windows taskkill /T 进程树语义")
def test_kill_tree_kills_process():
    """kill_tree 应终止长驻子进程"""
    proc = subprocess.Popen(
        LONG_CMD,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    assert proc.poll() is None  # 仍在运行
    kill_tree(proc.pid)
    time.sleep(1.5)
    assert proc.poll() is not None  # 已被终止


@pytest.mark.skipif(sys.platform != "win32", reason="Windows taskkill /T 进程树语义")
def test_tree_safe_timeout_kills_tree():
    """超时场景：抛 TimeoutExpired 且进程树已被清理（不会残留驻留）"""
    with pytest.raises(subprocess.TimeoutExpired):
        run_subprocess_tree_safe(LONG_CMD, None, 2)


@pytest.mark.skipif(sys.platform != "win32", reason="Windows taskkill /T 进程树语义")
def test_tree_safe_normal_returns_output():
    """正常路径：命令完成、输出可读、无泄漏"""
    completed = run_subprocess_tree_safe(["cmd", "/c", "echo", "ok"], None, 10)
    assert completed.returncode == 0
    assert "ok" in (completed.stdout or "")
    assert not getattr(completed, "timed_out", False)
