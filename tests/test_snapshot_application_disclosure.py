from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

import karayol_agent.api as api_module
from karayol_agent.agents.compliance import ComplianceAgent
from karayol_agent.agents.drafting import DraftingAgent
from karayol_agent.agents.legislation import SourceVerificationAgent
from karayol_agent.config import Settings
from karayol_agent.orchestrator import EvrakOrchestrator
from karayol_agent.retrieval.bm25 import BM25Index
from karayol_agent.retrieval.relevance import AnalysisAwareDeterministicReranker
from karayol_agent.retrieval.contracts import (
    COMPETITION_SNAPSHOT_NOTICE,
    COMPETITION_SNAPSHOT_STATUS,
    CorpusMode,
    competition_snapshot_chunk_blockers,
)
from karayol_agent.schemas import (
    DocumentAnalysis,
    ExtractedField,
    FieldStatus,
    LegislationChunk,
    RoutingRecommendation,
    SearchHit,
    TemplateDecision,
    VerifiedReference,
)


ROOT = Path(__file__).resolve().parents[1]


def _analysis() -> DocumentAnalysis:
    return DocumentAnalysis(
        document_type="yol_bakim_talebi",
        confidence=0.94,
        summary="Yol bakım talebi",
        fields={
            "konu": ExtractedField(
                value="Yol bakım talebi",
                status=FieldStatus.FROM_SOURCE,
            ),
            "talep": ExtractedField(
                value="Bozulan yolun onarılması",
                status=FieldStatus.FROM_SOURCE,
            ),
        },
        keywords=["yol", "bakım"],
    )


def _snapshot_chunk() -> LegislationChunk:
    return LegislationChunk(
        chunk_id="SNAPSHOT-DOC-madde-1-p1",
        document_id="SNAPSHOT-DOC",
        title="Sabit Yarışma Kaynağı",
        section="Madde 1",
        article="Madde 1",
        text="Yol bakım hizmetinin yürütülmesine ilişkin sabit kaynak metni.",
        source="data/sources/snapshot-document.pdf",
        source_sha256="a" * 64,
        source_kind=CorpusMode.COMPETITION_SNAPSHOT.value,
        page=1,
        page_end=1,
        document_type="regulation",
        domain="official_writing",
        validity_status="needs_verification",
        approved_for_active_rag=False,
        ocr_status="text_layer_available",
        context_text="Sabit Yarışma Kaynağı > Madde 1",
        status=COMPETITION_SNAPSHOT_STATUS,
    )


def _snapshot_reference() -> VerifiedReference:
    chunk = _snapshot_chunk()
    assert competition_snapshot_chunk_blockers(chunk) == []
    return SourceVerificationAgent().run(
        [
            SearchHit(
                chunk=chunk,
                score=1.0,
                matched_terms=["yol", "bakım"],
                relevance_score=1.0,
                relevance_accepted=True,
                relevance_profile="road_surface_maintenance_v1",
                relevance_basis="query_and_text",
            )
        ],
        _analysis(),
    )[0]


def _decision() -> TemplateDecision:
    return TemplateDecision(
        document_type="ust_yazi",
        template_id="ust_yazi_v1",
        rationale="Test",
        confidence=0.9,
    )


def _routing() -> RoutingRecommendation:
    return RoutingRecommendation(
        unit_id="UNIT-1",
        unit_name="Yol Bakım Birimi",
        hierarchy="Genel Müdürlük > Birim",
        rationale="Test",
        score=0.9,
    )


def test_snapshot_reference_is_accepted_only_for_retrieval_and_provenance() -> None:
    reference = _snapshot_reference()

    assert reference.verified is True
    assert reference.corpus_mode == CorpusMode.COMPETITION_SNAPSHOT.value
    assert reference.currentness_verified is False
    assert reference.legal_reliance_allowed is False
    assert reference.usage_notice == COMPETITION_SNAPSHOT_NOTICE
    assert COMPETITION_SNAPSHOT_NOTICE in reference.verification_note

    restored = VerifiedReference.model_validate_json(reference.model_dump_json())
    assert restored.model_dump() == reference.model_dump()


def test_snapshot_reference_without_relevance_decision_fails_closed() -> None:
    reference = SourceVerificationAgent().run(
        [
            SearchHit(
                chunk=_snapshot_chunk(),
                score=1.0,
                matched_terms=["yol", "bakım"],
            )
        ],
        _analysis(),
    )[0]

    assert reference.verified is False
    assert "alaka kapısından geçmedi" in reference.verification_note


def test_snapshot_reference_fails_closed_when_snapshot_contract_has_blockers() -> None:
    invalid_chunk = _snapshot_chunk().model_copy(
        update={"approved_for_active_rag": True}
    )

    reference = SourceVerificationAgent().run(
        [
            SearchHit(
                chunk=invalid_chunk,
                score=1.0,
                matched_terms=["yol"],
                relevance_score=1.0,
                relevance_accepted=True,
                relevance_profile="road_surface_maintenance_v1",
                relevance_basis="query_and_text",
            )
        ],
        _analysis(),
    )[0]

    assert reference.verified is False
    assert reference.corpus_mode == CorpusMode.COMPETITION_SNAPSHOT.value
    assert reference.currentness_verified is False
    assert reference.legal_reliance_allowed is False
    assert reference.usage_notice == COMPETITION_SNAPSHOT_NOTICE
    assert "public_active_rag_onayi_snapshotta_yasak" in reference.verification_note


def test_public_and_synthetic_references_persist_distinct_disclosures() -> None:
    public_chunk = _snapshot_chunk().model_copy(
        update={
            "chunk_id": "PUBLIC-DOC-madde-1-p1",
            "document_id": "PUBLIC-DOC",
            "source_kind": "public_legislation",
            "source_url": "https://example.test/public-document",
            "validity_status": "verified",
            "approved_for_active_rag": True,
            "status": "verified",
        }
    )
    synthetic_chunk = _snapshot_chunk().model_copy(
        update={
            "chunk_id": "SYNTHETIC-DOC-madde-1-p1",
            "document_id": "SYNTHETIC-DOC",
            "source_kind": "synthetic",
            "source_sha256": None,
            "page": None,
            "page_end": None,
            "domain": "unknown",
            "context_text": None,
            "ocr_status": "not_inspected",
            "status": "sentetik_demo_kurali",
        }
    )

    public_reference = SourceVerificationAgent().run(
        [SearchHit(chunk=public_chunk, score=1.0, matched_terms=["yol"])],
        _analysis(),
    )[0]
    synthetic_reference = SourceVerificationAgent().run(
        [SearchHit(chunk=synthetic_chunk, score=1.0, matched_terms=["yol"])],
        _analysis(),
    )[0]

    assert public_reference.verified is True
    assert public_reference.corpus_mode == CorpusMode.VERIFIED_PUBLIC.value
    assert public_reference.currentness_verified is True
    assert public_reference.legal_reliance_allowed is True
    assert public_reference.usage_notice is None
    assert synthetic_reference.verified is True
    assert synthetic_reference.corpus_mode == CorpusMode.TRUSTED_SYNTHETIC.value
    assert synthetic_reference.currentness_verified is False
    assert synthetic_reference.legal_reliance_allowed is False


def test_snapshot_notice_is_in_draft_and_enforced_by_compliance() -> None:
    reference = _snapshot_reference()
    draft = DraftingAgent().run(
        _analysis(),
        _decision(),
        _routing(),
        [reference],
    )

    assert draft.references == [reference]
    assert COMPETITION_SNAPSHOT_NOTICE in draft.paragraphs
    assert all(reference.title not in item for item in draft.paragraphs)
    assert all("doğrulanan şu kaynaklar" not in item for item in draft.paragraphs)

    compliant = ComplianceAgent().run(draft, _decision())
    assert compliant.passed is True
    assert COMPETITION_SNAPSHOT_NOTICE in compliant.warnings

    unsafe_draft = draft.model_copy(
        update={
            "paragraphs": [
                paragraph
                for paragraph in draft.paragraphs
                if paragraph != COMPETITION_SNAPSHOT_NOTICE
            ]
        }
    )
    rejected = ComplianceAgent().run(unsafe_draft, _decision())
    assert rejected.passed is False
    assert any("zorunlu güncellik/yürürlük uyarısı" in item for item in rejected.errors)


def test_snapshot_notice_is_preserved_in_missing_information_draft() -> None:
    reference = _snapshot_reference()
    analysis = _analysis().model_copy(update={"missing_fields": ["gonderen"]})
    decision = TemplateDecision(
        document_type="eksik_bilgi_talebi",
        template_id="eksik_bilgi_talebi_v1",
        rationale="Eksik alan testi",
        confidence=0.95,
    )

    draft = DraftingAgent().run(analysis, decision, _routing(), [reference])
    compliance = ComplianceAgent().run(draft, decision)

    assert COMPETITION_SNAPSHOT_NOTICE in draft.paragraphs
    assert compliance.passed is True
    assert compliance.errors == []


def test_health_labels_snapshot_explicitly_instead_of_synthetic(
    monkeypatch, tmp_path: Path
) -> None:
    app_settings = Settings(
        project_root=ROOT,
        data_dir=ROOT / "data",
        templates_dir=ROOT / "templates",
        output_dir=tmp_path / "output",
        runtime_dir=tmp_path / "runtime",
    )
    snapshot_orchestrator = EvrakOrchestrator(app_settings)
    snapshot_orchestrator.index = BM25Index([_snapshot_chunk()])
    monkeypatch.setattr(api_module, "orchestrator", snapshot_orchestrator)

    health = TestClient(api_module.app).get("/health")

    assert health.status_code == 200
    payload = health.json()
    assert payload["data_mode"] == "competition_snapshot"
    assert payload["corpus_mode"] == CorpusMode.COMPETITION_SNAPSHOT.value
    assert payload["corpus_contract_valid"] is True
    assert payload["currentness_verified"] is False
    assert payload["legal_reliance_allowed"] is False
    assert payload["usage_notice"] == COMPETITION_SNAPSHOT_NOTICE


def test_snapshot_bm25_mode_keeps_relevance_gate_without_qdrant(
    tmp_path: Path,
) -> None:
    app_settings = Settings(
        project_root=ROOT,
        data_dir=ROOT / "data",
        templates_dir=ROOT / "templates",
        output_dir=tmp_path / "output",
        runtime_dir=tmp_path / "runtime",
        retrieval_mode="bm25",
        corpus_mode=CorpusMode.COMPETITION_SNAPSHOT.value,
        competition_snapshot_path=(
            ROOT / "data" / "processed" / "competition_snapshot.json"
        ),
    )

    orchestrator = EvrakOrchestrator(app_settings)

    assert isinstance(
        orchestrator.retriever,
        AnalysisAwareDeterministicReranker,
    )
    assert orchestrator.retriever.retrieval_mode == "bm25"
    readiness = orchestrator.readiness()
    assert readiness["ready"] is True
    assert readiness["retrieval_mode"] == "bm25"
    assert readiness["corpus_mode"] == CorpusMode.COMPETITION_SNAPSHOT.value

    positive = orchestrator.process_text(
        "Konu: Asfalt yol bakım talebi\n"
        "Konum: Örnek yol\n"
        "Yol yüzeyindeki çukurların onarılmasını talep ediyorum."
    )
    assert positive.search_hits
    assert positive.retrieval_diagnostics is not None
    assert positive.retrieval_diagnostics.relevance_query_supported is True
    assert positive.retrieval_diagnostics.relevance_candidate_top_k == 40
    assert all(hit.relevance_accepted is True for hit in positive.search_hits)

    negative = orchestrator.process_text(
        "Konu: Yol bakım ve asfalt çukuru\n"
        "Çukura girince jantım kırıldı; tazminat ve değer kaybı istiyorum."
    )
    assert negative.search_hits == []
    assert negative.verified_references == []
    assert negative.retrieval_diagnostics is not None
    assert negative.retrieval_diagnostics.relevance_query_supported is False
    assert negative.retrieval_diagnostics.relevance_abstained is True
