#!/usr/bin/env python3
"""fetch_runtimes —— 构建期下载运行时并校验 SHA256（TASK-201，A-14 离线内置）。

用法：
    python scripts/installer/windows/fetch_runtimes.py            # 下载缺失 + 校验
    python scripts/installer/windows/fetch_runtimes.py --check    # 只校验已下载产物
    python scripts/installer/windows/fetch_runtimes.py --mirror cn # 指定镜像
产物目录：scripts/installer/windows/_runtimes/（gitignore，构建产物）。
失败（下载失败/校验不符）即中止构建（退出码非 0）——用户机器上不联网装运行时。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
MANIFEST = ROOT / "scripts" / "installer" / "manifest.json"
OUT_DIR = Path(__file__).resolve().parent / "_runtimes"


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def download(url: str, target: Path) -> None:
    req = urllib.request.Request(url, headers={"User-Agent": "aideanfleet-installer-build"})
    with urllib.request.urlopen(req, timeout=300) as resp, open(target, "wb") as fh:
        while True:
            chunk = resp.read(1 << 20)
            if not chunk:
                break
            fh.write(chunk)


def main() -> int:
    parser = argparse.ArgumentParser(description="构建期运行时获取与校验")
    parser.add_argument("--check", action="store_true", help="只校验已下载产物，不下载")
    parser.add_argument("--mirror", choices=["auto", "official", "cn"], default="auto")
    parser.add_argument("--out", default=str(OUT_DIR))
    args = parser.parse_args()

    out_dir = Path(args.out)
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    artifacts = [entry for entry in manifest["components"]
                 if entry.get("install", {}).get("type") == "bundled_zip"]

    failures = 0
    for entry in artifacts:
        name = entry["install"]["artifact"]
        expected = entry.get("sha256") or ""
        target = out_dir / name
        if args.check:
            if not target.is_file():
                print(f"CHECKSUM_MISMATCH/{name}: 文件不存在（先运行 fetch_runtimes.py）", file=sys.stderr)
                failures += 1
                continue
            actual = sha256_of(target)
            if expected and actual != expected:
                print(f"CHECKSUM_MISMATCH/{name}: {actual} != {expected}", file=sys.stderr)
                failures += 1
            else:
                print(f"OK {name} sha256={actual[:16]}…")
            continue

        if target.is_file() and (not expected or sha256_of(target) == expected):
            print(f"CACHED {name}")
            continue
        urls = entry.get("urls") or {}
        order: list[str] = []
        if args.mirror == "official":
            order = [urls["official"]]
        elif args.mirror == "cn":
            order = [urls.get("cn") or urls["official"]]
        else:
            order = [u for u in (urls.get("official"), urls.get("cn")) if u]
        ok = False
        last_error = ""
        for url in order:
            try:
                print(f"下载 {name} ← {url}", flush=True)
                out_dir.mkdir(parents=True, exist_ok=True)
                download(url, target)
                actual = sha256_of(target)
                if expected and actual != expected:
                    last_error = f"CHECKSUM_MISMATCH: {actual} != {expected}"
                    print(f"  {last_error}", file=sys.stderr)
                    target.unlink(missing_ok=True)
                    continue
                print(f"OK {name} sha256={actual[:16]}…")
                ok = True
                break
            except Exception as exc:
                last_error = f"DOWNLOAD_FAILED: {exc}"
                print(f"  {last_error}", file=sys.stderr)
        if not ok:
            failures += 1
            print(f"{name}: {last_error}", file=sys.stderr)

    if failures:
        print(f"\n{failures} 个运行时产物未就绪——中止构建", file=sys.stderr)
        return 1
    print("\n全部运行时产物就绪（构建期校验通过）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
