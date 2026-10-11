"""TASK-201：manifest 结构守门——每个条目含版本/URL/64 位十六进制 SHA256（zip 类必填）。"""

from __future__ import annotations

import re
from pathlib import Path

from fleet.setup import load_manifest, manifest_path

SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def test_manifest_loads():
    assert manifest_path().is_file()
    manifest = load_manifest()
    assert manifest.get("version") == 1
    assert manifest.get("components")


def test_manifest_entry_fields():
    manifest = load_manifest()
    names = set()
    for entry in manifest["components"]:
        assert entry.get("name"), entry
        assert entry.get("kind") in ("runtime", "cli"), entry
        assert isinstance(entry.get("detect"), list) and entry["detect"], entry
        assert "install" in entry, entry
        assert "urls" in entry, entry
        names.add(entry["name"])
        if entry["install"].get("type") == "bundled_zip":
            sha = entry.get("sha256") or ""
            assert SHA256_RE.match(sha), f"{entry['name']} 的 sha256 必须是 64 位十六进制: {sha!r}"
            assert entry["install"].get("artifact"), entry
    # 关键组件齐全（REQ-F-01：python/node + 核心执行体）
    for required in ("python", "node", "npm", "claude", "codex", "opencode"):
        assert required in names, f"manifest 缺组件 {required}"


def test_fetch_runtimes_check_passes():
    """构建期校验：_runtimes 产物存在且 sha256 与 manifest 一致（CI 构建先跑 fetch）。"""
    import subprocess
    import sys

    script = Path(__file__).resolve().parents[2] / "scripts" / "installer" / "windows" / "fetch_runtimes.py"
    out_dir = script.parent / "_runtimes"
    if not out_dir.exists() or not any(out_dir.glob("*.zip")):
        pytest.skip("运行时产物未下载（本地开发可跑 fetch_runtimes.py 生成）")
    result = subprocess.run(
        [sys.executable, str(script), "--check"], capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stdout + result.stderr
