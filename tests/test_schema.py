import pytest

from film_radar.schema import SchemaError, validate

SCHEMA = {
    "type": "object",
    "properties": {
        "id": {"type": "integer"},
        "keep": {"type": "boolean"},
        "rank": {"anyOf": [{"type": "integer"}, {"type": "null"}]},
        "kind": {"type": "string", "enum": ["a", "b"]},
        "level": {"type": "integer", "enum": [1, 2, 3]},
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"url": {"type": "string"}},
                "required": ["url"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["id", "keep", "rank", "kind", "level", "items"],
    "additionalProperties": False,
}


def good():
    return {"id": 1, "keep": True, "rank": None, "kind": "a", "level": 2, "items": [{"url": "https://x"}]}


def test_valid_value_passes():
    validate(good(), SCHEMA)


def test_nullable_accepts_both_branches():
    value = good()
    value["rank"] = 3
    validate(value, SCHEMA)


def test_missing_required_key():
    value = good()
    del value["keep"]
    with pytest.raises(SchemaError, match=r"\$: 缺少 keep"):
        validate(value, SCHEMA)


def test_wrong_type_reports_path():
    value = good()
    value["items"][0]["url"] = 5
    with pytest.raises(SchemaError, match=r"\$\.items\[0\]\.url"):
        validate(value, SCHEMA)


def test_bool_is_not_an_integer():
    value = good()
    value["id"] = True
    with pytest.raises(SchemaError, match=r"\$\.id"):
        validate(value, SCHEMA)


def test_string_enum():
    value = good()
    value["kind"] = "c"
    with pytest.raises(SchemaError, match=r"\$\.kind"):
        validate(value, SCHEMA)


def test_integer_enum():
    value = good()
    value["level"] = 9
    with pytest.raises(SchemaError, match=r"\$\.level"):
        validate(value, SCHEMA)


def test_nullable_rejects_other_types():
    value = good()
    value["rank"] = "first"
    with pytest.raises(SchemaError, match=r"\$\.rank"):
        validate(value, SCHEMA)


def test_extra_key_rejected_when_additional_properties_false():
    value = good()
    value["surprise"] = 1
    with pytest.raises(SchemaError, match="surprise"):
        validate(value, SCHEMA)


def test_top_level_must_be_object():
    with pytest.raises(SchemaError, match=r"\$: 应为对象"):
        validate([good()], SCHEMA)


def test_unsupported_schema_type_is_loud():
    with pytest.raises(SchemaError, match="不支持"):
        validate(1.5, {"type": "number"})
