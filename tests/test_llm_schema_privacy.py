from __future__ import annotations

import pytest

from karayol_agent.llm import DataClassification
from karayol_agent.llm.privacy import DataPolicyError, ExternalDataGuard
from karayol_agent.llm.schema import (
    SchemaDefinitionError,
    SchemaValidationError,
    parse_and_validate,
    parse_json_object,
    validate_schema_definition,
)


NESTED_SCHEMA = {
    "type": "object",
    "properties": {
        "sender": {"type": ["string", "null"], "maxLength": 80},
        "missing_fields": {
            "type": "array",
            "items": {"type": "string", "enum": ["sayi", "tarih", "imzalayan"]},
            "maxItems": 3,
        },
    },
    "required": ["sender", "missing_fields"],
    "additionalProperties": False,
}


def test_closed_nested_schema_accepts_valid_nullable_output() -> None:
    output = parse_and_validate(
        '{"sender":null,"missing_fields":["sayi","imzalayan"]}',
        NESTED_SCHEMA,
    )
    assert output["sender"] is None


def test_duplicate_json_key_is_rejected() -> None:
    with pytest.raises(SchemaValidationError, match="Tekrarlanan"):
        parse_json_object('{"sender":"A","sender":"B"}')


@pytest.mark.parametrize("raw", ["[]", "NaN", '{"sender": NaN}', "```json\n{}\n```"])
def test_non_object_or_non_strict_json_is_rejected(raw: str) -> None:
    with pytest.raises(SchemaValidationError):
        parse_json_object(raw)


def test_nested_object_must_be_closed() -> None:
    schema = {
        "type": "object",
        "properties": {
            "sender": {
                "type": "object",
                "properties": {"name": {"type": "string"}},
                "required": ["name"],
            }
        },
        "required": ["sender"],
        "additionalProperties": False,
    }
    with pytest.raises(SchemaDefinitionError, match="additionalProperties"):
        validate_schema_definition(schema)


@pytest.mark.parametrize(
    "schema",
    [
        {"$ref": "#/$defs/x", "type": "object"},
        {
            "type": "object",
            "properties": {},
            "required": ["unknown"],
            "additionalProperties": False,
        },
        {
            "type": "object",
            "properties": {"x": {"type": "string", "maxLength": "ten"}},
            "required": [],
            "additionalProperties": False,
        },
        {
            "type": "object",
            "properties": {"x": {"type": "string", "example": object()}},
            "required": [],
            "additionalProperties": False,
        },
        {
            "type": "object",
            "properties": {"x": {"type": "string", "enum": [42]}},
            "required": [],
            "additionalProperties": False,
        },
    ],
)
def test_unsafe_or_ambiguous_schema_definitions_are_rejected(schema: object) -> None:
    with pytest.raises(SchemaDefinitionError):
        validate_schema_definition(schema)  # type: ignore[arg-type]


def test_output_bounds_and_unknown_fields_are_enforced() -> None:
    with pytest.raises(SchemaValidationError, match="maksimum"):
        parse_and_validate(
            '{"sender":"A","missing_fields":["sayi","tarih","imzalayan","sayi"]}',
            NESTED_SCHEMA,
        )
    with pytest.raises(SchemaValidationError, match="izin verilmeyen"):
        parse_and_validate(
            '{"sender":"A","missing_fields":[],"invented":"x"}',
            NESTED_SCHEMA,
        )


def test_privacy_guard_redacts_turkish_identifiers_and_secrets_recursively() -> None:
    values = {
        "sender": {
            "tckn": "10000000146",
            "email": "vatandas@example.com",
            "phone": "+90 532 123 45 67",
            "iban": "TR330006100519786457841326",
            # Assemble the realistic-looking fixture at runtime so repository
            # secret scanners do not mistake test data for a live credential.
            "token": "AI" + "za" + "1234567890abcdefghijklmnop",
        }
    }

    result = ExternalDataGuard().prepare(
        values,
        classification=DataClassification.REDACTED,
        allow_automatic_redaction=True,
    )

    serialized = repr(result.payload)
    for sensitive in values["sender"].values():
        assert sensitive not in serialized
    assert result.redacted is True
    assert {finding.kind for finding in result.findings} == {
        "TCKN",
        "EMAIL",
        "PHONE",
        "IBAN",
        "SECRET_FIELD",
    }
    assert all("10000000146" not in finding.masked_sample for finding in result.findings)


def test_privacy_guard_rejects_restricted_data_even_if_no_pattern_matches() -> None:
    with pytest.raises(DataPolicyError, match="Kısıtlı"):
        ExternalDataGuard().prepare(
            {"document_text": "Gerçek kurum evrakı"},
            classification=DataClassification.RESTRICTED,
            allow_automatic_redaction=True,
        )


def test_privacy_guard_allows_restricted_data_only_for_local_llm() -> None:
    email = "yerel.kullanici@example.gov.tr"
    result = ExternalDataGuard().prepare(
        {"document_text": f"Gönderen: {email}"},
        classification=DataClassification.RESTRICTED,
        allow_automatic_redaction=False,
        allow_restricted_local=True,
    )

    assert result.payload["document_text"] == f"Gönderen: {email}"
    assert result.redacted is False


def test_privacy_guard_rejects_non_json_values() -> None:
    with pytest.raises(DataPolicyError, match="JSON-uyumlu"):
        ExternalDataGuard().prepare(
            {"bad": object()},
            classification=DataClassification.SYNTHETIC,
            allow_automatic_redaction=True,
        )


def test_privacy_guard_does_not_leak_sensitive_mapping_keys() -> None:
    email = "sender@example.com"
    result = ExternalDataGuard().prepare(
        {email: "value"},
        classification=DataClassification.REDACTED,
        allow_automatic_redaction=True,
    )
    assert email not in result.payload
    assert "[KİŞİSEL_VERİ:EMAIL]" in result.payload


def test_privacy_guard_redacts_plain_secret_by_field_name() -> None:
    secret = "provider-key-without-known-prefix"
    result = ExternalDataGuard().prepare(
        {"api_key": secret},
        classification=DataClassification.SYNTHETIC,
        allow_automatic_redaction=True,
    )
    assert secret not in repr(result.payload)
    assert result.payload["api_key"] == "[GİZLİ:SECRET_FIELD]"


def test_synthetic_attestation_preserves_fake_pii_but_not_secrets() -> None:
    fake_email = "zeynep.kaya@example.test"
    result = ExternalDataGuard().prepare(
        {"email": fake_email, "password": "synthetic-but-secret"},
        classification=DataClassification.SYNTHETIC,
        allow_automatic_redaction=True,
    )
    assert result.payload["email"] == fake_email
    assert result.payload["password"] == "[GİZLİ:SECRET_FIELD]"
