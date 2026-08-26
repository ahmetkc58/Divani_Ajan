from __future__ import annotations

import pytest

from karayol_agent.agents.compliance import ComplianceAgent
from karayol_agent.official_writing_rules import (
    REGULATION_ID,
    closing_matches_authority_relation,
    valid_official_date,
    valid_official_number,
)
from karayol_agent.schemas import (
    DraftPayload,
    ExtractedField,
    FieldStatus,
    TemplateDecision,
)


def _field(value: str | None) -> ExtractedField:
    return ExtractedField(value=value, status=FieldStatus.FROM_SOURCE)


def _decision() -> TemplateDecision:
    return TemplateDecision(
        document_type="ust_yazi",
        template_id="ust_yazi_v1",
        rationale="test",
        confidence=0.95,
    )


def _draft(**changes: object) -> DraftPayload:
    values: dict[str, object] = {
        "template_id": "ust_yazi_v1",
        "institution_name": _field("Karayolları Genel Müdürlüğü"),
        "date": _field("24.08.2026"),
        "number": _field("E-67915368-903.07.02-4752"),
        "subject": _field("Yol bakım çalışması"),
        "recipient": _field("Bölge Müdürlüğüne"),
        "paragraphs": [
            "Başvuru incelenmiş ve değerlendirme tamamlanmıştır.",
            "Gereğini rica ederim.",
        ],
        "signer": _field("Mehmet DEMİR"),
        "signer_title": _field("Şube Müdürü"),
        "authority_relation": "subordinate_internal",
        "closing": "Gereğini rica ederim.",
        "document_metadata": {
            "template_version": "1.0.0",
            "data_class": "test",
            "routing_unit_id": "UNIT-1",
            "official_writing_rules": REGULATION_ID,
        },
    }
    values.update(changes)
    return DraftPayload(**values)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("01.09.2019", True),
        ("10 Ekim 2019", True),
        ("2019-09-01", False),
        ("1/9/2019", False),
    ],
)
def test_date_rule_follows_article_12(value: str, expected: bool) -> None:
    assert valid_official_date(value) is expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("E-67915368-903.07.02-4752", True),
        ("Z-67915368-804.02-4757", True),
        ("2026/42", False),
        ("E-123-903-1", False),
    ],
)
def test_number_rule_follows_article_11(value: str, expected: bool) -> None:
    assert valid_official_number(value) is expected


@pytest.mark.parametrize(
    ("closing", "relation"),
    [
        ("Gereğini rica ederim.", "subordinate_internal"),
        ("Arz ederim.", "superior"),
        ("Arz ederim.", "same_level"),
        ("Arz ve rica ederim.", "mixed"),
        ("Bilgilerinize sunulur.", "citizen_or_external"),
    ],
)
def test_closing_rule_follows_article_16(closing: str, relation: str) -> None:
    assert closing_matches_authority_relation(closing, relation)


def test_compliance_is_source_traced_and_rejects_invalid_official_number() -> None:
    result = ComplianceAgent().run(
        _draft(number=_field("2026/42")),
        _decision(),
    )

    assert not result.passed
    assert result.rule_source_id == REGULATION_ID
    assert "RY-11" in result.applied_rule_ids
    assert any(error.startswith("[RY-11]") for error in result.errors)


def test_interest_and_legislation_references_are_not_conflated() -> None:
    result = ComplianceAgent().run(
        _draft(interest=["12.08.2026 tarihli ve E-12345678-903-42 sayılı yazı."]),
        _decision(),
    )

    assert result.passed
    assert "RY-15" in result.applied_rule_ids
    assert any("mevzuat/kural kaynağı" in warning for warning in result.warnings)


def test_unjustified_minimum_body_length_is_not_a_compliance_rule() -> None:
    result = ComplianceAgent().run(
        _draft(paragraphs=["Olur.", "Gereğini rica ederim."]),
        _decision(),
    )

    assert result.passed
    assert not any("çok kısa" in error for error in result.errors)
