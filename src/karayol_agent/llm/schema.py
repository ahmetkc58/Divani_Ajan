"""A small, strict JSON-Schema subset for LLM structured output.

The validator intentionally supports fewer features than a general JSON Schema
engine.  Closed objects, bounded nesting and bounded response size make the
provider boundary predictable without introducing another runtime dependency.
"""

from __future__ import annotations

import json
import math
from typing import Any, Mapping, Sequence


class SchemaDefinitionError(ValueError):
    pass


class SchemaValidationError(ValueError):
    pass


_TYPES = {"object", "array", "string", "integer", "number", "boolean", "null"}
_COMMON_KEYS = {"type", "enum", "const", "title", "description"}
_TYPE_KEYS = {
    "object": {"properties", "required", "additionalProperties", "minProperties", "maxProperties"},
    "array": {"items", "minItems", "maxItems"},
    "string": {"minLength", "maxLength"},
    "integer": {"minimum", "maximum"},
    "number": {"minimum", "maximum"},
    "boolean": set(),
    "null": set(),
}


def _matches_type(value: Any, expected: str) -> bool:
    return {
        "object": isinstance(value, dict),
        "array": isinstance(value, list),
        "string": isinstance(value, str),
        "integer": isinstance(value, int) and not isinstance(value, bool),
        "number": isinstance(value, (int, float)) and not isinstance(value, bool),
        "boolean": isinstance(value, bool),
        "null": value is None,
    }[expected]


def _schema_types(schema: Mapping[str, Any], path: str) -> tuple[str, ...]:
    value = schema.get("type")
    if isinstance(value, str):
        types = (value,)
    elif isinstance(value, list) and value and all(isinstance(item, str) for item in value):
        types = tuple(value)
    else:
        raise SchemaDefinitionError(f"{path}.type açıkça tanımlanmalıdır.")
    if len(types) != len(set(types)) or not set(types) <= _TYPES:
        raise SchemaDefinitionError(f"{path}.type desteklenmeyen değer içeriyor.")
    if len(types) > 2 or (len(types) == 2 and "null" not in types):
        raise SchemaDefinitionError(
            f"{path}.type yalnız tek tür veya bir tür + null içerebilir."
        )
    return types


def validate_schema_definition(
    schema: Mapping[str, Any], *, max_depth: int = 8, max_properties: int = 128
) -> None:
    try:
        serialized_schema = json.dumps(schema, ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise SchemaDefinitionError("JSON şeması JSON-uyumlu olmalıdır.") from exc
    if len(serialized_schema) > 65_536:
        raise SchemaDefinitionError("JSON şeması boyut sınırını aşıyor.")
    property_counter = [0]

    def visit(node: Any, path: str, depth: int) -> None:
        if not isinstance(node, Mapping):
            raise SchemaDefinitionError(f"{path} bir JSON şema nesnesi olmalıdır.")
        if depth > max_depth:
            raise SchemaDefinitionError("JSON şeması izin verilen iç içe geçme sınırını aşıyor.")
        if any(str(key).startswith("$") for key in node):
            raise SchemaDefinitionError("$ref/$defs gibi dolaylı şema özellikleri desteklenmez.")

        types = _schema_types(node, path)
        effective_types = [item for item in types if item != "null"]
        primary_type = effective_types[0] if effective_types else "null"
        allowed_keys = _COMMON_KEYS | _TYPE_KEYS[primary_type]
        unknown = set(node) - allowed_keys
        if unknown:
            raise SchemaDefinitionError(
                f"{path} desteklenmeyen şema alanları içeriyor: {sorted(unknown)}"
            )

        if "enum" in node:
            enum = node["enum"]
            if not isinstance(enum, list) or not enum or len(enum) > 100:
                raise SchemaDefinitionError(f"{path}.enum 1-100 değer içermelidir.")
            try:
                canonical_values = [
                    json.dumps(item, ensure_ascii=False, sort_keys=True)
                    for item in enum
                ]
            except TypeError as exc:
                raise SchemaDefinitionError(
                    f"{path}.enum kanonik JSON değerleri içermelidir."
                ) from exc
            if len(canonical_values) != len(set(canonical_values)):
                raise SchemaDefinitionError(f"{path}.enum tekrarlı değer içeremez.")
            if any(
                not any(_matches_type(item, expected) for expected in types)
                for item in enum
            ):
                raise SchemaDefinitionError(f"{path}.enum tanımlı type ile uyuşmuyor.")
        if "const" in node and not any(
            _matches_type(node["const"], expected) for expected in types
        ):
            raise SchemaDefinitionError(f"{path}.const tanımlı type ile uyuşmuyor.")

        if primary_type == "object":
            properties = node.get("properties")
            if not isinstance(properties, Mapping):
                raise SchemaDefinitionError(f"{path}.properties tanımlanmalıdır.")
            if node.get("additionalProperties") is not False:
                raise SchemaDefinitionError(
                    f"{path}.additionalProperties güvenlik için false olmalıdır."
                )
            property_counter[0] += len(properties)
            if property_counter[0] > max_properties:
                raise SchemaDefinitionError("JSON şeması çok fazla alan içeriyor.")
            required = node.get("required", [])
            if not isinstance(required, list) or not all(
                isinstance(item, str) for item in required
            ):
                raise SchemaDefinitionError(f"{path}.required string listesi olmalıdır.")
            if len(required) != len(set(required)) or not set(required) <= set(properties):
                raise SchemaDefinitionError(f"{path}.required bilinmeyen/tekrarlı alan içeriyor.")
            for name, child in properties.items():
                if not isinstance(name, str) or not name or len(name) > 80:
                    raise SchemaDefinitionError(f"{path}.properties alan adı geçersiz.")
                visit(child, f"{path}.{name}", depth + 1)
        elif primary_type == "array":
            if "items" not in node:
                raise SchemaDefinitionError(f"{path}.items tanımlanmalıdır.")
            visit(node["items"], f"{path}[]", depth + 1)
        for keyword in ("minLength", "maxLength", "minItems", "maxItems", "minProperties", "maxProperties"):
            if keyword in node and (
                not isinstance(node[keyword], int)
                or isinstance(node[keyword], bool)
                or node[keyword] < 0
            ):
                raise SchemaDefinitionError(f"{path}.{keyword} negatif olmayan tam sayı olmalıdır.")
        for keyword in ("minimum", "maximum"):
            if keyword in node and (
                not isinstance(node[keyword], (int, float))
                or isinstance(node[keyword], bool)
                or not math.isfinite(node[keyword])
            ):
                raise SchemaDefinitionError(f"{path}.{keyword} sonlu sayı olmalıdır.")
        for low_name, high_name in (
            ("minLength", "maxLength"),
            ("minItems", "maxItems"),
            ("minProperties", "maxProperties"),
            ("minimum", "maximum"),
        ):
            if low_name in node and high_name in node and node[low_name] > node[high_name]:
                raise SchemaDefinitionError(f"{path} alt sınırı üst sınırdan büyük olamaz.")

    visit(schema, "$", 0)


def parse_json_object(raw_text: str, *, max_chars: int = 65_536) -> Mapping[str, Any]:
    if not isinstance(raw_text, str) or not raw_text.strip():
        raise SchemaValidationError("Model boş bir yanıt döndürdü.")
    if len(raw_text) > max_chars:
        raise SchemaValidationError("Model yanıtı izin verilen boyutu aşıyor.")
    text = raw_text.strip()
    if text.startswith("```"):
        raise SchemaValidationError("Model yanıtı saf JSON nesnesi değildir.")

    def reject_constant(value: str) -> None:
        raise SchemaValidationError(f"Geçersiz JSON sayısal sabiti: {value}")

    def reject_duplicates(pairs: Sequence[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise SchemaValidationError(f"Tekrarlanan JSON alanı: {key}")
            result[key] = value
        return result

    try:
        value = json.loads(
            text,
            parse_constant=reject_constant,
            object_pairs_hook=reject_duplicates,
        )
    except SchemaValidationError:
        raise
    except (json.JSONDecodeError, TypeError, ValueError) as exc:
        raise SchemaValidationError("Model yanıtı geçerli JSON değildir.") from exc
    if not isinstance(value, dict):
        raise SchemaValidationError("Model yanıtının üst seviyesi JSON nesnesi olmalıdır.")
    return value


def validate_instance(value: Any, schema: Mapping[str, Any], *, path: str = "$") -> None:
    types = _schema_types(schema, path)
    if value is None:
        if "null" in types:
            return
        raise SchemaValidationError(f"{path} null olamaz.")

    non_null_types = [item for item in types if item != "null"]
    expected = non_null_types[0] if non_null_types else "null"
    matches = _matches_type(value, expected)
    if not matches:
        raise SchemaValidationError(f"{path} beklenen {expected} türünde değildir.")
    if isinstance(value, float) and not math.isfinite(value):
        raise SchemaValidationError(f"{path} sonlu bir sayı olmalıdır.")
    if "enum" in schema and value not in schema["enum"]:
        raise SchemaValidationError(f"{path} izinli enum değerlerinden biri değildir.")
    if "const" in schema and value != schema["const"]:
        raise SchemaValidationError(f"{path} sabit şema değeriyle eşleşmiyor.")

    if expected == "object":
        properties = schema["properties"]
        unknown = set(value) - set(properties)
        if unknown:
            raise SchemaValidationError(f"{path} izin verilmeyen alanlar içeriyor: {sorted(unknown)}")
        missing = set(schema.get("required", [])) - set(value)
        if missing:
            raise SchemaValidationError(f"{path} zorunlu alanları eksik: {sorted(missing)}")
        _check_size(len(value), schema, "Properties", path)
        for key, item in value.items():
            validate_instance(item, properties[key], path=f"{path}.{key}")
    elif expected == "array":
        _check_size(len(value), schema, "Items", path)
        for index, item in enumerate(value):
            validate_instance(item, schema["items"], path=f"{path}[{index}]")
    elif expected == "string":
        _check_size(len(value), schema, "Length", path)
    elif expected in {"integer", "number"}:
        if "minimum" in schema and value < schema["minimum"]:
            raise SchemaValidationError(f"{path} minimum sınırının altında.")
        if "maximum" in schema and value > schema["maximum"]:
            raise SchemaValidationError(f"{path} maximum sınırının üstünde.")


def _check_size(size: int, schema: Mapping[str, Any], suffix: str, path: str) -> None:
    minimum = schema.get(f"min{suffix}")
    maximum = schema.get(f"max{suffix}")
    if minimum is not None and size < minimum:
        raise SchemaValidationError(f"{path} minimum uzunluk sınırının altında.")
    if maximum is not None and size > maximum:
        raise SchemaValidationError(f"{path} maksimum uzunluk sınırını aşıyor.")


def parse_and_validate(raw_text: str, schema: Mapping[str, Any]) -> Mapping[str, Any]:
    validate_schema_definition(schema)
    value = parse_json_object(raw_text)
    validate_instance(value, schema)
    return value
