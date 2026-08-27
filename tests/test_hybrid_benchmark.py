from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from karayol_agent.evaluation.hybrid_benchmark import (
    SyntheticBenchmarkError,
    SyntheticQdrantDenseRetriever,
    build_synthetic_hybrid_benchmark,
    contextualize_synthetic_chunks,
)
from karayol_agent.retrieval.embeddings import DeterministicHashEmbeddingProvider
from karayol_agent.schemas import LegislationChunk


ROOT = Path(__file__).resolve().parents[1]


class _Models:
    class Distance:
        COSINE = "Cosine"

    @staticmethod
    def VectorParams(**kwargs: object) -> SimpleNamespace:
        return SimpleNamespace(**kwargs)

    @staticmethod
    def PointStruct(**kwargs: object) -> SimpleNamespace:
        return SimpleNamespace(**kwargs)


class _Client:
    def __init__(self) -> None:
        self.points: list[SimpleNamespace] = []
        self.collection: str | None = None

    def create_collection(self, **kwargs: object) -> None:
        self.collection = str(kwargs["collection_name"])

    def upsert(self, **kwargs: object) -> None:
        self.points = list(kwargs["points"])  # type: ignore[arg-type]

    def query_points(self, **kwargs: object) -> SimpleNamespace:
        ranked = [
            SimpleNamespace(payload=point.payload, score=0.9 - index * 0.1)
            for index, point in enumerate(self.points)
        ]
        return SimpleNamespace(points=ranked[: int(kwargs["limit"])])


def _synthetic_chunk() -> LegislationChunk:
    return LegislationChunk(
        chunk_id="SENT-TEST-001",
        title="Sentetik Kural",
        section="Yol bakım",
        article="Kural 1",
        text="Asfalt bakım talebi ilgili birime yönlendirilir.",
        source="synthetic.json",
        source_kind="synthetic",
        status="sentetik_demo_kurali",
    )


def test_contextualize_keeps_original_text_and_adds_structure() -> None:
    original = _synthetic_chunk()

    contextualized = contextualize_synthetic_chunks([original])[0]

    assert contextualized.text == original.text
    assert contextualized.context_text == "Sentetik Kural > Yol bakım > Kural 1"


def test_dense_benchmark_requires_explicit_synthetic_boundary() -> None:
    public = _synthetic_chunk().model_copy(
        update={"source_kind": "public_legislation"}
    )
    contextual = contextualize_synthetic_chunks([public])

    with pytest.raises(SyntheticBenchmarkError, match="sentetik demo"):
        SyntheticQdrantDenseRetriever(
            contextual,
            DeterministicHashEmbeddingProvider(dimension=32),
            client=_Client(),
            models_module=_Models,
        )


def test_dense_benchmark_uses_isolated_collection_and_returns_hits() -> None:
    chunks = contextualize_synthetic_chunks([_synthetic_chunk()])
    client = _Client()
    retriever = SyntheticQdrantDenseRetriever(
        chunks,
        DeterministicHashEmbeddingProvider(dimension=32),
        client=client,
        models_module=_Models,
        collection_name="benchmark_contract_test",
    )

    hits = retriever.search("asfalt", top_k=1)

    assert client.collection == "benchmark_contract_test"
    assert client.points[0].payload["benchmark_only"] is True
    assert client.points[0].payload["source_kind"] == "synthetic"
    assert hits[0].chunk.chunk_id == "SENT-TEST-001"
    assert retriever.index_report.passage_task == "retrieval.passage"
    assert retriever.index_report.query_task == "retrieval.query"
    assert len(retriever.index_report.corpus_fingerprint) == 64
    assert retriever.index_report.corpus_source_path is None
    assert retriever.query_count == 1


def test_dense_benchmark_rejects_a_stale_corpus_payload() -> None:
    chunks = contextualize_synthetic_chunks([_synthetic_chunk()])
    client = _Client()
    retriever = SyntheticQdrantDenseRetriever(
        chunks,
        DeterministicHashEmbeddingProvider(dimension=32),
        client=client,
        models_module=_Models,
        collection_name="benchmark_stale_corpus_test",
    )
    client.points[0].payload["corpus_fingerprint"] = "0" * 64

    with pytest.raises(SyntheticBenchmarkError, match="farklı corpus"):
        retriever.search("asfalt", top_k=1)


def test_builder_combines_real_bm25_with_benchmark_dense_channel() -> None:
    runtime = build_synthetic_hybrid_benchmark(
        legislation_path=ROOT / "data" / "synthetic_legislation.json",
        embedding_provider=DeterministicHashEmbeddingProvider(dimension=32),
        client=_Client(),
        models_module=_Models,
        collection_name="benchmark_builder_test",
    )

    response = runtime.retriever.search_with_diagnostics("asfalt bakım", top_k=5)

    assert runtime.index_report.chunk_count == 7
    assert runtime.index_report.corpus_source_path == "data/synthetic_legislation.json"
    assert len(runtime.index_report.corpus_source_sha256 or "") == 64
    assert len(runtime.index_report.corpus_fingerprint) == 64
    assert response.diagnostics.dense_status == "used"
    assert response.diagnostics.lexical_candidate_count > 0
    assert response.diagnostics.dense_candidate_count == 7
    assert any(
        contribution.channel == "dense"
        for hit in response.hits
        for contribution in hit.channel_contributions
    )
