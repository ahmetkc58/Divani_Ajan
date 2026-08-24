from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

import pytest

from karayol_agent.agents.legislation import SourceVerificationAgent
from karayol_agent.retrieval.contracts import CorpusMode
from karayol_agent.retrieval.relevance import (
    AnalysisAwareDeterministicReranker,
    AnalysisAwareTextRetrieverAdapter,
    PROFILE_EXPANSIONS,
    ROAD_SURFACE_PROFILE,
    TRAFFIC_SIGN_PROFILE,
    assess_query_relevance,
    assess_query_intent,
    build_relevance_query,
    resolve_relevance_profile,
)
from karayol_agent.retrieval.repository import LegislationRepository
from karayol_agent.schemas import (
    DocumentAnalysis,
    ExtractedField,
    FieldStatus,
    RetrievalDiagnostics,
    SearchHit,
)
from karayol_agent.text_utils import normalize_for_search
from scripts.evaluate_snapshot_relevance import _query_metrics


ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT = ROOT / "data" / "processed" / "competition_snapshot.json"
GOLD = ROOT / "data" / "evaluation" / "competition_snapshot_relevance_v1.json"


@pytest.fixture(scope="module")
def snapshot_chunks():
    chunks, binding = LegislationRepository(
        SNAPSHOT,
        corpus_mode=CorpusMode.COMPETITION_SNAPSHOT,
    ).load_with_binding()
    return {chunk.chunk_id: chunk for chunk in chunks}, binding


def _analysis(document_type: str, summary: str) -> DocumentAnalysis:
    return DocumentAnalysis(
        document_type=document_type,
        confidence=0.95,
        summary=summary,
        fields={
            "konu": ExtractedField(
                value=summary,
                status=FieldStatus.FROM_SOURCE,
            ),
            "talep": ExtractedField(
                value="Gerekli bakım ve onarımın yapılması",
                status=FieldStatus.FROM_SOURCE,
            ),
        },
        keywords=["trafik", "bakım"],
    )


def test_gold_is_bound_to_snapshot_and_all_anchors_are_real(snapshot_chunks) -> None:
    by_id, binding = snapshot_chunks
    dataset = json.loads(GOLD.read_text(encoding="utf-8"))

    assert dataset["corpus"]["fingerprint"] == binding.fingerprint
    assert dataset["corpus"]["file_sha256"] == hashlib.sha256(
        SNAPSHOT.read_bytes()
    ).hexdigest()
    for query in dataset["queries"]:
        judged_ids: set[str] = set()
        for judgment in query["judgments"]:
            chunk_id = judgment["chunk_id"]
            assert chunk_id not in judged_ids
            judged_ids.add(chunk_id)
            chunk = by_id[chunk_id]
            searchable = normalize_for_search(
                f"{chunk.context_text or ''} {chunk.text}"
            )
            assert normalize_for_search(judgment["text_anchor"]) in searchable
        assert not judged_ids.intersection(query["hard_negative_chunk_ids"])
        assert all(chunk_id in by_id for chunk_id in query["hard_negative_chunk_ids"])


def test_reviewed_profiles_are_resolved_and_expansions_name_no_article() -> None:
    road = _analysis("yol_bakim_talebi", "Asfalt çukuru için yol bakım talebi")
    sign = _analysis(
        "trafik_guvenligi_bildirimi",
        "Devrilmiş trafik işaret levhası",
    )
    generic_traffic = _analysis(
        "trafik_guvenligi_bildirimi",
        "Yaya geçidinde güvenlik sorunu",
    )

    assert resolve_relevance_profile(road) == ROAD_SURFACE_PROFILE
    assert resolve_relevance_profile(sign) == TRAFFIC_SIGN_PROFILE
    assert resolve_relevance_profile(generic_traffic) is None
    for profile in (ROAD_SURFACE_PROFILE, TRAFFIC_SIGN_PROFILE):
        expanded = normalize_for_search(build_relevance_query("örnek", profile))
        assert "madde" not in expanded
        assert "2918" not in expanded
        assert all(term in expanded for term in PROFILE_EXPANSIONS[profile])


@pytest.mark.parametrize(
    ("profile", "text"),
    [
        (
            ROAD_SURFACE_PROFILE,
            "D-100 üzerindeki derin çukurlar kapatılsın, bozulan asfalt onarılsın.",
        ),
        (
            ROAD_SURFACE_PROFILE,
            "Kaplamadaki çatlaklar trafik güvenliği için giderilsin.",
        ),
        (
            TRAFFIC_SIGN_PROFILE,
            "Kavşaktaki trafik yön levhası devrildi; yenilenmesini rica ederim.",
        ),
        (
            TRAFFIC_SIGN_PROFILE,
            "Trafik işaret levhası kırılmış ve görünmüyor; arıza giderilsin.",
        ),
    ],
)
def test_query_intent_requires_submitted_incident_concepts(
    profile: str,
    text: str,
) -> None:
    decision = assess_query_intent(profile=profile, evidence_text=text)

    assert decision.supported is True
    assert decision.score >= 2 / 3


@pytest.mark.parametrize(
    ("profile", "text"),
    [
        (
            ROAD_SURFACE_PROFILE,
            "Yol bakım personeli iş başvurusu yapmak istiyorum.",
        ),
        (
            ROAD_SURFACE_PROFILE,
            "Asfalt yamasında bitüm oranı ve teknik şartname nedir?",
        ),
        (
            ROAD_SURFACE_PROFILE,
            "Tünel aydınlatma sistemindeki arıza giderilsin.",
        ),
        (
            ROAD_SURFACE_PROFILE,
            "Çukura girince jantım kırıldı; tazminat ve değer kaybı istiyorum.",
        ),
        (
            TRAFFIC_SIGN_PROFILE,
            "Trafik işaret levhasına uymadığım cezaya itiraz etmek istiyorum.",
        ),
        (
            TRAFFIC_SIGN_PROFILE,
            "Kazada devrilen trafik levhasının bedelini sigorta mı öder?",
        ),
        (
            TRAFFIC_SIGN_PROFILE,
            "Trafik işaret levhalarının teknik ölçülerini öğrenmek istiyorum.",
        ),
        (
            TRAFFIC_SIGN_PROFILE,
            "Hasarlı araç plakası veya ayırım işareti nasıl yenilenir?",
        ),
    ],
)
def test_query_intent_rejects_no_answer_and_near_miss_inputs(
    profile: str,
    text: str,
) -> None:
    assert assess_query_intent(profile=profile, evidence_text=text).supported is False


@pytest.mark.parametrize(
    ("profile", "positive_ids", "negative_ids"),
    [
        (
            ROAD_SURFACE_PROFILE,
            [
                "MEV-B4102E4DDE97752F",
                "MEV-F3938057B283C03C",
                "MEV-09E4E088C59D4D13",
                "MEV-D1B127E868E39891",
                "MEV-94ECA73AA07B2D39",
            ],
            [
                "MEV-C863A805478FFC53",
                "MEV-56214B1A9589A5DA",
                "MEV-9DFE7B7E895F4F01",
                "MEV-311383AB24A5855D",
                "MEV-557C8DA8A10F2BA5",
            ],
        ),
        (
            TRAFFIC_SIGN_PROFILE,
            [
                "MEV-F3938057B283C03C",
                "MEV-B4102E4DDE97752F",
                "MEV-557C8DA8A10F2BA5",
                "MEV-06B1C9050FB89590",
                "MEV-E65ACF3F7612C808",
            ],
            [
                "MEV-CD368D3D73FF9FE8",
                "MEV-097A621442A40371",
                "MEV-031D0A3918F5F30E",
                "MEV-9C1D2E3C962F54A1",
            ],
        ),
    ],
)
def test_concept_gate_accepts_gold_and_rejects_hard_cases(
    snapshot_chunks,
    profile: str,
    positive_ids: list[str],
    negative_ids: list[str],
) -> None:
    by_id, _ = snapshot_chunks
    query = (
        "asfalt çukuru yol bakım onarım"
        if profile == ROAD_SURFACE_PROFILE
        else "devrilmiş hasarlı trafik işaret levhası"
    )

    assert all(
        assess_query_relevance(
            by_id[chunk_id], profile=profile, query=query
        ).accepted
        for chunk_id in positive_ids
    )
    assert all(
        not assess_query_relevance(
            by_id[chunk_id], profile=profile, query=query
        ).accepted
        for chunk_id in negative_ids
    )


def test_context_only_sign_rule_is_not_exposed_as_misleading_child_citation(
    snapshot_chunks,
) -> None:
    by_id, _ = snapshot_chunks
    decision = assess_query_relevance(
        by_id["MEV-51492E2304E2F0A8"],
        profile=TRAFFIC_SIGN_PROFILE,
        query="hasarlı trafik işaret levhası",
    )

    assert decision.accepted is False
    assert decision.basis == "context_only"
    assert any("yalnız üst bağlamda" in reason for reason in decision.reasons)


@dataclass
class _Response:
    hits: list[SearchHit]
    diagnostics: RetrievalDiagnostics


class _FakeAnalysisRetriever:
    retrieval_mode = "hybrid"
    vector_store = object()

    def __init__(self, hits: list[SearchHit]) -> None:
        self.hits = hits
        self.calls: list[tuple[str, int]] = []

    def search_for_analysis(
        self,
        query: str,
        analysis: DocumentAnalysis,
        top_k: int = 5,
    ) -> _Response:
        self.calls.append((query, top_k))
        return _Response(
            hits=self.hits[:top_k],
            diagnostics=RetrievalDiagnostics(
                mode="hybrid",
                dense_status="used",
                lexical_candidate_count=len(self.hits),
                dense_candidate_count=len(self.hits),
                fused_candidate_count=len(self.hits),
                channel_top_n=20,
                rrf_k=60,
            ),
        )


def test_wrapper_reranks_before_top_five_and_persists_diagnostics(
    snapshot_chunks,
) -> None:
    by_id, _ = snapshot_chunks
    irrelevant = SearchHit(
        chunk=by_id["MEV-311383AB24A5855D"], score=0.04
    )
    direct = SearchHit(
        chunk=by_id["MEV-B4102E4DDE97752F"], score=0.01
    )
    fake = _FakeAnalysisRetriever([irrelevant, direct])
    reranker = AnalysisAwareDeterministicReranker(
        fake,
        candidate_top_k=30,
        threshold=0.75,
    )
    analysis = _analysis("yol_bakim_talebi", "Asfalt çukuru yol bakım talebi")

    result = reranker.search_for_analysis("asfalt çukuru", analysis, top_k=5)

    assert fake.calls[0][1] == 30
    assert "bozukluk ve eksiklik" in normalize_for_search(fake.calls[0][0])
    assert [hit.chunk.chunk_id for hit in result.hits] == [
        "MEV-B4102E4DDE97752F"
    ]
    assert result.hits[0].relevance_accepted is True
    assert result.hits[0].relevance_score == 1.0
    assert result.diagnostics.relevance_candidate_count == 2
    assert result.diagnostics.relevance_candidate_top_k == 30
    assert result.diagnostics.relevance_accepted_count == 1
    assert result.diagnostics.relevance_rejected_count == 1
    assert result.diagnostics.relevance_abstained is False
    assert reranker.vector_store is fake.vector_store

    reference = SourceVerificationAgent().run(result.hits, analysis)[0]
    assert reference.relevance_accepted is True
    assert reference.relevance_profile == ROAD_SURFACE_PROFILE


def test_wrapper_abstains_instead_of_returning_only_irrelevant_candidates(
    snapshot_chunks,
) -> None:
    by_id, _ = snapshot_chunks
    fake = _FakeAnalysisRetriever(
        [SearchHit(chunk=by_id["MEV-311383AB24A5855D"], score=0.04)]
    )
    reranker = AnalysisAwareDeterministicReranker(fake, threshold=0.75)

    result = reranker.search_for_analysis(
        "asfalt çukuru",
        _analysis("yol_bakim_talebi", "Asfalt çukuru yol bakım talebi"),
        top_k=5,
    )

    assert result.hits == []
    assert result.diagnostics.relevance_abstained is True
    assert "yanlış atıf" in (result.diagnostics.warning or "")


def test_query_gate_abstains_before_retrieval_for_misclassified_input(
    snapshot_chunks,
) -> None:
    by_id, _ = snapshot_chunks
    fake = _FakeAnalysisRetriever(
        [SearchHit(chunk=by_id["MEV-B4102E4DDE97752F"], score=1.0)]
    )
    reranker = AnalysisAwareDeterministicReranker(fake)
    analysis = _analysis("yol_bakim_talebi", "Yol bakım talebi")
    analysis.retrieval_evidence_text = (
        "Tünel aydınlatma sistemindeki arıza giderilsin."
    )

    result = reranker.search_for_analysis("yol bakım talebi", analysis)

    assert result.hits == []
    assert fake.calls == []
    assert result.diagnostics.relevance_query_supported is False
    assert result.diagnostics.relevance_abstained is True
    assert result.diagnostics.relevance_candidate_count == 0


def test_unsupported_snapshot_profile_fails_closed_without_retrieval(
    snapshot_chunks,
) -> None:
    by_id, _ = snapshot_chunks
    fake = _FakeAnalysisRetriever(
        [SearchHit(chunk=by_id["MEV-B4102E4DDE97752F"], score=1.0)]
    )
    reranker = AnalysisAwareDeterministicReranker(fake)

    result = reranker.search_for_analysis(
        "genel başvuru",
        _analysis("genel_basvuru", "Genel başvuru"),
    )

    assert result.hits == []
    assert fake.calls == []
    assert result.diagnostics.relevance_profile is None
    assert result.diagnostics.relevance_abstained is True


def test_expansion_terms_are_not_reported_as_original_lexical_evidence(
    snapshot_chunks,
) -> None:
    by_id, _ = snapshot_chunks
    fake = _FakeAnalysisRetriever(
        [
            SearchHit(
                chunk=by_id["MEV-B4102E4DDE97752F"],
                score=1.0,
                matched_terms=["karayolu", "bozukluk", "eksiklik"],
            )
        ]
    )
    reranker = AnalysisAwareDeterministicReranker(fake)
    analysis = _analysis(
        "yol_bakim_talebi",
        "Karayolu asfalt çukuru için bakım ve onarım talebi",
    )

    result = reranker.search_for_analysis("karayolu asfalt çukuru", analysis)

    assert result.hits[0].matched_terms == ["karayolu"]
    assert result.hits[0].expansion_matched_terms == ["bozukluk", "eksiklik"]
    reference = SourceVerificationAgent().run(result.hits, analysis)[0]
    assert reference.verified is True
    assert "Sorgu terimleri" in reference.verification_note


def test_bm25_adapter_preserves_mode_and_applies_same_relevance_gate(
    snapshot_chunks,
) -> None:
    by_id, _ = snapshot_chunks

    class _TextRetriever:
        def __init__(self) -> None:
            self.calls: list[tuple[str, int]] = []

        def search(self, query: str, top_k: int = 5) -> list[SearchHit]:
            self.calls.append((query, top_k))
            return [
                SearchHit(
                    chunk=by_id["MEV-B4102E4DDE97752F"],
                    score=2.0,
                    matched_terms=["karayolu", "bozukluk"],
                )
            ]

    base = _TextRetriever()
    adapter = AnalysisAwareTextRetrieverAdapter(base, mode="bm25")
    reranker = AnalysisAwareDeterministicReranker(adapter, candidate_top_k=40)
    analysis = _analysis(
        "yol_bakim_talebi",
        "Karayolu asfalt çukuru bakım onarım talebi",
    )

    result = reranker.search_for_analysis("karayolu asfalt çukuru", analysis)

    assert base.calls[0][1] == 40
    assert result.diagnostics.mode == "bm25"
    assert result.diagnostics.dense_status == "not_requested"
    assert [hit.chunk.chunk_id for hit in result.hits] == [
        "MEV-B4102E4DDE97752F"
    ]


def test_metric_scorer_penalizes_irrelevant_filler() -> None:
    query = {
        "judgments": [
            {"chunk_id": "A", "grade": 3, "provision_family": "F1"},
            {"chunk_id": "B", "grade": 2, "provision_family": "F2"},
            {"chunk_id": "C", "grade": 1, "provision_family": "F3"},
        ],
        "hard_negative_chunk_ids": ["X"],
    }

    metrics = _query_metrics(query, ["X", "B", "A", "Y", "C"], k=5, min_grade=2)

    assert metrics["precision_at_k"] == pytest.approx(0.4)
    assert metrics["recall_at_k"] == pytest.approx(1.0)
    assert metrics["reciprocal_rank"] == pytest.approx(0.5)
    assert metrics["hard_negative_count_at_k"] == 1
