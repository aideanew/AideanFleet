"""红线机制测试（pytest 形式：return → assert，消除 PytestReturnNotNoneWarning）"""

from pathlib import Path

from fleet.launcher.redlines import check_command, log_redline_event, get_deny_re_list


def test_redline_safe_commands():
    """安全命令必须放行（allowed=True）"""
    safe_commands = [
        "ls -la", "dir", "python --version", "git status",
        "npm install", "pip install pyyaml", "echo hello",
        "cat file.txt", "type file.txt",
    ]
    for cmd in safe_commands:
        result = check_command(cmd)
        assert result.allowed, f"误拦截安全命令：{cmd}（matched={result.matched_pattern}）"


def test_redline_dangerous_commands():
    """危险命令必须拦截（allowed=False）"""
    dangerous_commands = [
        "rm -rf /", "rm -rf *", "format C:", "del /s /q",
        "rmdir /s /q", "regedit", "reg delete HKLM\\Software",
        "drop database test", "truncate table users",
        "delete from users", "shutdown",
    ]
    for cmd in dangerous_commands:
        result = check_command(cmd)
        assert not result.allowed, f"未拦截危险命令：{cmd}"


def test_redline_logging(tmp_path, monkeypatch):
    """红线事件必须落审计日志（data/audit/redline.jsonl）"""
    monkeypatch.chdir(tmp_path)
    result = check_command("rm -rf /")
    assert not result.allowed
    log_redline_event("rm -rf /", result)
    log_file = Path("data/audit/redline.jsonl")
    assert log_file.exists(), "审计日志文件未生成"
    assert "rm -rf /" in log_file.read_text(encoding="utf-8"), "审计日志缺少危险命令记录"


def test_deny_re_list():
    """危险命令正则清单必须非空"""
    deny_list = get_deny_re_list()
    assert deny_list, "危险命令正则清单为空"
    assert len(deny_list.splitlines()) > 0
