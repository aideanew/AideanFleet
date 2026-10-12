"""执行体子进程在 Windows 非 UTF-8 默认编码下仍须完整传递中文。"""

import subprocess
import sys

from fleet.executors.base import run_subprocess_tree_safe


def test_subprocess_utf8_roundtrip_with_gbk_default(monkeypatch, tmp_path):
    monkeypatch.setattr(subprocess, "_text_encoding", lambda: "gbk")
    prompt = "请制作动态表格，完成后回复：成功 ✨\n第二行提示词"
    result = run_subprocess_tree_safe(
        [sys.executable, "-c", "import sys; sys.stdout.buffer.write(sys.stdin.buffer.read())"],
        cwd=str(tmp_path),
        timeout=10,
        input_text=prompt,
    )
    assert result.returncode == 0
    assert result.stdout == prompt
    assert result.stderr == ""
