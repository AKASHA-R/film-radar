"""只支持本项目用到的那一小部分 JSON Schema。

同一份 schema 字典既发给 API 做结构化输出，也在本地再校验一遍。
本地校验的意义：测试里的假响应、被截断或被拒答的真响应，都不受 API 的结构保证。
"""
from __future__ import annotations


class SchemaError(Exception):
    pass


def validate(value, schema: dict, path: str = "$") -> None:
    if "anyOf" in schema:
        for option in schema["anyOf"]:
            try:
                validate(value, option, path)
                return
            except SchemaError:
                continue
        raise SchemaError(f"{path}: 不符合任何一个备选类型，实为 {value!r}")

    kind = schema.get("type")
    if kind == "object":
        if not isinstance(value, dict):
            raise SchemaError(f"{path}: 应为对象")
        for key in schema.get("required", []):
            if key not in value:
                raise SchemaError(f"{path}: 缺少 {key}")
        properties = schema.get("properties", {})
        if schema.get("additionalProperties") is False:
            extra = sorted(set(value) - set(properties))
            if extra:
                raise SchemaError(f"{path}: 多出字段 {', '.join(extra)}")
        for key, sub in properties.items():
            if key in value:
                validate(value[key], sub, f"{path}.{key}")
    elif kind == "array":
        if not isinstance(value, list):
            raise SchemaError(f"{path}: 应为数组")
        for i, item in enumerate(value):
            validate(item, schema["items"], f"{path}[{i}]")
    elif kind == "string":
        if not isinstance(value, str):
            raise SchemaError(f"{path}: 应为字符串")
    elif kind == "integer":
        if isinstance(value, bool) or not isinstance(value, int):
            raise SchemaError(f"{path}: 应为整数")
    elif kind == "boolean":
        if not isinstance(value, bool):
            raise SchemaError(f"{path}: 应为布尔值")
    elif kind == "null":
        if value is not None:
            raise SchemaError(f"{path}: 应为 null")
    else:
        raise SchemaError(f"{path}: 不支持的 schema 类型 {kind!r}")

    if "enum" in schema and value not in schema["enum"]:
        raise SchemaError(f"{path}: {value!r} 不在允许取值内")
