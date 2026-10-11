"""这是什么：设计文档验收门（A5：verify 必须是真实命令，禁止"文件存在即通过"）。
怎么用：python -m fleet.gates.doclint docs/design.md   [更多文档路径...]
规则（全部满足才通过，exit 0；任何一条不满足 exit 1 并给出原因）：
  1. 文件存在且为 UTF-8 文本；
  2. 有效内容（去空白行/代码围栏后）≥ 300 字符；
  3. Markdown 标题 ≥ 3 个（# 开头）；
  4. 至少命中 3 类关键词：技术选型/架构/目录结构/模块/接口/数据流/依赖。
本模块只依赖标准库，供 verify_cmd 在任意工作区 cwd 下执行。
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

MIN_EFFECTIVE_CHARS = 300
MIN_HEADINGS = 3
KEYWORD_GROUPS = [
    ("技术选型", "选型", "技术栈", "框架"),
    ("架构", "分层", "模块划分", "组件"),
    ("目录结构", "目录", "文件结构", "工程结构"),
    ("模块", "组件", "服务"),
    ("接口", "API", "协议", "契约"),
    ("数据流", "数据结构", "存储", "模型"),
    ("依赖", "环境", "版本"),
]
MIN_KEYWORD_HITS = 3


def _effective_text(text: str) -> str:
    """去掉代码围栏与空白行的正文——围栏里的代码不算设计说明。"""
    text = re.sub(r"```.*?```", "", text, flags=re.DOTALL)
    lines = [ln for ln in text.splitlines() if ln.strip()]
    return "\n".join(lines)


def lint_doc(path: Path) -> list[str]:
    """返回问题列表；空列表 = 通过。"""
    problems: list[str] = []
    if not path.is_file():
        return [f"文件不存在: {path}"]
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return [f"文件不是 UTF-8 文本: {path}"]

    effective = _effective_text(text)
    if len(effective) < MIN_EFFECTIVE_CHARS:
        problems.append(
            f"有效内容不足：{len(effective)} 字符 < {MIN_EFFECTIVE_CHARS}"
            "（代码围栏与空行不计入）"
        )

    headings = [ln for ln in text.splitlines() if re.match(r"\s*#{1,6}\s+\S", ln)]
    if len(headings) < MIN_HEADINGS:
        problems.append(f"Markdown 标题过少：{len(headings)} 个 < {MIN_HEADINGS} 个")

    hits = sum(1 for group in KEYWORD_GROUPS if any(k in text for k in group))
    if hits < MIN_KEYWORD_HITS:
        problems.append(
            f"设计要素不足：仅覆盖 {hits} 类主题 < {MIN_KEYWORD_HITS} 类"
            "（技术选型/架构/目录结构/模块/接口/数据流/依赖）"
        )
    return problems


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args:
        print("用法: python -m fleet.gates.doclint <doc.md> [more.md ...]")
        return 2
    failures = 0
    for arg in args:
        problems = lint_doc(Path(arg))
        if problems:
            failures += 1
            print(f"[doclint] FAIL {arg}")
            for p in problems:
                print(f"  - {p}")
        else:
            print(f"[doclint] PASS {arg}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
