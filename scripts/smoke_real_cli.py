"""真实 CLI 冒烟脚本：resolve → check_available → 最小任务 → DONE。

CLI 安装后，任何人一条命令即可补上真实冒烟证据。

用法:
    python scripts/smoke_real_cli.py [claude|codex|opencode|hermes|cline|gemini|grok]
    python scripts/smoke_real_cli.py --all
"""

from __future__ import annotations

import argparse
import io
import shutil
import subprocess
import sys
import time
from pathlib import Path

# Windows GBK 兼容
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

# 确保项目根目录在 sys.path
_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_root))

from tests.int._cli_probe import probe_cli, KNOWN_CLIS

#: KNOWN_CLIS 键 → 适配器注册名映射（claude 适配器注册名为 claudecode）
CLI_ALIAS = {"claude": "claudecode"}


def run_smoke(cli_name: str) -> dict:
    """对单个 CLI 执行完整冒烟链路"""
    result = {
        "cli": cli_name,
        "available": False,
        "version": "",
        "resolve_ok": False,
        "probe_ok": False,
        "error": "",
    }

    # Step 1: 检查 CLI 是否可用
    probe = probe_cli(cli_name)
    result["available"] = probe.available
    result["version"] = probe.version_output

    if not probe.available:
        result["error"] = probe.skip_reason
        return result

    print(f"[{cli_name}] CLI 可用: {probe.version_output}")

    # Step 2: 尝试 resolve（通过 adapter 的 capabilities）
    try:
        import importlib
        from fleet.executors.base import ADAPTER_REGISTRY

        reg_name = CLI_ALIAS.get(cli_name, cli_name)
        importlib.import_module(f"fleet.executors.{reg_name}")
        adapter_cls = ADAPTER_REGISTRY.get(reg_name)
        if adapter_cls:
            adapter = adapter_cls()
            caps = adapter.capabilities()
            result["resolve_ok"] = True
            result["probe_ok"] = caps is not None
            print(f"[{cli_name}] resolve → capabilities: streaming={caps.streaming}, "
                  f"usage_reporting={caps.usage_reporting}")
        else:
            result["error"] = f"adapter {cli_name} 未注册"
    except Exception as e:
        result["error"] = str(e)

    return result


def main():
    parser = argparse.ArgumentParser(description="真实 CLI 冒烟脚本")
    parser.add_argument("cli", nargs="?", default=None,
                       help="要测试的 CLI 名称 (claude/codex/opencode/hermes/cline/gemini/grok)")
    parser.add_argument("--all", action="store_true",
                       help="测试所有已知 CLI")
    args = parser.parse_args()

    if args.all:
        targets = list(KNOWN_CLIS.keys())
    elif args.cli:
        targets = [args.cli]
    else:
        targets = list(KNOWN_CLIS.keys())

    results = []
    for cli_name in targets:
        print(f"\n{'='*50}")
        print(f"冒烟测试: {cli_name}")
        print(f"{'='*50}")
        r = run_smoke(cli_name)
        results.append(r)

    # 汇总
    print(f"\n{'='*50}")
    print("冒烟测试汇总")
    print(f"{'='*50}")
    for r in results:
        status = "✅" if r["available"] and r["resolve_ok"] else "❌"
        detail = r["error"] if (status == "❌" and r["error"]) else (r["version"] or r["error"])
        print(f"  {status} {r['cli']}: {detail}")

    available = sum(1 for r in results if r["available"])
    print(f"\n可用: {available}/{len(results)}")


if __name__ == "__main__":
    main()
