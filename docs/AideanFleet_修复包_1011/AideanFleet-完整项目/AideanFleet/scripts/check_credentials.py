#!/usr/bin/env python3
"""凭证泄漏回归检查脚本（P0-A-3）

用途：每次提交前运行，确保历史泄漏的凭证值不再出现在**仓库跟踪文件**中。
用法：python scripts/check_credentials.py
退出码：0 = 全部清洁；1 = 发现泄漏。

扫描范围：仅 git 跟踪的文件（git ls-files），自动排除 .env 等本地密钥文件——
.env 本就存放真实值，不属于仓库文件；P0-A-2 的脱敏对象是入库文件。

历史凭证（已全部轮换/作废）：
  - 163 邮箱授权码
  - AI 平台 API Key (sk-xxx)
  - 邮箱用户名
如果这些值再次出现在任何入库文件中，说明回归发生了。
"""
import subprocess
import sys
from pathlib import Path

# Windows 控制台默认 GBK，emoji/中文会 UnicodeEncodeError
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# 历史泄漏的凭证模式——用拼接构造，避免脚本自身触发误报
# 163 SMTP 授权码（已轮换）
_P1 = "PMF" + "HEFU" + "VASH" + "UISBQ"
# AI 平台 API Key 前缀（已注销）
_P2 = "sk-CRe" + "I4z9"
# 邮箱用户名（已替换为 ${EMAIL_USER}）
_P3 = "buchang" + "_123"

CREDENTIAL_PATTERNS = [_P1, _P2, _P3]

# 只扫描这些扩展名（避免二进制文件误报）
INCLUDE_EXTS = {".py", ".md", ".txt", ".env", ".json", ".ts", ".vue", ".yaml", ".yml", ".sh"}

# 排除目录 + 本脚本自身
EXCLUDE_DIRS = {".git", "node_modules", "__pycache__", ".venv", "dist", "e2e-out"}
SELF_PATH = Path(__file__).resolve()


def tracked_files(repo_root: Path) -> list[Path]:
    """仅返回 git 跟踪的文件（排除 gitignored 本地文件）。"""
    try:
        out = subprocess.run(
            ["git", "-C", str(repo_root), "ls-files", "-z"],
            capture_output=True,
            check=True,
        )
    except (OSError, subprocess.CalledProcessError):
        # 非 git 环境兜底：回退到全库扫描（仍排除 EXCLUDE_DIRS）
        return [
            p
            for p in repo_root.rglob("*")
            if p.is_file() and p.suffix in INCLUDE_EXTS and not any(part in EXCLUDE_DIRS for part in p.parts)
        ]
    files: list[Path] = []
    for rel in out.stdout.decode("utf-8", errors="replace").split("\0"):
        if not rel:
            continue
        path = repo_root / rel
        if path.suffix in INCLUDE_EXTS and path.is_file():
            files.append(path)
    return files


def main() -> int:
    repo_root = Path(__file__).resolve().parent.parent
    violations: list[str] = []
    candidates = tracked_files(repo_root)

    for pattern in CREDENTIAL_PATTERNS:
        for filepath in candidates:
            if filepath == SELF_PATH:
                continue  # 排除自身
            if any(part in EXCLUDE_DIRS for part in filepath.parts):
                continue
            try:
                text = filepath.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue
            if pattern in text:
                for i, line in enumerate(text.splitlines(), 1):
                    if pattern in line:
                        violations.append(f"  {filepath.relative_to(repo_root)}:{i}: contains leaked credential pattern")
                        break

    if violations:
        print("[FAIL] 凭证回归检查失败——以下入库文件包含历史凭证值：")
        for v in violations:
            print(v)
        print(f"\n共 {len(violations)} 处。请将凭证值替换为 ${{VAR}} 环境变量占位符。")
        return 1
    print(f"[OK] 凭证回归检查通过——{len(candidates)} 个入库文件中无历史凭证值。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
