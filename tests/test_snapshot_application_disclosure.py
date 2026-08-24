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


def test_snapshot_reference_fails_closed_when_snapshot_contract_has_blockers() -> None:
    invalid_chunk = _snapshot_chunk().model_copy(
        update={"approved_for_active_rag": True}
    )

    reference = SourceVerificationAgent().run(
        [SearchHit(chunk=invalid_chunk, score=1.0, matched_terms=["yol"])],
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
    assert any("yalnız retrieval ve kaynak izi" in item for item in draft.paragraphs)
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
