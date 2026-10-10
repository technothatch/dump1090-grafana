"""A hand-rolled validator for the JSON Schema subset this repository uses.

``schema/dashboard.schema.json`` is a real JSON Schema document, but the test
suite deliberately does not depend on the ``jsonschema`` package: the subset
actually needed here (types, ``required``, ``properties``,
``additionalProperties``, ``items``, ``enum``, ``const``, bounds, ``pattern``
and local ``$ref``) is small enough to implement in the standard library, and a
dashboard build must not fail because an optional dependency is missing.

``validate`` returns a flat list of ``"<json path>: <message>"`` strings; an
empty list means the instance matched the schema. The paths are intentionally
plain (``$.panels[2].fieldConfig.defaults.unit``) so they can be pasted into a
bug report.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import TypeGuard

#: The keywords understood by :func:`validate`. Anything else in a schema is
#: ignored, which keeps the document forward-compatible with full JSON Schema.
SUPPORTED_KEYWORDS: frozenset[str] = frozenset(
    {
        "$ref",
        "additionalProperties",
        "const",
        "enum",
        "items",
        "maxLength",
        "maximum",
        "minItems",
        "minLength",
        "minimum",
        "pattern",
        "properties",
        "required",
        "type",
    }
)

_REF_PREFIX = "#/$defs/"

_MAX_SHOWN = 120


class SchemaError(Exception):
    """Raised when the schema document itself is unusable."""


def validate(instance: object, schema: Mapping[str, object]) -> list[str]:
    """Check *instance* against *schema* and return every problem found."""
    return _check(instance, schema, schema, "$")


def validate_document(instance: object, schema: Mapping[str, object]) -> list[str]:
    """Like :func:`validate` but rejects schemas written in an unknown dialect."""
    known = SUPPORTED_KEYWORDS | {"$defs", "$schema", "$id", "title", "description"}
    unknown = sorted(set(schema) - known)
    if unknown:
        raise SchemaError(f"unsupported schema keyword(s): {', '.join(unknown)}")
    return validate(instance, schema)


def _check(
    instance: object, schema: Mapping[str, object], root: Mapping[str, object], path: str
) -> list[str]:
    ref = schema.get("$ref")
    if isinstance(ref, str):
        target = _resolve_ref(ref, root)
        if target is None:
            return [f"{path}: unresolvable reference {ref!r}"]
        return _check(instance, target, root, path)

    type_spec = schema.get("type")
    if type_spec is not None and not _type_matches(instance, type_spec):
        return [f"{path}: expected {_type_label(type_spec)}, got {_show(instance)}"]

    problems: list[str] = []

    if "const" in schema and not _same(instance, schema["const"]):
        problems.append(
            f"{path}: expected constant {_show(schema['const'])}, got {_show(instance)}"
        )

    enum = schema.get("enum")
    if isinstance(enum, list) and not any(_same(instance, option) for option in enum):
        problems.append(f"{path}: expected one of {_show(enum)}, got {_show(instance)}")

    if isinstance(instance, dict):
        problems.extend(_check_object(instance, schema, root, path))
    elif isinstance(instance, list):
        problems.extend(_check_array(instance, schema, root, path))
    elif isinstance(instance, str):
        problems.extend(_check_string(instance, schema, path))
    elif isinstance(instance, int | float) and not isinstance(instance, bool):
        problems.extend(_check_number(instance, schema, path))

    return problems


def _check_object(
    instance: dict[object, object],
    schema: Mapping[str, object],
    root: Mapping[str, object],
    path: str,
) -> list[str]:
    problems: list[str] = []

    required = schema.get("required")
    if isinstance(required, list):
        for key in required:
            if isinstance(key, str) and key not in instance:
                problems.append(f"{path}: missing required property {key!r}")

    properties = schema.get("properties")
    if isinstance(properties, dict):
        for key, subschema in properties.items():
            if key in instance and isinstance(subschema, dict):
                problems.extend(_check(instance[key], subschema, root, f"{path}.{key}"))

    additional = schema.get("additionalProperties")
    if additional is False and isinstance(properties, dict):
        for key in instance:
            if key not in properties:
                problems.append(f"{path}: unexpected property {key!r}")
    elif isinstance(additional, dict):
        for key, value in instance.items():
            if not (isinstance(properties, dict) and key in properties):
                problems.extend(_check(value, additional, root, f"{path}.{key}"))

    return problems


def _check_array(
    instance: list[object],
    schema: Mapping[str, object],
    root: Mapping[str, object],
    path: str,
) -> list[str]:
    problems: list[str] = []

    min_items = schema.get("minItems")
    if _is_number(min_items) and len(instance) < min_items:
        problems.append(f"{path}: expected at least {min_items} items, got {len(instance)}")

    items = schema.get("items")
    if isinstance(items, dict):
        for index, element in enumerate(instance):
            problems.extend(_check(element, items, root, f"{path}[{index}]"))

    return problems


def _check_string(instance: str, schema: Mapping[str, object], path: str) -> list[str]:
    problems: list[str] = []

    min_length = schema.get("minLength")
    if _is_number(min_length) and len(instance) < min_length:
        problems.append(f"{path}: expected at least {min_length} characters, got {len(instance)}")

    max_length = schema.get("maxLength")
    if _is_number(max_length) and len(instance) > max_length:
        problems.append(f"{path}: expected at most {max_length} characters, got {len(instance)}")

    pattern = schema.get("pattern")
    if isinstance(pattern, str):
        try:
            matched = re.search(pattern, instance) is not None
        except re.error as exc:
            problems.append(f"{path}: invalid pattern {pattern!r}: {exc}")
        else:
            if not matched:
                problems.append(f"{path}: {_show(instance)} does not match pattern {pattern!r}")

    return problems


def _check_number(instance: int | float, schema: Mapping[str, object], path: str) -> list[str]:
    problems: list[str] = []

    minimum = schema.get("minimum")
    if _is_number(minimum) and instance < minimum:
        problems.append(f"{path}: expected at least {minimum}, got {_show(instance)}")

    maximum = schema.get("maximum")
    if _is_number(maximum) and instance > maximum:
        problems.append(f"{path}: expected at most {maximum}, got {_show(instance)}")

    return problems


def _resolve_ref(ref: str, root: Mapping[str, object]) -> Mapping[str, object] | None:
    if not ref.startswith(_REF_PREFIX):
        return None
    definitions = root.get("$defs")
    if not isinstance(definitions, dict):
        return None
    target = definitions.get(ref.removeprefix(_REF_PREFIX))
    if isinstance(target, dict):
        return target
    return None


def _type_matches(value: object, spec: object) -> bool:
    if isinstance(spec, str):
        return _matches_one(value, spec)
    if isinstance(spec, list):
        names = [item for item in spec if isinstance(item, str)]
        if not names:
            return True
        return any(_matches_one(value, name) for name in names)
    return True


def _matches_one(value: object, name: str) -> bool:
    if name == "object":
        return isinstance(value, dict)
    if name == "array":
        return isinstance(value, list)
    if name == "string":
        return isinstance(value, str)
    if name == "boolean":
        return isinstance(value, bool)
    if name == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if name == "number":
        return isinstance(value, int | float) and not isinstance(value, bool)
    if name == "null":
        return value is None
    return True


def _type_label(spec: object) -> str:
    if isinstance(spec, str):
        return spec
    if isinstance(spec, list):
        return " or ".join(str(item) for item in spec)
    return _show(spec)


def _same(left: object, right: object) -> bool:
    if isinstance(left, bool) != isinstance(right, bool):
        return False
    return bool(left == right)


def _is_number(value: object) -> TypeGuard[int | float]:
    return isinstance(value, int | float) and not isinstance(value, bool)


def _show(value: object) -> str:
    text = repr(value)
    if len(text) > _MAX_SHOWN:
        return f"{text[: _MAX_SHOWN - 3]}..."
    return text
