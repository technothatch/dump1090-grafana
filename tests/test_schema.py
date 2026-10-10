"""Unit tests for the hand-rolled JSON Schema subset validator."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from dump1090_grafana.schema import (
    SUPPORTED_KEYWORDS,
    SchemaError,
    validate,
    validate_document,
)

ROOT = Path(__file__).resolve().parents[1]


def test_real_schema_document_uses_only_supported_keywords() -> None:
    raw = (ROOT / "schema" / "dashboard.schema.json").read_text(encoding="utf-8")
    schema = json.loads(raw)
    # raises SchemaError as soon as the document uses a keyword we ignore
    validate_document({}, schema)
    assert "$ref" in SUPPORTED_KEYWORDS
    assert {"minItems", "additionalProperties", "pattern"} <= SUPPORTED_KEYWORDS


def test_empty_schema_accepts_anything() -> None:
    assert validate(42, {}) == []
    assert validate({"a": [1, 2]}, {}) == []


def test_type_string_match_and_mismatch() -> None:
    assert validate("x", {"type": "integer"}) == ["$: expected integer, got 'x'"]
    assert validate(7, {"type": "integer"}) == []
    assert validate(None, {"type": "null"}) == []
    assert validate([], {"type": "object"}) == ["$: expected object, got []"]


def test_bool_is_not_an_integer() -> None:
    assert validate(True, {"type": "integer"}) != []
    assert validate(True, {"type": "boolean"}) == []


def test_type_list_accepts_any_declared_type() -> None:
    schema = {"type": ["integer", "null"]}
    assert validate(0, schema) == []
    assert validate(None, schema) == []
    assert validate("x", schema) == ["$: expected integer or null, got 'x'"]


def test_unknown_type_name_or_spec_is_ignored() -> None:
    assert validate("x", {"type": "banana"}) == []
    assert validate("x", {"type": 42}) == []
    assert validate("x", {"type": [42]}) == []


def test_missing_required_property() -> None:
    schema = {"type": "object", "required": ["uid", "title"]}
    assert validate({"uid": "a"}, schema) == ["$: missing required property 'title'"]
    assert validate({"uid": "a", "title": "b"}, schema) == []
    # a non-string entry in a malformed schema cannot crash the walk
    assert validate({}, {"required": [7]}) == []


def test_additional_properties_false_rejects_unknown_keys() -> None:
    schema = {
        "type": "object",
        "properties": {"a": {"type": "integer"}},
        "additionalProperties": False,
    }
    assert validate({"a": 1, "b": 2}, schema) == ["$: unexpected property 'b'"]
    assert validate({"a": 1}, schema) == []


def test_additional_properties_schema_checks_unknown_keys() -> None:
    schema = {"type": "object", "properties": {"a": {}}, "additionalProperties": {"type": "string"}}
    assert validate({"b": 1}, schema) == ["$.b: expected string, got 1"]
    assert validate({"b": "ok"}, schema) == []


def test_const_and_enum() -> None:
    assert validate("a", {"const": "a"}) == []
    assert validate("b", {"const": "a"}) == ["$: expected constant 'a', got 'b'"]
    assert validate("red", {"enum": ["green", "red"]}) == []
    assert validate("blue", {"enum": ["green", "red"]}) == [
        "$: expected one of ['green', 'red'], got 'blue'"
    ]


def test_enum_is_type_sensitive() -> None:
    assert validate(True, {"enum": [1]}) != []
    assert validate(1, {"enum": [1]}) == []


def test_array_items_and_min_items() -> None:
    schema = {"type": "array", "minItems": 2, "items": {"type": "integer"}}
    assert validate([], schema) == ["$: expected at least 2 items, got 0"]
    assert validate([1, "x"], schema) == ["$[1]: expected integer, got 'x'"]
    assert validate([1, 2], schema) == []


def test_string_length_and_pattern() -> None:
    schema = {"type": "string", "minLength": 2, "maxLength": 3, "pattern": "^[a-z]+$"}
    assert validate("a", schema) == ["$: expected at least 2 characters, got 1"]
    assert validate("abcd", schema) == ["$: expected at most 3 characters, got 4"]
    assert validate("Aa", schema) == ["$: 'Aa' does not match pattern '^[a-z]+$'"]
    assert validate("ab", schema) == []


def test_invalid_pattern_is_reported_not_raised() -> None:
    problems = validate("x", {"type": "string", "pattern": "["})
    assert len(problems) == 1
    assert "invalid pattern" in problems[0]


def test_number_bounds() -> None:
    schema = {"type": "integer", "minimum": 1, "maximum": 4}
    assert validate(0, schema) == ["$: expected at least 1, got 0"]
    assert validate(5, schema) == ["$: expected at most 4, got 5"]
    assert validate(2, schema) == []


def test_local_ref_is_resolved() -> None:
    schema = {
        "$defs": {"uid": {"type": "string", "minLength": 1}},
        "properties": {"uid": {"$ref": "#/$defs/uid"}},
    }
    assert validate({"uid": ""}, schema) == ["$.uid: expected at least 1 characters, got 0"]
    assert validate({"uid": "ok"}, schema) == []


def test_unresolvable_refs_are_reported() -> None:
    assert validate({}, {"$ref": "#/$defs/missing"}) == [
        "$: unresolvable reference '#/$defs/missing'"
    ]
    assert validate({}, {"$ref": "#/definitions/other"}) == [
        "$: unresolvable reference '#/definitions/other'"
    ]
    assert validate({}, {"$ref": 5}) == []


def test_nested_paths_point_at_the_offending_node() -> None:
    schema = {
        "type": "object",
        "properties": {
            "panels": {"type": "array", "items": {"type": "object", "required": ["id"]}}
        },
    }
    problems = validate({"panels": [{"id": 1}, {}]}, schema)
    assert problems == ["$.panels[1]: missing required property 'id'"]


def test_validate_document_rejects_unknown_keywords() -> None:
    with pytest.raises(SchemaError, match="unsupported schema keyword"):
        validate_document({}, {"oneOf": [{"type": "string"}]})
    with pytest.raises(SchemaError, match="anyOf"):
        validate_document({}, {"anyOf": []})


def test_long_values_are_truncated_in_messages() -> None:
    problems = validate("x" * 500, {"type": "integer"})
    assert len(problems[0]) < 200
    assert problems[0].endswith("...")
