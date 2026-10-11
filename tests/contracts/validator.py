"""零依赖 JSON Schema 子集校验器（TASK-002，ADR-002）。

支持关键字（packages/contracts/README.md 约定）：
  type / properties / required / enum / items / additionalProperties /
  minLength / maxLength / minimum / maximum / pattern / const / $ref（目录内相对引用）/ oneOf

用法：
    from tests.contracts.validator import validate
    errors = validate(instance, schema, root_dir=Path("packages/contracts"))
    # errors: list[str]，空列表 = 通过
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

_CACHE: dict[str, dict] = {}


def _load(uri_base: Path, ref_file: str) -> dict:
    target = (uri_base / ref_file).resolve()
    key = str(target)
    if key not in _CACHE:
        _CACHE[key] = json.loads(target.read_text(encoding="utf-8"))
    return _CACHE[key]


def _resolve_ref(ref: str, source_file: Path, root_dir: Path,
                 root_schema: dict | None = None) -> tuple[dict, Path]:
    file_part, _, frag = ref.partition("#")
    if file_part:
        doc = _load(source_file.parent, file_part)
        target_file = source_file.parent / file_part
    elif frag and root_schema is not None:
        # 同文档引用（#/...）：在调用方给的 schema 文档内解析
        schema: Any = root_schema
        for part in frag.strip("/").split("/"):
            schema = schema[part]
        return schema, source_file or root_dir / "__inline__"
    else:
        doc = _load(source_file.parent, source_file.name) if not source_file.is_absolute() else _load(source_file.parent, source_file.name)
        target_file = source_file
    schema_any: Any = doc
    if frag:
        for part in frag.strip("/").split("/"):
            schema_any = schema_any[part]
    return schema_any, target_file


def _type_ok(value: Any, t: str) -> bool:
    if t == "object":
        return isinstance(value, dict)
    if t == "array":
        return isinstance(value, list)
    if t == "string":
        return isinstance(value, str)
    if t == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if t == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if t == "boolean":
        return isinstance(value, bool)
    if t == "null":
        return value is None
    return True


def validate(instance: Any, schema: dict, *, root_dir: Path, source_file: Path | None = None,
             path: str = "$", root_schema: dict | None = None) -> list[str]:
    """返回错误列表；空 = 通过。root_dir 用于解析跨文件 $ref；root_schema 用于同文档 #/ 引用。"""
    errors: list[str] = []
    if source_file is None:
        source_file = root_dir / "__inline__"
    if root_schema is None:
        root_schema = schema

    def err(msg: str) -> None:
        errors.append(f"{path}: {msg}")

    if "$ref" in schema:
        try:
            resolved, target = _resolve_ref(schema["$ref"], source_file, root_dir, root_schema)
        except (OSError, KeyError, json.JSONDecodeError) as exc:
            err(f"$ref 无法解析 {schema['$ref']}: {exc}")
            return errors
        errors.extend(validate(instance, resolved, root_dir=root_dir, source_file=target,
                               path=path, root_schema=root_schema))
        return errors

    t = schema.get("type")
    if t is not None:
        types = t if isinstance(t, list) else [t]
        if not any(_type_ok(instance, item) for item in types):
            err(f"类型应为 {types}，实际 {type(instance).__name__}")
            return errors

    if "const" in schema and instance != schema["const"]:
        err(f"应为 const {schema['const']!r}，实际 {instance!r}")

    if "enum" in schema and instance not in schema["enum"]:
        err(f"{instance!r} 不在枚举 {schema['enum']}")

    if isinstance(instance, str):
        if "minLength" in schema and len(instance) < schema["minLength"]:
            err(f"长度 {len(instance)} < minLength {schema['minLength']}")
        if "maxLength" in schema and len(instance) > schema["maxLength"]:
            err(f"长度 {len(instance)} > maxLength {schema['maxLength']}")
        if "pattern" in schema and not re.search(schema["pattern"], instance):
            err(f"不匹配 pattern {schema['pattern']!r}")

    if isinstance(instance, (int, float)) and not isinstance(instance, bool):
        if "minimum" in schema and instance < schema["minimum"]:
            err(f"{instance} < minimum {schema['minimum']}")
        if "maximum" in schema and instance > schema["maximum"]:
            err(f"{instance} > maximum {schema['maximum']}")

    if isinstance(instance, list):
        items = schema.get("items")
        if isinstance(items, dict):
            for i, item in enumerate(instance):
                errors.extend(validate(item, items, root_dir=root_dir,
                                       source_file=source_file, path=f"{path}[{i}]",
                                       root_schema=root_schema))

    if isinstance(instance, dict):
        props = schema.get("properties") or {}
        for name in schema.get("required") or []:
            if name not in instance:
                err(f"缺少必填字段 {name!r}")
        additional = schema.get("additionalProperties")
        if additional is False:
            for name in instance:
                if name not in props:
                    err(f"多余字段 {name!r}（additionalProperties=false）")
        for name, sub in props.items():
            if name in instance:
                errors.extend(validate(instance[name], sub, root_dir=root_dir,
                                       source_file=source_file, path=f"{path}.{name}",
                                       root_schema=root_schema))
        if isinstance(additional, dict):
            for name, value in instance.items():
                if name not in props:
                    errors.extend(validate(value, additional, root_dir=root_dir,
                                           source_file=source_file, path=f"{path}.{name}",
                                           root_schema=root_schema))

    if "oneOf" in schema:
        ok_count = sum(1 for sub in schema["oneOf"]
                       if not validate(instance, sub, root_dir=root_dir,
                                       source_file=source_file, path=path,
                                       root_schema=root_schema))
        if ok_count != 1:
            err(f"oneOf 匹配数 {ok_count} != 1")

    return errors


def load_schema(rel_path: str, contracts_dir: Path | None = None) -> dict:
    base = contracts_dir or Path(__file__).resolve().parents[2] / "packages" / "contracts"
    return json.loads((base / rel_path).read_text(encoding="utf-8"))
