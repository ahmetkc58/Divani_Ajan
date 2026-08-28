from __future__ import annotations

from pathlib import Path

import pytest

from karayol_agent.agents.compliance import ComplianceAgent
from karayol_agent.config import Settings
from karayol_agent.official_writing_rules import (
    REGULATION_ID,
    closing_matches_authority_relation,
    valid_official_date,
    valid_official_number,
)
from karayol_agent.orchestrator import EvrakOrchestrator
from karayol_agent.schemas import (
    DraftPayload,
    ExtractedField,
    FieldStatus,
    ProcessState,
    ProcessStatus,
    TemplateDecision,
)


ROOT = Path(__file__).resolve().parents[1]


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


# --- RY-11 (DETSİS/standard file plan "sayı" format) regression coverage ---
#
# Today's commit tightened RY-11 so that a plain value like "2026/42" is
# rejected; only the DETSİS/standard-file-plan shape
# (ortam kodu-DETSİS-standart dosya planı-kayıt numarası, e.g.
# "E-67915368-903.07.02-4752") is accepted. This is treated as an intentional
# stricter rule (see task context), so these tests lock in both sides of the
# boundary plus the "graceful block, not a crash" behaviour when it fires.


def test_valid_detsis_formatted_number_passes_with_no_ry11_finding() -> None:
    result = ComplianceAgent().run(
        _draft(number=_field("E-67915368-903.07.02-4752")),
        _decision(),
    )

    assert result.passed is True
    assert "RY-11" in result.applied_rule_ids
    assert not any(error.startswith("[RY-11]") for error in result.errors)
    assert not any(warning.startswith("[RY-11]") for warning in result.warnings)


def test_invalid_official_number_blocks_finalization_gracefully_not_a_crash(
    tmp_path: Path,
) -> None:
    """RY-11 rejection must leave the process in a controlled, actionable
    state via ``EvrakOrchestrator._finalize_user_message`` — never an
    unhandled exception and never a silent/approved completion."""

    orchestrator = EvrakOrchestrator(
        Settings(
            project_root=ROOT,
            data_dir=ROOT / "data",
            templates_dir=ROOT / "templates",
            output_dir=tmp_path / "output",
            runtime_dir=tmp_path / "runtime",
        )
    )
    decision = _decision()
    invalid_draft = _draft(number=_field("2026/42"))
    invalid_compliance = ComplianceAgent().run(invalid_draft, decision)
    assert invalid_compliance.passed is False
    assert any(
        error.startswith("[RY-11]")
        and "E-67915368-903.07.02-4752" in error
        for error in invalid_compliance.errors
    )

    state = ProcessState(
        document_id="EVR-TEST-RY11",
        draft=invalid_draft,
        compliance=invalid_compliance,
    )

    # Must not raise.
    orchestrator._finalize_user_message(state)

    assert state.status == ProcessStatus.ERROR
    assert state.possible_actions == ["taslagi_duzenle", "reddet"]
    assert state.pending_actions
    assert any("RY-11" in action for action in state.pending_actions)
    assert state.next_step
