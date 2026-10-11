"""fleet.setup CLI 入口（TASK-202）：status / install。"""

from __future__ import annotations

import argparse
import json
import sys
import time


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m fleet.setup", description="AideanFleet 组件安装与状态")
    sub = parser.add_subparsers(dest="command")

    p_status = sub.add_parser("status", help="汇总 SetupStatus（组件/模型/执行体登录态）")
    p_status.add_argument("--json", action="store_true", help="JSON 输出")

    p_install = sub.add_parser("install", help="安装组件（默认安装全部 default 组件）")
    p_install.add_argument("components", nargs="*", help="组件名（缺省=default 集合）")
    p_install.add_argument("--mirror", choices=["auto", "official", "cn"], default="auto")
    p_install.add_argument("--wait", action="store_true", help="前台等待作业结束并打印进度")

    args = parser.parse_args(argv)
    from fleet.setup import core

    if args.command == "status":
        payload = core.status()
        if args.json:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            print(f"platform={payload['platform']} ready={payload['ready']}")
            for component in payload["components"]:
                marker = "✓" if component["state"] == "installed" else ("⚠" if component["state"] == "outdated" else "✗")
                print(f"  {marker} {component['name']:<9} {component['state']:<9} {component['version']:<10} [{component['source']}] {component['detail'][:60]}")
            for harness in payload["harness_auth"]:
                marker = "✓" if harness["authed"] else "✗"
                print(f"  {'登录' if harness['installed'] else '未装'} {harness['harness']:<9} authed={marker} {harness['detail'][:60]}")
        return 0

    if args.command == "install":
        names = list(args.components)
        if not names:
            manifest = core.load_manifest()
            names = [entry["name"] for entry in manifest["components"]
                     if entry.get("default") and entry.get("install", {}).get("type") in ("npm", "bundled_zip")]
        core.note_explicit(names)
        try:
            job_id = core.install_components(names, mirror=args.mirror)
        except core.InstallInProgress as exc:
            print(json.dumps({"ok": False, "reason": "INSTALL_IN_PROGRESS", "error": str(exc)}, ensure_ascii=False))
            return 2
        print(json.dumps({"ok": True, "job_id": job_id}, ensure_ascii=False))
        if args.wait:
            while True:
                job = core.read_job(job_id)
                if job and job["state"] in ("succeeded", "failed"):
                    print(json.dumps(job, ensure_ascii=False, indent=2)[:4000])
                    return 0 if job["state"] == "succeeded" else 1
                time.sleep(1)
        return 0

    parser.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
