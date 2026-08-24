import pytest

from karayol_agent.agents.compliance import ComplianceAgent
from karayol_agent.schemas import DraftPayload, ExtractedField, FieldStatus, TemplateDecision


VALID = {
    "template_id": "ust_yazi_v1",
    "institution_name": ExtractedField(value="Karayolları Genel Müdürlüğü", status=FieldStatus.GENERATED),
    "date": ExtractedField(value="24.08.2026", status=FieldStatus.FROM_SOURCE),
    "number": ExtractedField(value="2026/42", status=FieldStatus.FROM_SOURCE),
    "subject": ExtractedField(value="Yol bakım çalışması", status=FieldStatus.FROM_SOURCE),
    "recipient": ExtractedField(value="Bölge Müdürlüğüne", status=FieldStatus.GENERATED),
    "paragraphs": ["Başvurunuz incelenmiş ve gerekli değerlendirme yapılmıştır."],
    "signer": ExtractedField(value="Mehmet Demir", status=FieldStatus.FROM_SOURCE),
    "signer_title": ExtractedField(value="Şube Müdürü", status=FieldStatus.FROM_SOURCE),
    "closing": ExtractedField(value="Gereğini rica ederim.", status=FieldStatus.GENERATED),
}


def make_draft(**changes: object) -> DraftPayload:
    values = {**VALID, **changes}
    return DraftPayload(**values)


def make_decision(document_type: str = "ust_yazi") -> TemplateDecision:
    return TemplateDecision(
        document_type=document_type,
        template_id={
            "ust_yazi": "ust_yazi_v1",
            "cevap_yazisi": "cevap_yazisi_v1",
            "bilgilendirme_yazisi": "bilgilendirme_yazisi_v1",
        }.get(document_type, "eksik_bilgi_talebi_v1"),
        rationale="test",
        confidence=0.95,
        user_approval_required=True,
    )


@pytest.mark.parametrize(
    ("document_type", "closing"),
    [
        ("ust_yazi", "Gereğini rica ederim."),
        ("cevap_yazisi", "Bilgilerinize arz ederim."),
        ("bilgilendirme_yazisi", "Bilgilerinize arz ve rica ederim."),
        ("eksik_bilgi_talebi", "Gereğini rica ederim."),
    ],
)
def test_valid_closing_rules_pass(document_type: str, closing: str) -> None:
    draft = make_draft(
        template_id=make_decision(document_type).template_id,
        closing=ExtractedField(value=closing, status=FieldStatus.GENERATED),
    )
    result = ComplianceAgent().run(draft, make_decision(document_type))
    assert result.passed


@pytest.mark.parametrize(
    "change",
    [
        {"institution_name": ExtractedField(value=None, status=FieldStatus.USER_REQUIRED)},
        {"subject": ExtractedField(value=None, status=FieldStatus.USER_REQUIRED)},
        {"recipient": ExtractedField(value=None, status=FieldStatus.USER_REQUIRED)},
        {"recipient": ExtractedField(value="Bölge Müdürlüğü", status=FieldStatus.FROM_SOURCE)},
        {"date": ExtractedField(value=None, status=FieldStatus.USER_REQUIRED)},
        {"date": ExtractedField(value="2026/08/24", status=FieldStatus.FROM_SOURCE)},
        {"number": ExtractedField(value=None, status=FieldStatus.USER_REQUIRED)},
        {"number": ExtractedField(value="2026 42", status=FieldStatus.FROM_SOURCE)},
        {"closing": ExtractedField(value=None, status=FieldStatus.USER_REQUIRED)},
        {"closing": ExtractedField(value="Gereğini arz ederim.", status=FieldStatus.GENERATED)},
        {"signer": ExtractedField(value=None, status=FieldStatus.USER_REQUIRED)},
        {"signer_title": ExtractedField(value=None, status=FieldStatus.USER_REQUIRED)},
        {"paragraphs": []},
        {"references_section": ["İlgi: 1"], "references": []},
        {"attachments": [""]},
        {"distribution": [""]},
        {"template_id": "bilinmeyen_v1"},
        {"template_id": "cevap_yazisi_v1"},
        {"missing_fields": ["sayi"]},
        {"paragraphs": ["çok kısa"]},
    ],
)
def test_invalid_or_incomplete_drafts_fail_closed(change: dict[str, object]) -> None:
    result = ComplianceAgent().run(make_draft(**change), make_decision())
    assert not result.passed
    assert result.errors


def test_missing_references_is_warning_only() -> None:
    result = ComplianceAgent().run(make_draft(), make_decision())
    assert result.passed
    assert result.warnings


def test_attachments_and_distribution_with_values_are_allowed() -> None:
    result = ComplianceAgent().run(
        make_draft(attachments=["Ek-1.pdf"], distribution=["Bölge Müdürlüğü"]),
        make_decision(),
    )
    assert result.passed
