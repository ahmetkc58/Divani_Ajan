from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from karayol_agent.retrieval import embeddings as embeddings_module
from karayol_agent.retrieval import qdrant_store as qdrant_store_module
from karayol_agent.retrieval.corpus import build_corpus_binding
from karayol_agent.retrieval.contracts import CorpusMode
from karayol_agent.retrieval.embeddings import EmbeddingMetadata, EmbeddingTask
from karayol_agent.retrieval.hybrid import DenseRetrievalWarning
from karayol_agent.retrieval.runtime import (
    AnalysisAwareHybridRetriever,
    AnalysisDomainResolver,
    ArchiveWideDomainResolver,
    DomainAwareDenseRetriever,
    DomainResolutionError,
    RuntimeContractError,
    build_analysis_query,
    build_retrieval_runtime,
)
from karayol_agent.schemas import (
    DocumentAnalysis,
    ExtractedField,
    FieldStatus,
    LegislationChunk,
    SearchHit,
)


def _analysis(
    *,
    document_type: str = "yol_bakim_talebi",
    summary: str = "Asfalt çukuru için yol bakım ve onarım talep edilmektedir.",
    keywords: list[str] | None = None,
) -> DocumentAnalysis:
    return DocumentAnalysis(
        document_type=document_type,
        confidence=0.95,
        summary=summary,
        fields={
            "konu": ExtractedField(
                value="Yol bakım ihtiyacı",
                status=FieldStatus.INFERRED,
            ),
            "talep": ExtractedField(
                value="Hasarın giderilmesini talep ediyorum.",
                status=FieldStatus.FROM_SOURCE,
            ),
        },
        keywords=keywords or ["asfalt", "bakım"],
    )


def _chunk(chunk_id: str) -> LegislationChunk:
    return LegislationChunk(
        chunk_id=chunk_id,
        title=f"Başlık {chunk_id}",
        section="Madde",
        text=f"{chunk_id} için örnek hüküm",
        source="test.json",
    )


class RecordingEmbeddingProvider:
    model_name = "test/jina-compatible"
    dimension = 4
    model_revision = "weights"
    code_revision = "code"

    def __init__(self) -> None:
        self.query_batches: list[list[str]] = []
        self.passage_batches: list[list[str]] = []

    @property
    def passage_metadata(self) -> EmbeddingMetadata:
        return EmbeddingMetadata(
            model_name=self.model_name,
            dimension=self.dimension,
            task=EmbeddingTask.PASSAGE,
            backend="fake",
            model_revision=self.model_revision,
            code_revision=self.code_revision,
        )

    @property
    def query_metadata(self) -> EmbeddingMetadata:
        return EmbeddingMetadata(
            model_name=self.model_name,
            dimension=self.dimension,
            task=EmbeddingTask.QUERY,
            backend="fake",
            model_revision=self.model_revision,
            code_revision=self.code_revision,
        )

    def embed_queries(self, texts: Sequence[str]) -> list[list[float]]:
        values = list(texts)
        self.query_batches.append(values)
        return [[0.5, 0.5, 0.5, 0.5] for _ in values]

    def embed_passages(self, texts: Sequence[str]) -> list[list[float]]:
        values = list(texts)
        self.passage_batches.append(values)
        return [[0.5, 0.5, 0.5, 0.5] for _ in values]


class RecordingDenseStore:
    embedding_model = RecordingEmbeddingProvider.model_name
    embedding_dimension = RecordingEmbeddingProvider.dimension
    embedding_model_revision = RecordingEmbeddingProvider.model_revision
    embedding_code_revision = RecordingEmbeddingProvider.code_revision
    passage_task = "retrieval.passage"
    query_task = "retrieval.query"
    collection_name = "test_chunks"
    index_version = "test-v1"

    def __init__(self, hits: Sequence[SearchHit] = ()) -> None:
        self.hits = list(hits)
        self.calls: list[dict[str, Any]] = []

    def dense_search(
        self,
        query_vector: Sequence[float],
        *,
        domain: str,
        limit: int = 20,
        embedding_task: str = "retrieval.query",
    ) -> list[SearchHit]:
        self.calls.append(
            {
                "vector": list(query_vector),
                "domain": domain,
                "limit": limit,
                "embedding_task": embedding_task,
            }
        )
        return self.hits[:limit]


class RecordingLexicalRetriever:
    def __init__(self, hits: Sequence[SearchHit]) -> None:
        self.hits = list(hits)
        self.calls: list[tuple[str, int]] = []

    def search(self, query: str, top_k: int = 5) -> list[SearchHit]:
        self.calls.append((query, top_k))
        return self.hits[:top_k]


def test_analysis_domain_resolver_uses_document_and_content_signals() -> None:
    resolver = AnalysisDomainResolver()

    infrastructure = resolver.resolve(_analysis())
    transport = resolver.resolve(
        _analysis(
            document_type="bilgi_talebi",
            summary="Karayolu taşıma yetki belgesi ve takograf şartları sorulmaktadır.",
            keywords=["yetki belgesi", "takograf"],
        )
    )

    assert infrastructure.domain == "kgm_infrastructure"
    assert transport.domain == "road_transport"
    assert transport.source == "analysis_rules"
    assert any("yetki belgesi" in item for item in transport.evidence)


def test_explicit_domain_wins_and_out_of_scope_value_fails_closed() -> None:
    resolver = AnalysisDomainResolver()
    explicit = {
        "domain": "official_writing",
        "document_type": "yol_bakim_talebi",
        "summary": "asfalt bakım",
    }

    assert resolver.resolve(explicit).domain == "official_writing"
    with pytest.raises(DomainResolutionError, match="aktif retrieval kapsamında değil"):
        resolver.resolve({**explicit, "domain": "aviation"})


def test_archive_wide_resolver_is_explicit_and_deterministic() -> None:
    resolution = ArchiveWideDomainResolver().resolve(_analysis())

    assert resolution.domain == "__all__"
    assert resolution.source == "archive_wide_opt_in"
    assert resolution.confidence == 1.0


def test_ambiguous_analysis_domain_fails_closed() -> None:
    analysis = {
        "document_type": "tanimsiz",
        "summary": "Karayolu taşıma şartları ile bilgi edinme usulü birlikte soruluyor",
        "keywords": [],
        "fields": {},
    }

    with pytest.raises(DomainResolutionError, match="belirsiz"):
        AnalysisDomainResolver().resolve(analysis)


def test_dense_retriever_embeds_query_and_applies_resolved_domain() -> None:
    provider = RecordingEmbeddingProvider()
    expected = SearchHit(chunk=_chunk("DENSE"), score=0.91)
    store = RecordingDenseStore([expected])
    retriever = DomainAwareDenseRetriever(provider, store, _analysis())

    hits = retriever.search("asfalt bakım mevzuatı", top_k=7)

    assert hits == [expected]
    assert provider.query_batches == [["asfalt bakım mevzuatı"]]
    assert store.calls == [
        {
            "vector": [0.5, 0.5, 0.5, 0.5],
            "domain": "kgm_infrastructure",
            "limit": 7,
            "embedding_task": "retrieval.query",
        }
    ]
    assert retriever.last_resolution is not None
    assert retriever.last_resolution.domain == "kgm_infrastructure"


def test_dense_retriever_rejects_embedding_store_contract_mismatch() -> None:
    provider = RecordingEmbeddingProvider()
    store = RecordingDenseStore()
    store.embedding_dimension = 1024
    retriever = DomainAwareDenseRetriever(provider, store, _analysis())

    with pytest.raises(RuntimeContractError, match="sözleşmesi uyuşmuyor"):
        retriever.search("sorgu")

    assert provider.query_batches == []
    assert store.calls == []


def test_analysis_aware_wrapper_uses_one_enriched_query_for_both_channels() -> None:
    lexical_hit = SearchHit(chunk=_chunk("LEX"), score=4.0, matched_terms=["asfalt"])
    dense_hit = SearchHit(chunk=_chunk("DENSE"), score=0.8)
    lexical = RecordingLexicalRetriever([lexical_hit])
    provider = RecordingEmbeddingProvider()
    store = RecordingDenseStore([dense_hit])
    retriever = AnalysisAwareHybridRetriever(
        lexical,
        provider,
        store,
        channel_top_n=10,
    )
    analysis = _analysis()

    response = retriever.search_with_diagnostics(analysis, top_k=2)
    query = build_analysis_query(analysis)

    assert lexical.calls == [(query, 10)]
    assert provider.query_batches == [[query]]
    assert store.calls[0]["domain"] == "kgm_infrastructure"
    assert {hit.chunk.chunk_id for hit in response.hits} == {"LEX", "DENSE"}
    assert response.diagnostics.dense_status == "used"
    assert response.diagnostics.fallback_used is False


def test_search_for_analysis_uses_supplied_enriched_query_without_rebuilding() -> None:
    lexical_hit = SearchHit(chunk=_chunk("LEX"), score=4.0, matched_terms=["özel"])
    dense_hit = SearchHit(chunk=_chunk("DENSE"), score=0.8)
    lexical = RecordingLexicalRetriever([lexical_hit])
    provider = RecordingEmbeddingProvider()
    store = RecordingDenseStore([dense_hit])
    retriever = AnalysisAwareHybridRetriever(
        lexical,
        provider,
        store,
        channel_top_n=9,
    )
    supplied_query = "ajan tarafından önceden zenginleştirilmiş özel sorgu"

    response = retriever.search_for_analysis(
        supplied_query,
        _analysis(),
        top_k=2,
    )

    assert lexical.calls == [(supplied_query, 9)]
    assert provider.query_batches == [[supplied_query]]
    assert store.calls[0]["domain"] == "kgm_infrastructure"
    assert {hit.chunk.chunk_id for hit in response.hits} == {"LEX", "DENSE"}


def test_unresolved_domain_becomes_observable_bm25_fallback() -> None:
    lexical_hit = SearchHit(chunk=_chunk("LEX"), score=3.0, matched_terms=["başvuru"])
    lexical = RecordingLexicalRetriever([lexical_hit])
    provider = RecordingEmbeddingProvider()
    store = RecordingDenseStore()
    retriever = AnalysisAwareHybridRetriever(lexical, provider, store)
    analysis = {
        "document_type": "tanimsiz",
        "summary": "İçerik açıklaması",
        "keywords": [],
        "fields": {},
    }

    with pytest.warns(DenseRetrievalWarning, match="DomainResolutionError"):
        response = retriever.search_with_diagnostics(analysis)

    assert [hit.chunk.chunk_id for hit in response.hits] == ["LEX"]
    assert response.diagnostics.dense_status == "error"
    assert response.diagnostics.fallback_used is True
    assert response.diagnostics.dense_error_type == "DomainResolutionError"
    assert provider.query_batches == []
    assert store.calls == []


def test_runtime_factory_keeps_optional_dependencies_lazy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    imported: list[str] = []

    def forbidden_optional_import(name: str) -> Any:
        imported.append(name)
        raise AssertionError(f"optional dependency imported early: {name}")

    monkeypatch.setattr(embeddings_module, "import_module", forbidden_optional_import)
    monkeypatch.setattr(qdrant_store_module, "import_module", forbidden_optional_import)
    settings = SimpleNamespace(
        embedding_model="jinaai/jina-embeddings-v3",
        embedding_dimension=1024,
        embedding_revision="1" * 40,
        embedding_code_revision="2" * 40,
        embedding_batch_size=8,
        qdrant_url="http://qdrant.test:6333",
        qdrant_api_key=None,
        qdrant_timeout_seconds=3.0,
        qdrant_collection="legal-test-v1",
        index_version="test-v1",
    )

    binding = build_corpus_binding([_chunk("BOUND")])
    runtime = build_retrieval_runtime(settings, corpus_binding=binding)

    assert imported == []
    assert runtime.embedding_provider.model_revision == "1" * 40
    assert runtime.embedding_provider.code_revision == "2" * 40
    assert runtime.qdrant_store.collection_name == "legal-test-v1"
    assert runtime.qdrant_store.embedding_dimension == 1024
    assert runtime.qdrant_store._client is None
    assert runtime.qdrant_store.corpus_binding == binding


def test_runtime_factory_wires_embedded_qdrant_path_lazily(
    tmp_path: Path,
) -> None:
    local_path = tmp_path / "persistent-qdrant"
    settings = SimpleNamespace(
        embedding_model="jinaai/jina-embeddings-v3",
        embedding_dimension=1024,
        embedding_revision="1" * 40,
        embedding_code_revision="2" * 40,
        embedding_batch_size=8,
        qdrant_url=None,
        qdrant_path=local_path,
        qdrant_api_key=None,
        qdrant_timeout_seconds=3.0,
        qdrant_collection="legal-test-v1",
        index_version="test-v1",
    )

    binding = build_corpus_binding([_chunk("BOUND-LOCAL")])
    runtime = build_retrieval_runtime(settings, corpus_binding=binding)

    assert runtime.qdrant_store.path == local_path.resolve()
    assert runtime.qdrant_store.storage_mode == "embedded_local"
    assert runtime.qdrant_store.payload_indexes_enforced is False
    assert runtime.qdrant_store._client is None


def test_runtime_factory_propagates_competition_snapshot_mode(
    tmp_path: Path,
) -> None:
    settings = SimpleNamespace(
        embedding_model="jinaai/jina-embeddings-v3",
        embedding_dimension=1024,
        embedding_revision="1" * 40,
        embedding_code_revision="2" * 40,
        embedding_batch_size=8,
        qdrant_url=None,
        qdrant_path=tmp_path / "snapshot-qdrant",
        qdrant_api_key=None,
        qdrant_timeout_seconds=3.0,
        qdrant_collection="competition_snapshot_chunks_v1",
        corpus_mode=CorpusMode.COMPETITION_SNAPSHOT.value,
        index_version="snapshot-v1",
    )

    binding = build_corpus_binding([_chunk("BOUND-SNAPSHOT")])
    runtime = build_retrieval_runtime(settings, corpus_binding=binding)

    assert runtime.qdrant_store.corpus_mode == CorpusMode.COMPETITION_SNAPSHOT
    assert runtime.qdrant_store.collection_name == "competition_snapshot_chunks_v1"


def test_runtime_factory_fails_closed_without_corpus_binding() -> None:
    settings = SimpleNamespace(
        embedding_model="jinaai/jina-embeddings-v3",
        embedding_dimension=1024,
        embedding_revision="1" * 40,
        embedding_code_revision="2" * 40,
        embedding_batch_size=8,
        qdrant_url="http://qdrant.test:6333",
        qdrant_api_key=None,
        qdrant_timeout_seconds=3.0,
        qdrant_collection="legal-test-v1",
        index_version="test-v1",
    )

    with pytest.raises(RuntimeContractError, match="corpus binding"):
        build_retrieval_runtime(settings)
