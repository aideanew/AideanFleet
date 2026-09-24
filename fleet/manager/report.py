"""这是什么：六节报告的解析与校验。执行体回执少任何一节都不得进入审查。
怎么用：from fleet.manager import report;  report.parse(text) / report.missing_sections(text)
契约：prompts/报告模板.md（六节标题原样出现一次：改动清单/命令记录/证据链/四要素/未完成事项/模型自述）。
"""

from __future__ import annotations

import re
from typing import Any

#: 六节标题（顺序即模板顺序，冻结）
SECTION_NAMES: tuple[str, ...] = ("改动清单", "命令记录", "证据链", "四要素", "未完成事项", "模型自述")

_TITLE_RE = re.compile(
    r"^\s*(?:#{1,6}\s*)?(?:第?\s*\d+\s*[.、)]\s*)?(?:\*\*|__)?\s*("
    + "|".join(SECTION_NAMES)
    + r")\s*(?:\*\*|__)?\s*[:：]?\s*$"
)


class MissingReportSection(Exception):
    """报告缺节。missing 里是被漏掉的节名。"""

    def __init__(self, missing: list[str]) -> None:
        self.missing = missing
        super().__init__("六节报告缺少小节：" + "、".join(missing))


def _lines(text: str) -> list[str]:
    return str(text or "").replace("\r\n", "\n").replace("\r", "\n").split("\n")


def boundaries(text: str) -> list[tuple[str, int]]:
    """找出各节标题的行号，返回 [(节名, 行号)]（保持出现顺序）。"""
    found: list[tuple[str, int]] = []
    seen: set[str] = set()
    for index, line in enumerate(_lines(text)):
        match = _TITLE_RE.match(line)
        if not match:
            continue
        name = match.group(1)
        if name in seen:
            continue
        seen.add(name)
        found.append((name, index))
    return found


def parse(text: str) -> dict[str, str]:
    """把报告拆成 {节名: 正文}；缺节抛 MissingReportSection。"""
    lines = _lines(text)
    marks = boundaries(text)
    missing = [name for name in SECTION_NAMES if name not in {item[0] for item in marks}]
    if missing:
        raise MissingReportSection(missing)

    sections: dict[str, str] = {}
    for position, (name, start) in enumerate(marks):
        end = marks[position + 1][1] if position + 1 < len(marks) else len(lines)
        sections[name] = "\n".join(lines[start + 1 : end]).strip()
    return {name: sections.get(name, "") for name in SECTION_NAMES}


def missing_sections(text: str) -> list[str]:
    """只返回缺失的节名（不抛异常，供机器门直接判失败）。"""
    present = {item[0] for item in boundaries(text)}
    return [name for name in SECTION_NAMES if name not in present]


def is_complete(text: str) -> bool:
    """是否六节齐全。"""
    return not missing_sections(text)


def summary(text: str) -> dict[str, Any]:
    """给事件/报告用的紧凑摘要（不复制全文，避免事件流膨胀）。"""
    missing = missing_sections(text)
    return {
        "six_sections": not missing,
        "missing": missing,
        "length": len(str(text or "")),
    }