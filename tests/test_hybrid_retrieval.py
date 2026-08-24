from __future__ import annotations

from collections.abc import Sequence

import pytest

from karayol_agent.retrieval.bm25 import BM25Index
from karayol_agent.retrieval.hybrid import (
    DEFAULT_CHANNEL_TOP_N,
    DenseRetrievalWarning,
    HybridRetriever,
    HybridSearchHit,
    fuse_lexical_and_dense,
    reciprocal_rank_fusion,
)
from karayol_agent.schemas import LegislationChunk, SearchHit


def _chunk(chunk_id: str, text: str | None = None) -> LegislationChunk:
    return LegislationChunk(
        chunk_id=chunk_id,
        title=f"Başlık {chunk_id}",
        section="Madde",
        text=text or f"{chunk_id} için örnek hüküm",
        source="test.json",
        tags=[],
    )


def _hit(
    chunk: LegislationChunk,
    score: float,
    matched_terms: list[str] | None = None,
) -> SearchHit:
    return SearchHit(
        chunk=chunk,
        score=score,
        matched_terms=matched_terms or [],
    )


class MockDenseRetriever:
    def __init__(
        self,
        hits: Sequence[SearchHit] = (),
        *,
        error: Exception | None = None,
    ) -> None:
        self.hits = list(hits)
        self.error = error
        self.calls: list[tuple[str, int]] = []

    def search(self, query: str, top_k: int = 5) -> list[SearchHit]:
        self.calls.append((query, top_k))
        if self.error is not None:
            raise self.error
        return self.hits[:top_k]


class RecordingRetriever(MockDenseRetriever):
    pass


def test_rrf_uses_only_rank_while_preserving_raw_scores() -> None:
    a, b, c = _chunk("A"), _chunk("B"), _chunk("C")
    lexical = [_hit(a, 0.000001, ["yol"]), _hit(b, 1_000_000.0, ["bakım"])]
    dense = [_hit(b, -0.75), _hit(c, 99_999_999.0)]

    hits = fuse_lexical_and_dense(lexical, dense, k=60)

    assert [hit.chunk.chunk_id for hit in hits] == ["B", "A", "C"]
    assert hits[0].score == pytest.approx(1 / 62 + 1 / 61)
    assert [(item.channel, item.rank, item.raw_score) for item in hits[0].channel_contributions] == [
        ("lexical", 2, 1_000_000.0),
        ("dense", 1, -0.75),
    ]
    assert hits[1].score == pytest.approx(1 / 61)
    assert hits[2].score == pytest.approx(1 / 62)


def test_rrf_deduplicates_chunk_id_once_per_channel() -> None:
    a, b = _chunk("A"), _chunk("B")
    lexical = [
        _hit(a, 10.0, ["ilk"]),
        _hit(a.model_copy(update={"title": "Farklı backend kopyası"}), 9.0),
        _hit(b, 8.0),
    ]
    dense = [_hit(a, 0.9)]

    hits = fuse_lexical_and_dense(lexical, dense, k=10)

    assert [hit.chunk.chunk_id for hit in hits] == ["A", "B"]
    assert hits[0].chunk.title == "Başlık A"
    assert [(item.channel, item.rank) for item in hits[0].channel_contributions] == [
        ("lexical", 1),
        ("dense", 1),
    ]
    assert hits[0].score == pytest.approx(2 / 11)
    assert hits[1].channel_contributions[0].rank == 3


def test_rrf_tie_break_is_chunk_id_not_raw_score_or_mapping_order() -> None:
    a, b = _chunk("A"), _chunk("B")
    rankings = {
        "dense": [_hit(b, 1_000_000.0)],
        "lexical": [_hit(a, -1_000_000.0)],
    }

    first = reciprocal_rank_fusion(rankings, k=60)
    second = reciprocal_rank_fusion(dict(reversed(list(rankings.items()))), k=60)

    assert [hit.chunk.chunk_id for hit in first] == ["A", "B"]
    assert [hit.chunk.chunk_id for hit in second] == ["A", "B"]


def test_hybrid_retriever_queries_each_channel_with_independent_default_top_n() -> None:
    a, b = _chunk("A"), _chunk("B")
    lexical = RecordingRetriever([_hit(a, 4.0, ["yol"])])
    dense = MockDenseRetriever([_hit(b, 0.8)])
    retriever = HybridRetriever(lexical, dense)

    response = retriever.search_with_diagnostics("yol bakım", top_k=2)

    assert lexical.calls == [("yol bakım", DEFAULT_CHANNEL_TOP_N)]
    assert dense.calls == [("yol bakım", DEFAULT_CHANNEL_TOP_N)]
    assert response.diagnostics.dense_status == "used"
    assert response.diagnostics.fallback_used is False
    assert response.diagnostics.lexical_candidate_count == 1
    assert response.diagnostics.dense_candidate_count == 1
    assert response.diagnostics.fused_candidate_count == 2
    assert all(isinstance(hit, SearchHit) for hit in response.hits)
    assert all(isinstance(hit, HybridSearchHit) for hit in response.hits)


def test_hybrid_retriever_is_compatible_with_real_bm25_index() -> None:
    road = _chunk("ROAD", "Asfalt çukuru yol bakım onarım kuralı")
    permit_rule = _chunk("PERMIT", "Geçiş yolu izin başvurusu kuralı")
    dense = MockDenseRetriever([_hit(road, 0.42), _hit(permit_rule, 0.91)])
    retriever = HybridRetriever(BM25Index([road, permit_rule]), dense)

    hits = retriever.search("asfalt bakım", top_k=2)
    legacy_hits = retriever.search_as_search_hits("asfalt bakım", top_k=2)

    assert hits[0].chunk.chunk_id == "ROAD"
    assert "asfalt" in hits[0].matched_terms
    assert type(legacy_hits[0]) is SearchHit


def test_missing_dense_retriever_warns_and_reports_bm25_fallback() -> None:
    lexical_hit = _hit(_chunk("LEX"), 7.25, ["bakım"])
    retriever = HybridRetriever(RecordingRetriever([lexical_hit]))

    with pytest.warns(DenseRetrievalWarning, match="not configured"):
        response = retriever.search_with_diagnostics("bakım", top_k=5)

    assert [hit.chunk.chunk_id for hit in response.hits] == ["LEX"]
    assert response.hits[0].channel_contributions[0].raw_score == 7.25
    assert response.diagnostics.dense_status == "unavailable"
    assert response.diagnostics.fallback_used is True
    assert response.diagnostics.warning is not None
    assert response.diagnostics.dense_candidate_count == 0


def test_dense_error_warns_and_reports_bm25_fallback() -> None:
    lexical_hit = _hit(_chunk("LEX"), 2.0, ["yol"])
    dense = MockDenseRetriever(error=ConnectionError("Qdrant erişilemiyor"))
    retriever = HybridRetriever(RecordingRetriever([lexical_hit]), dense)

    with pytest.warns(DenseRetrievalWarning, match="ConnectionError"):
        response = retriever.search_with_diagnostics("yol", top_k=5)

    assert [hit.chunk.chunk_id for hit in response.hits] == ["LEX"]
    assert response.diagnostics.dense_status == "error"
    assert response.diagnostics.fallback_used is True
    assert response.diagnostics.dense_error_type == "ConnectionError"
    assert "Qdrant erişilemiyor" not in (response.diagnostics.warning or "")


def test_invalid_dense_results_fall_back_without_hiding_the_problem() -> None:
    lexical_hit = _hit(_chunk("LEX"), 2.0)
    invalid_dense_hit = _hit(_chunk("DENSE"), float("nan"))
    dense = MockDenseRetriever([invalid_dense_hit])
    retriever = HybridRetriever(RecordingRetriever([lexical_hit]), dense)

    with pytest.warns(DenseRetrievalWarning, match="invalid results"):
        response = retriever.search_with_diagnostics("yol", top_k=5)

    assert [hit.chunk.chunk_id for hit in response.hits] == ["LEX"]
    assert response.diagnostics.dense_status == "error"
    assert response.diagnostics.dense_candidate_count == 0


@pytest.mark.parametrize("k", [-1, 1.5, True])
def test_rrf_rejects_invalid_k(k: object) -> None:
    with pytest.raises(ValueError):
        reciprocal_rank_fusion({}, k=k)  # type: ignore[arg-type]
