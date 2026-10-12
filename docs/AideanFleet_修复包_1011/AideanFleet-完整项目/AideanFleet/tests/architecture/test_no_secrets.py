"""密钥扫描守门（TASK-002，REQ-NF-03）：已跟踪文本文件不得出现真实形态的密钥。

规则刻意只匹配"真密钥的形态"（长随机串/证书头），不匹配 ${VAR} 占位与
config.py 里密钥检测正则的定义文本本身。
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

SKIP_DIRS = {".git", "node_modules", "dist", "build", ".venv", "__pycache__",
             "data", ".pytest_cache", ".zcode", ".claude"}
BINARY_EXTS = {".png", ".jpg", ".ico", ".woff", ".woff2", ".exe", ".dll", ".zip",
               ".gz", ".whl", ".db", ".wfw", ".icns"}
MAX_FILE_BYTES = 2_000_000

PATTERNS: dict[str, re.Pattern[str]] = {
    "openai_style_key": re.compile(r"sk-[A-Za-z0-9]{20,}"),
    "aws_access_key": re.compile(r"AKIA[0-9A-Z]{16}"),
    "github_pat": re.compile(r"github_pat_[A-Za-z0-9_]{22,}"),
    "github_token": re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}"),
    "slack_token": re.compile(r"xox[bpars]-[A-Za-z0-9-]{10,}"),
    "private_key_block": re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
}


def _tracked_text_files():
    """只扫 git 已跟踪文件（REQ-NF-03 口径）；git 不可用时退回全目录扫描。"""
    try:
        result = subprocess.run(
            ["git", "-C", str(ROOT), "ls-files", "-z"], capture_output=True, timeout=60,
        )
        if result.returncode == 0 and result.stdout:
            names = result.stdout.decode("utf-8", "replace").split("\0")
            for name in names:
                if not name:
                    continue
                path = ROOT / name
                if path.suffix.lower() in BINARY_EXTS or path.name.endswith(".lock"):
                    continue
                try:
                    if path.stat().st_size > MAX_FILE_BYTES:
                        continue
                    yield path, path.read_text(encoding="utf-8")
                except (UnicodeDecodeError, OSError):
                    continue
            return
    except OSError:
        pass
    # 退路：文件系统遍历（跳过运行时目录）
    for path in ROOT.rglob("*"):
        if not path.is_file() or any(part in SKIP_DIRS for part in path.parts):
            continue
        if path.suffix.lower() in BINARY_EXTS:
            continue
        try:
            if path.stat().st_size > MAX_FILE_BYTES:
                continue
            yield path, path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue


def test_no_plaintext_secrets():
    offenders: list[str] = []
    for path, text in _tracked_text_files():
        for name, pattern in PATTERNS.items():
            for match in pattern.finditer(text):
                line_no = text.count("\n", 0, match.start()) + 1
                line = text.splitlines()[line_no - 1]
                if "# nosec" in line:
                    continue  # 显式豁免（测试夹具的假密钥形态，bandit 惯例）
                rel = path.relative_to(ROOT)
                offenders.append(f"{rel}:{line_no}: [{name}]（内容已隐去）")
    assert not offenders, "发现疑似明文密钥（规则 " + ", ".join(offenders[:10]) + " …）"
