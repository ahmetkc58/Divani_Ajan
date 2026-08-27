from types import SimpleNamespace

from karayol_agent.retrieval.federated import FederatedAnalysisRetriever
from karayol_agent.schemas import DocumentAnalysis, LegislationChunk, SearchHit


def _chunk(chunk_id: str) -> LegislationChunk:
    return LegislationChunk(
        chunk_id=chunk_id,
        document_id=f"DOC-{chunk_id}",
        title=chunk_id,
        section="Bölüm",
        text="karayolu bakım onarım",
        source=f"{chunk_id}.txt",
        source_kind="competition_snapshot",
    )


class _Primary:
    def search_for_analysis(self, query, analysis, top_k=5):
        del query, analysis, top_k
        return SimpleNamespace(
            hits=[SearchHit(chunk=_chunk("UAB-1"), score=8.0, matched_terms=["bakım"])],
            diagnostics=SimpleNamespace(warning=None),
        )


class _External:
    def search(self, query, top_k=5):
        del query, top_k
        return [SearchHit(chunk=_chunk("MEV-1"), score=0.82)]


def test_federated_retriever_returns_both_corpora() -> None:
    retriever = FederatedAnalysisRetriever(_Primary(), _External(), channel_top_n=10)
    analysis = DocumentAnalysis(
        document_type="yol_bakim_talebi",
        confidence=1,
        summary="Yol bakım talebi",
        fields={},
    )

    response = retriever.search_for_analysis("yol bakım", analysis, top_k=5)

    assert {hit.chunk.chunk_id for hit in response.hits} == {"UAB-1", "MEV-1"}
    assert response.diagnostics.lexical_candidate_count == 1
    assert response.diagnostics.dense_candidate_count == 1
    assert response.diagnostics.dense_status == "used"
