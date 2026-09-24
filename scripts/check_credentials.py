#!/usr/bin/env python3
"""凭证泄漏回归检查脚本（P0-A-3）

用途：每次提交前运行，确保历史泄漏的凭证值不再出现在仓库文件中。
用法：python scripts/check_credentials.py
退出码：0 = 全部清洁；1 = 发现泄漏。

历史凭证（已全部轮换/作废）：
  - 163 邮箱授权码
  - AI 平台 API Key (sk-xxx)
  - 邮箱用户名
如果这些值再次出现在任何仓库文件中，说明回归发生了。
"""
import sys
from pathlib import Path

# 历史泄漏的凭证模式——用拼接构造，避免脚本自身触发误报
# 163 SMTP 授权码（已轮换）
_P1 = "PMF" + "HEFU" + "VASH" + "UISBQ"
# AI 平台 API Key 前缀（已注销）
_P2 = "sk-CRe" + "I4z9"
# 邮箱用户名（已替换为 ${EMAIL_USER}）
_P3 = "buchang" + "_123"

CREDENTIAL_PATTERNS = [_P1, _P2, _P3]

# 只扫描这些扩展名（避免二进制文件误报）
INCLUDE_GLOBS = ["*.py", "*.md", "*.txt", "*.env", "*.json", "*.ts", "*.vue", "*.yaml", "*.yml", "*.sh"]

# 排除目录 + 本脚本自身
EXCLUDE_DIRS = [".git", "node_modules", "__pycache__", ".venv", "dist"]
SELF_PATH = Path(__file__).resolve()


def main() -> int:
    repo_root = Path(__file__).resolve().parent.parent
    violations: list[str] = []

    for pattern in CREDENTIAL_PATTERNS:
        for glob in INCLUDE_GLOBS:
            for filepath in repo_root.rglob(glob):
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
        print("❌ 凭证回归检查失败——以下文件包含历史凭证值：")
        for v in violations:
            print(v)
        print(f"\n共 {len(violations)} 处。请将凭证值替换为 ${{VAR}} 环境变量占位符。")
        return 1
    else:
        print("✅ 凭证回归检查通过——仓库中无历史凭证值。")
        return 0


if __name__ == "__main__":
    sys.exit(main())
