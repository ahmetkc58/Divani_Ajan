from __future__ import annotations

import json
from pathlib import Path

import pytest

from karayol_agent.agents.legislation import (
    LegislationResearchAgent,
    SourceVerificationAgent,
)
from karayol_agent.config import Settings
from karayol_agent.orchestrator import EvrakOrchestrator
from karayol_agent.retrieval.bm25 import BM25Index
from karayol_agent.retrieval.hybrid import (
    ChannelContribution,
    DenseRetrievalWarning,
    HybridRetriever,
    HybridRetrievalDiagnostics,
    HybridSearchHit,
    HybridSearchResponse,
)
from karayol_agent.retrieval.runtime import AnalysisAwareHybridRetriever
from karayol_agent.schemas import (
    DocumentAnalysis,
    ExtractedField,
    FieldStatus,
    LegislationChunk,
    ProcessState,
    RetrievalDiagnostics,
    SearchHit,
)


ROOT = Path(__file__).resolve().parents[1]


def _analysis() -> DocumentAnalysis:
    return DocumentAnalysis(
        document_type="yol_bakim_talebi",
        confidence=0.95,
        summary="Asfalt bozulması için yol bakım talebi",
        fields={
            "konu": ExtractedField(
                value="D-100 asfalt bozulması",
                status=FieldStatus.FROM_SOURCE,
            ),
            "talep": ExtractedField(
                value="Yolun onarılması",
                status=FieldStatus.FROM_SOURCE,
            ),
        },
        keywords=["asfalt", "bakım"],
    )


def _chunk(
    chunk_id: str,
    *,
    public: bool = False,
    approved: bool = True,
) -> LegislationChunk:
    common = {
        "chunk_id": chunk_id,
        "document_id": "TEST-DOC",
        "title": f"Test kaynağı {chunk_id}",
        "section": "Madde 1",
        "article": "Madde 1",
        "text": "Yol bakım ve asfalt onarımı hakkında doğrulanabilir hüküm.",
        "source": "test.pdf",
    }
    if public:
        return LegislationChunk(
            **common,
            source_kind="public_legislation",
            source_url=f"https://example.test/mevzuat/{chunk_id}",
            source_sha256="a" * 64,
            page=1,
            page_end=1,
            validity_status="verified",
            approved_for_active_rag=approved,
            ocr_status="text_layer_available",
            domain="kgm_infrastructure",
            context_text=f"Test kaynağı {chunk_id} > Madde 1",
            status="verified",
        )
    return LegislationChunk(
        **common,
        source_kind="synthetic",
        status="sentetik_demo_kurali",
    )


def _active_envelope(chunk: LegislationChunk) -> dict[str, object]:
    return {
        "schema_version": "2.0",
        "dataset_name": "active_public_legislation",
        "generated_at": "2026-08-24T12:30:00+03:00",
        "approved_for_active_rag": True,
        "document_count": 1,
        "chunk_count": 1,
        "documents": [
            {
                "document_id": chunk.document_id,
                "source_url": chunk.source_url,
                "source_sha256": chunk.source_sha256,
                "chunk_count": 1,
                "reviewed_by": "Hukuk Uzmanı",
                "reviewed_at": "2026-08-24T12:00:00+03:00",
            }
        ],
        "data": [chunk.model_dump(mode="json")],
    }


def _dense_hit(chunk_id: str = "DENSE-ACTIVE") -> HybridSearchHit:
    return HybridSearchHit(
        chunk=_chunk(chunk_id, public=True),
        score=1 / 61,
        channel_contributions=[
            ChannelContribution(
                channel="dense",
                rank=1,
                raw_score=0.91,
                rrf_contribution=1 / 61,
            )
        ],
    )


def _hybrid_response(hit: HybridSearchHit) -> HybridSearchResponse:
    return HybridSearchResponse(
        hits=[hit],
        diagnostics=HybridRetrievalDiagnostics(
            dense_status="used",
            fallback_used=False,
            lexical_candidate_count=0,
            dense_candidate_count=1,
            fused_candidate_count=1,
            channel_top_n=20,
            rrf_k=60,
        ),
    )


class FakeRuntimeAnalysisRetriever:
    retrieval_mode = "hybrid"

    def __init__(self, hit: HybridSearchHit) -> None:
        self.hit = hit
        self.received: DocumentAnalysis | None = None

    def bind(self, analysis: DocumentAnalysis) -> object:
        return self

    def search_with_diagnostics(
        self, analysis: DocumentAnalysis, top_k: int = 5
    ) -> HybridSearchResponse:
        self.received = analysis
        return _hybrid_response(self.hit)

    def search(self, query: str, top_k: int = 5) -> list[SearchHit]:
        raise AssertionError("Tanılı analysis araması varken düz search çağrılmamalı")


def test_research_agent_uses_runtime_analysis_search_with_diagnostics() -> None:
    retriever = FakeRuntimeAnalysisRetriever(_dense_hit())

    result = LegislationResearchAgent(retriever).run_with_diagnostics(_analysis())

    assert retriever.received is not None
    assert retriever.received.document_type == "yol_bakim_talebi"
    assert result.diagnostics.mode == "hybrid"
    assert result.diagnostics.dense_status == "used"
    assert result.hits[0].channel_contributions[0].channel == "dense"


def test_dense_only_evidence_requires_channel_and_complete_source_trust() -> None:
    contribution = ChannelContribution(
        channel="dense",
        rank=1,
        raw_score=0.88,
        rrf_contribution=1 / 61,
    )
    hits = [
        SearchHit(
            chunk=_chunk("ACTIVE", public=True),
            score=1.0,
            channel_contributions=[contribution],
        ),
        SearchHit(
            chunk=_chunk("INACTIVE", public=True, approved=False),
            score=0.9,
            channel_contributions=[contribution.model_copy(update={"rank": 2})],
        ),
        SearchHit(chunk=_chunk("NO-CHANNEL", public=True), score=0.8),
    ]

    references = SourceVerificationAgent().run(hits, _analysis())

    assert references[0].verified is True
    assert references[0].evidence_channels == ["dense"]
    assert references[0].channel_contributions[0].raw_score == 0.88
    assert references[1].verified is False
    assert "aktif_rag_onayi_yok" in references[1].verification_note
    assert references[2].verified is False


def test_dense_only_negative_similarity_is_not_verified_legal_evidence() -> None:
    hit = SearchHit(
        chunk=_chunk("DENSE-IRRELEVANT", public=True),
        score=1 / 61,
        channel_contributions=[
            ChannelContribution(
                channel="dense",
                rank=1,
                raw_score=-0.99,
                rrf_contribution=1 / 61,
            )
        ],
    )

    reference = SourceVerificationAgent(min_retrieval_score=0.20).run(
        [hit],
        _analysis(),
    )[0]

    assert reference.score == 1.0
    assert reference.verified is False
    assert "Dense ham benzerlik skoru" in reference.verification_note
    assert "esik=0.2000" in reference.verification_note


def test_plain_bm25_synthetic_behavior_and_diagnostics_remain_compatible() -> None:
    agent = LegislationResearchAgent(BM25Index([_chunk("BM25")]), top_k=5)

    hits = agent.run(_analysis())
    result = agent.run_with_diagnostics(_analysis())
    references = SourceVerificationAgent().run(hits, _analysis())

    assert [hit.chunk.chunk_id for hit in hits] == ["BM25"]
    assert result.diagnostics.mode == "bm25"
    assert result.diagnostics.dense_status == "not_requested"
    assert references[0].verified is True
    assert references[0].evidence_channels == ["lexical"]


def test_process_state_round_trip_preserves_channel_evidence_and_diagnostics() -> None:
    state = ProcessState(
        document_id="EVR-TEST",
        search_hits=[_dense_hit()],
        retrieval_diagnostics=RetrievalDiagnostics(
            mode="hybrid",
            dense_status="used",
            lexical_candidate_count=0,
            dense_candidate_count=1,
            fused_candidate_count=1,
            channel_top_n=20,
            rrf_k=60,
        ),
    )

    restored = ProcessState.model_validate_json(state.model_dump_json())

    assert restored.search_hits[0].fusion_method == "rrf"
    assert restored.search_hits[0].channel_contributions[0].channel == "dense"
    assert restored.retrieval_diagnostics is not None
    assert restored.retrieval_diagnostics.dense_status == "used"


class FakeSearchForAnalysisRetriever:
    retrieval_mode = "hybrid"

    def __init__(self, hit: HybridSearchHit) -> None:
        self.hit = hit
        self.calls = 0

    def search_for_analysis(
        self,
        query: str,
        analysis: DocumentAnalysis,
        top_k: int = 5,
    ) -> HybridSearchResponse:
        self.calls += 1
        return _hybrid_response(self.hit)

    def search(self, query: str, top_k: int = 5) -> list[SearchHit]:
        raise AssertionError("search_for_analysis varken düz search çağrılmamalı")


def test_orchestrator_persists_hybrid_diagnostics_and_dense_evidence(
    tmp_path: Path,
) -> None:
    fake_retriever = FakeSearchForAnalysisRetriever(_dense_hit())
    app_settings = Settings(
        project_root=ROOT,
        data_dir=ROOT / "data",
        templates_dir=ROOT / "templates",
        output_dir=tmp_path / "output",
        runtime_dir=tmp_path / "runtime",
    )
    orchestrator = EvrakOrchestrator(app_settings, retriever=fake_retriever)

    state = orchestrator.process_file(ROOT / "examples" / "yol_bakim_talebi.txt")
    restored = orchestrator.get(state.document_id)

    # Katman-1 iki ayrı RAG turu kullanır: sınıflandırma ve türe özel şart analizi.
    assert fake_retriever.calls == 2
    assert restored.retrieval_diagnostics is not None
    assert restored.retrieval_diagnostics.mode == "hybrid"
    assert restored.retrieval_diagnostics.dense_status == "used"
    assert restored.search_hits[0].channel_contributions[0].channel == "dense"
    assert restored.verified_references[0].verified is True
    assert restored.verified_references[0].evidence_channels == ["dense"]
    assert restored.verified_references[0].document_id == "TEST-DOC"
    assert restored.verified_references[0].source_kind == "public_legislation"
    assert restored.verified_references[0].domain == "kgm_infrastructure"


def test_hybrid_mode_builds_lazy_application_retriever(tmp_path: Path) -> None:
    active_path = tmp_path / "active_legislation.json"
    active_path.write_text(
        json.dumps(
            _active_envelope(_chunk("PUBLIC", public=True)),
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    app_settings = Settings(
        project_root=ROOT,
        data_dir=ROOT / "data",
        templates_dir=ROOT / "templates",
        output_dir=tmp_path / "output",
        runtime_dir=tmp_path / "runtime",
        retrieval_mode="hybrid",
        active_legislation_path=active_path,
    )

    orchestrator = EvrakOrchestrator(app_settings)

    assert isinstance(orchestrator.retriever, AnalysisAwareHybridRetriever)
    assert orchestrator.retriever.embedding_provider.is_loaded is False
    assert orchestrator.index.documents[0].chunk.source_kind == "public_legislation"


@pytest.mark.parametrize("empty_corpus", [False, True], ids=["missing", "empty"])
def test_unavailable_active_corpus_uses_diagnosed_synthetic_bm25_fallback(
    tmp_path: Path, empty_corpus: bool
) -> None:
    active_path = tmp_path / "active.json"
    if empty_corpus:
        active_path.write_text('{"data": []}', encoding="utf-8")
    app_settings = Settings(
        project_root=ROOT,
        data_dir=ROOT / "data",
        templates_dir=ROOT / "templates",
        output_dir=tmp_path / "output",
        runtime_dir=tmp_path / "runtime",
        retrieval_mode="hybrid",
        active_legislation_path=active_path,
    )
    orchestrator = EvrakOrchestrator(app_settings)

    assert isinstance(orchestrator.retriever, HybridRetriever)
    assert orchestrator.index.documents[0].chunk.source_kind == "synthetic"
    with pytest.warns(DenseRetrievalWarning, match="not configured"):
        state = orchestrator.process_file(
            ROOT / "examples" / "yol_bakim_talebi.txt"
        )

    assert state.retrieval_diagnostics is not None
    assert state.retrieval_diagnostics.fallback_used is True
    assert "Aktif kamu mevzuatı korpusu kullanılamadı" in (
        state.retrieval_diagnostics.warning or ""
    )
