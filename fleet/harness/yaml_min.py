"""这是什么：Harness Profile 用的极小 YAML 子集解析器（零外部依赖，不引入 PyYAML）。
支持的语法（仅此而已，profile 文件必须遵守）：
  - `key: value`（字符串/整数/bool）
  - 块列表：
        key:
          - item1
          - item2
  - 行内列表：key: [a, b, c]
  - 注释（# 开头）与空行；值两侧引号会被剥掉。
不支持的语法一律报 YamlMiniError（宁可不解析，也不静默错读）。
"""

from __future__ import annotations


class YamlMiniError(ValueError):
    """profile 文本不符合受支持的 YAML 子集。"""


def _strip_quotes(text: str) -> str:
    text = text.strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in ("'", '"'):
        return text[1:-1]
    return text


def _scalar(text: str):
    low = text.lower()
    if low in ("true", "yes", "on"):
        return True
    if low in ("false", "no", "off"):
        return False
    if low in ("null", "~", ""):
        return None
    try:
        return int(text)
    except ValueError:
        pass
    try:
        return float(text)
    except ValueError:
        pass
    return _strip_quotes(text)


def parse(text: str) -> dict:
    """把 profile 文本解析成 dict[str, str | int | float | bool | list[str]]。"""
    data: dict = {}
    current_list_key: str | None = None
    for lineno, raw in enumerate(text.splitlines(), 1):
        line = raw.rstrip()
        if not line.strip() or line.strip().startswith("#"):
            continue
        if line.strip().startswith("- "):
            if current_list_key is None:
                raise YamlMiniError(f"第 {lineno} 行：列表项出现在任何 key 之外")
            data[current_list_key].append(_scalar(line.strip()[2:]))
            continue
        if ":" not in line:
            raise YamlMiniError(f"第 {lineno} 行：不是 `key: value` 形式 → {line.strip()[:60]}")
        if line[:1].isspace():
            raise YamlMiniError(f"第 {lineno} 行：不支持嵌套缩进（profile 是扁平结构）")
        key, _, value = line.partition(":")
        key = key.strip()
        value = value.strip()
        if not key or key.startswith("#"):
            raise YamlMiniError(f"第 {lineno} 行：空键名")
        if value.startswith("#"):
            value = ""
        if not value:
            data[key] = []
            current_list_key = key
            continue
        if value.startswith("[") and value.endswith("]"):
            inner = value[1:-1].strip()
            data[key] = [_scalar(item) for item in inner.split(",")] if inner else []
            current_list_key = None
            continue
        data[key] = _scalar(value)
        current_list_key = None
    return data
