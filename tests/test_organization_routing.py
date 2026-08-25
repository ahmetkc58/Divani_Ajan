import json
from pathlib import Path

from karayol_agent.agents.routing import RoutingAgent
from karayol_agent.schemas import DocumentAnalysis, ExtractedField, FieldStatus


ROOT = Path(__file__).resolve().parents[1]
CATALOG_PATH = ROOT / "data" / "organization" / "kgm_units_2026-07-16.json"


def analysis(text: str, *, confidence: float = 0.90) -> DocumentAnalysis:
    return DocumentAnalysis(
        document_type="dis_evrak",
        confidence=confidence,
        summary=text,
        retrieval_evidence_text=text,
        fields={
            "konu": ExtractedField(
                value=text,
                status=FieldStatus.FROM_SOURCE,
            )
        },
        keywords=[],
    )


def test_catalog_is_versioned_closed_and_contains_no_personnel_fields() -> None:
    payload = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    records = payload["data"]
    ids = [record["unit_id"] for record in records]

    assert payload["organization_version"] == "2026-07-16"
    assert payload["contains_personnel_data"] is False
    assert len(ids) == len(set(ids))
    assert all("manager" not in record and "personnel" not in record for record in records)
    assert all(
        not record.get("parent_id") or record["parent_id"] in ids
        for record in records
    )


def test_topic_routes_only_to_units_from_the_chart_catalog() -> None:
    router = RoutingAgent(CATALOG_PATH)
    cases = {
        "Asfalt kaplamada derin çukur için yol bakım talebi": "ORKGM-YB-001",
        "Eksik trafik levhası ve bariyer bildirimi": "ORKGM-TG-001",
        "Köprü hasarı ve köprü onarımı talebi": "ORKGM-AF-001",
        "Kamulaştırma bedeli hakkında itiraz": "KGM-TAS-KAMU",
        "Personel atama ve kadro talebi": "KGM-PER-ATAMA",
        "Kurumsal yazılım API entegrasyonu talebi": "KGM-BT-YAZILIM",
    }
    allowed_ids = {unit.unit_id for unit in router.units}

    for text, expected in cases.items():
        result = router.run(analysis(text))
        assert result.unit_id == expected
        assert result.unit_id in allowed_ids
        assert result.organization_version == "2026-07-16"
        assert result.evidence


def test_unknown_and_ambiguous_documents_require_human_review() -> None:
    router = RoutingAgent(CATALOG_PATH)

    unknown = router.run(analysis("Toplantı daveti ve genel değerlendirme notu"))
    assert unknown.unit_id == "ORKGM-EB-001"
    assert unknown.routing_status == "needs_review"
    assert unknown.requires_human_review is True

    ambiguous = router.run(
        analysis("Asfalt yol bakım çalışması ile trafik levhası ve bariyer talebi")
    )
    assert ambiguous.requires_human_review is True
    assert ambiguous.score_margin < 0.20


def test_chart_only_region_match_never_bypasses_human_review() -> None:
    result = RoutingAgent(CATALOG_PATH).run(
        analysis("İstanbul sınırlarında genel bir karayolu başvurusu")
    )

    assert result.unit_id == "KGM-BOLGE-01"
    assert result.target_level == "regional"
    assert result.requires_human_review is True
    assert "yer:İstanbul" in result.evidence
