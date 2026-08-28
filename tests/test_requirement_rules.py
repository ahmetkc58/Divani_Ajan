from pathlib import Path

from karayol_agent.agents.llm_roles import LLMAdjudicatorAgent
from karayol_agent.retrieval.requirement_rules import RequirementRuleRepository
from karayol_agent.schemas import DocumentAnalysis, DocumentLayout


ROOT = Path(__file__).resolve().parents[1]


def _analysis(
    *,
    general_type: str,
    operational_type: str = "genel_basvuru",
    subtype: str | None = None,
    text: str = "",
) -> DocumentAnalysis:
    return DocumentAnalysis(
        document_type=operational_type,
        general_document_type=general_type,
        document_subtype=subtype,
        confidence=0.9,
        summary=text or "Başvuru",
        retrieval_evidence_text=text or None,
        fields={},
    )


def _repository() -> RequirementRuleRepository:
    return RequirementRuleRepository(
        ROOT / "data" / "legal_requirements" / "catalog.json"
    )


def test_generic_request_selects_only_reviewed_petition_requirements() -> None:
    repository = _repository()

    rules = repository.select(
        _analysis(general_type="talep", operational_type="yol_bakim_talebi")
    )

    assert repository.warning is None
    assert {rule.field for rule in rules} == {"gonderen", "imza", "adres", "konu"}
    assert all(rule.source_id == "SRC-3071" for rule in rules)


def test_permit_rules_require_a_matching_subtype() -> None:
    repository = _repository()

    generic = repository.select(_analysis(general_type="izin"))
    crossing = repository.select(
        _analysis(
            general_type="izin",
            subtype="Geçiş Yolu Ön İzin Belgesi",
            text="Yol boyu tesis için geçiş yolu ön izin başvurusu",
        )
    )

    assert not any(rule.source_id == "SRC-KGM-GECIS-YOLU" for rule in generic)
    assert {
        rule.field for rule in crossing if rule.source_id == "SRC-KGM-GECIS-YOLU"
    } == {
        "sahiplik_belgesi",
        "vaziyet_plani",
        "belediye_sinir_yazisi",
    }
    conditional = next(
        rule for rule in crossing if rule.field == "belediye_sinir_yazisi"
    )
    assert conditional.applicability == "conditional"
    assert conditional.absence_is_missing is False


def test_detsis_display_type_does_not_hide_a_matching_legal_subtype() -> None:
    repository = _repository()

    rules = repository.select(
        _analysis(
            general_type="BAŞVURU/TALEP FORMU",
            operational_type="dilekce",
            subtype="Geçiş Yolu İzin Belgesi Talebi",
            text="Geçiş yolu izin belgesi talebi",
        )
    )

    assert {rule.field for rule in rules} >= {
        "gonderen",
        "imza",
        "adres",
        "konu",
        "sahiplik_belgesi",
        "vaziyet_plani",
        "belediye_sinir_yazisi",
    }


def test_machine_style_subtype_matches_human_readable_rule_terms() -> None:
    repository = _repository()

    rules = repository.select(
        _analysis(
            general_type="genel_basvuru",
            operational_type="genel_basvuru",
            subtype="gecis_yolu_izin_belgesi_talebi",
        )
    )

    assert {
        rule.field for rule in rules if rule.source_id == "SRC-KGM-GECIS-YOLU"
    } == {"sahiplik_belgesi", "vaziyet_plani", "belediye_sinir_yazisi"}


def test_natural_person_name_rule_is_not_applied_to_a_company_application() -> None:
    repository = _repository()

    rules = repository.select(
        _analysis(
            general_type="genel_basvuru",
            operational_type="genel_basvuru",
            subtype="gecis_yolu_izin_belgesi_talebi",
            text="Başvuru sahibi Örnek Lojistik A.Ş. tarafından sunulmuştur.",
        )
    )

    assert "3071-M4-AD-SOYAD" not in {rule.rule_id for rule in rules}
    assert "3071-M4-IMZA" in {rule.rule_id for rule in rules}


def test_curated_reference_flags_are_copied_from_their_catalog_source() -> None:
    """Katman B context: curated references are a small, human-reviewed set,
    so ``currentness_verified``/``legal_reliance_allowed`` must reflect each
    rule's own ``RequirementSource`` exactly — not a blanket True/True, and
    not the bulk ``competition_snapshot`` corpus's blanket False/False."""

    repository = _repository()

    # SRC-3071 (Dilekçe Kanunu): currentness_verified True AND
    # legal_reliance_allowed True.
    petition_rules = repository.select(
        _analysis(general_type="talep", operational_type="yol_bakim_talebi")
    )
    petition_references = repository.verified_references(petition_rules)
    assert petition_references
    assert all(reference.source_kind == "curated_requirement_rule" for reference in petition_references)
    assert all(reference.currentness_verified is True for reference in petition_references)
    assert all(reference.legal_reliance_allowed is True for reference in petition_references)

    # SRC-KGM-SIKAYET-FORMU: currentness_verified True but
    # legal_reliance_allowed False (a form/field rule, not a legal-basis
    # source) — the repository must not silently upgrade this to True.
    form_rules = [
        rule
        for rule in repository.select(
            _analysis(
                general_type="sikayet",
                subtype="Şikâyet / Talep Formu",
                text="Türkiye Acil Yol Rehabilitasyonu ve Yeniden Yapım Projesi",
            )
        )
        if rule.source_id == "SRC-KGM-SIKAYET-FORMU"
    ]
    assert form_rules
    form_references = repository.verified_references(form_rules)
    assert all(reference.source_kind == "curated_requirement_rule" for reference in form_references)
    assert all(reference.currentness_verified is True for reference in form_references)
    assert all(reference.legal_reliance_allowed is False for reference in form_references)


def test_rules_become_closed_verified_llm2_candidates() -> None:
    repository = _repository()
    rules = repository.select(_analysis(general_type="ust_yazi"))

    references = repository.verified_references(rules)
    payload = repository.payload(rules)

    assert rules
    assert all(reference.verified for reference in references)
    assert all(
        reference.evidence_channels == ["curated_requirement_catalog"]
        for reference in references
    )
    assert payload[0]["legal_reference_id"].startswith("REQ-")
    assert {item["field"] for item in payload} >= {
        "baslik",
        "sayi",
        "tarih",
        "konu",
        "muhatap",
        "metin",
        "imza",
    }


def test_official_form_advisory_fields_cannot_create_certain_missing_findings() -> None:
    repository = _repository()

    rules = repository.select(
        _analysis(
            general_type="sikayet",
            subtype="Şikâyet / Talep Formu",
            text="Türkiye Acil Yol Rehabilitasyonu ve Yeniden Yapım Projesi",
        )
    )

    form_rules = [rule for rule in rules if rule.source_id == "SRC-KGM-SIKAYET-FORMU"]
    assert form_rules
    assert all(rule.absence_is_missing is False for rule in form_rules)
    assert all(rule.severity == "warning" for rule in form_rules)

    references = repository.verified_references(form_rules)
    rule_payload = repository.payload(form_rules)
    date_rule = next(item for item in rule_payload if item["field"] == "tarih")
    date_reference = next(
        reference
        for reference in references
        if reference.chunk_id == date_rule["legal_reference_id"]
    )
    validation = LLMAdjudicatorAgent._validate_payload(
        {
            "accepted_reference_ids": [date_reference.chunk_id],
            "requirements": [
                {
                    "field": "tarih",
                    "requirement": date_rule["requirement"],
                    "status": "missing",
                    "document_evidence_ids": [],
                    "legal_reference_ids": [date_reference.chunk_id],
                    "legal_evidence": date_reference.excerpt,
                    "confidence": 0.9,
                }
            ],
            "missing_fields": ["tarih"],
            "unsupported_claims": [],
        },
        verified_references=[date_reference],
        document_layout=DocumentLayout(),
        curated_requirement_rules=rule_payload,
    )
    assert validation.requirements == ()
    assert any("kesin eksik" in warning for warning in validation.server_warnings)
