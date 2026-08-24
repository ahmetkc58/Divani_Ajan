from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import pytest

from karayol_agent.retrieval.corpus import CorpusBinding, build_corpus_binding
from karayol_agent.retrieval.embeddings import EmbeddingMetadata, EmbeddingTask
from karayol_agent.retrieval.runtime import RuntimeContractError
from karayol_agent.retrieval.vector_indexing import (
    VectorIndexingError,
    VectorIndexingService,
    build_passage_text,
)
from karayol_agent.schemas import LegislationChunk


def _approved_chunk(index: int, *, context_text: str | None = None) -> LegislationChunk:
    return LegislationChunk(
        chunk_id=f"MEV-{index:03d}",
        document_id=f"UAB-{index:03d}",
        title=f"Test Yönetmeliği {index}",
        section="Birinci Bölüm",
        article=f"Madde {index}",
        paragraph="1",
        text=f"{index}. özgün mevzuat hükmü.\nİkinci satır korunur.",
        source=f"archive/{index}.pdf",
        source_url=f"https://example.test/mevzuat/{index}",
        source_sha256=f"{index % 16:x}" * 64,
        source_kind="public_legislation",
        page=1,
        page_end=1,
        document_type="yonetmelik",
        domain="kgm_infrastructure",
        subdomain="maintenance",
        validity_status="verified",
        approved_for_active_rag=True,
        ocr_status="text_layer_available",
        context_text=context_text or f"Yönetmelik {index} > Madde {index}",
        status="verified",
    )


class RecordingPassageProvider:
    model_name = "test/jina-compatible"
    dimension = 4
    model_revision = "weights-pin"
    code_revision = "code-pin"

    def __init__(self) -> None:
        self.passage_batches: list[list[str]] = []
        self.query_batches: list[list[str]] = []

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

    def embed_passages(self, texts: Sequence[str]) -> list[list[float]]:
        batch = list(texts)
        self.passage_batches.append(batch)
        return [[0.5, 0.5, 0.5, 0.5] for _ in batch]

    def embed_queries(self, texts: Sequence[str]) -> list[list[float]]:
        batch = list(texts)
        self.query_batches.append(batch)
        return [[0.5, 0.5, 0.5, 0.5] for _ in batch]


class RecordingIndexStore:
    embedding_model = RecordingPassageProvider.model_name
    embedding_dimension = RecordingPassageProvider.dimension
    embedding_model_revision = RecordingPassageProvider.model_revision
    embedding_code_revision = RecordingPassageProvider.code_revision
    passage_task = "retrieval.passage"
    query_task = "retrieval.query"
    collection_name = "legal-test-v1"
    index_version = "test-v1"

    def __init__(self) -> None:
        self.validated: list[str] = []
        self.upsert_calls: list[dict[str, Any]] = []
        self.corpus_binding: CorpusBinding | None = None

    def bind_corpus(self, binding: CorpusBinding) -> None:
        if self.corpus_binding is not None and self.corpus_binding != binding:
            raise ValueError("store farklı corpus binding'e bağlı")
        self.corpus_binding = binding

    def build_payload(self, chunk: LegislationChunk) -> dict[str, Any]:
        self.validated.append(chunk.chunk_id)
        if not chunk.approved_for_active_rag or chunk.validity_status != "verified":
            raise ValueError(f"{chunk.chunk_id} aktif indekse alınamaz")
        return {"chunk_id": chunk.chunk_id}

    def upsert(
        self,
        chunks: Sequence[LegislationChunk],
        vectors: Sequence[Sequence[float]],
        *,
        embedding_task: str = "retrieval.passage",
        wait: bool = True,
    ) -> int:
        chunk_list = list(chunks)
        vector_list = [list(vector) for vector in vectors]
        self.upsert_calls.append(
            {
                "chunk_ids": [chunk.chunk_id for chunk in chunk_list],
                "vectors": vector_list,
                "embedding_task": embedding_task,
                "wait": wait,
            }
        )
        return len(chunk_list)


def test_passage_text_is_context_then_original_without_rewriting_content() -> None:
    chunk = _approved_chunk(1, context_text="Belge > Bölüm > Madde 1")

    passage = build_passage_text(chunk)

    assert passage == (
        "Belge > Bölüm > Madde 1\n\n"
        "1. özgün mevzuat hükmü.\nİkinci satır korunur."
    )


def test_passage_text_requires_context_and_original_text() -> None:
    missing_context = _approved_chunk(1).model_copy(update={"context_text": "  "})
    missing_original = _approved_chunk(2).model_copy(update={"text": "  "})

    with pytest.raises(VectorIndexingError, match="context_text"):
        build_passage_text(missing_context)
    with pytest.raises(VectorIndexingError, match="original text"):
        build_passage_text(missing_original)


def test_indexing_batches_contextual_passages_and_persists_revision_report() -> None:
    chunks = [_approved_chunk(index) for index in range(1, 6)]
    provider = RecordingPassageProvider()
    store = RecordingIndexStore()
    service = VectorIndexingService(provider, store, batch_size=2)

    report = service.index_chunks(chunks, wait=False)

    assert store.validated == [chunk.chunk_id for chunk in chunks]
    assert [len(batch) for batch in provider.passage_batches] == [2, 2, 1]
    assert provider.passage_batches[0][0] == build_passage_text(chunks[0])
    assert [call["chunk_ids"] for call in store.upsert_calls] == [
        ["MEV-001", "MEV-002"],
        ["MEV-003", "MEV-004"],
        ["MEV-005"],
    ]
    assert all(
        call["embedding_task"] == "retrieval.passage"
        for call in store.upsert_calls
    )
    assert all(call["wait"] is False for call in store.upsert_calls)
    assert report.chunk_count == 5
    assert report.indexed_count == 5
    assert report.batch_count == 3
    assert report.embedding_model == provider.model_name
    assert report.embedding_dimension == 4
    assert report.embedding_model_revision == "weights-pin"
    assert report.embedding_code_revision == "code-pin"
    assert report.embedding_task == "retrieval.passage"
    assert report.collection_name == "legal-test-v1"
    assert report.index_version == "test-v1"
    assert report.corpus_fingerprint == build_corpus_binding(chunks).fingerprint
    assert store.corpus_binding == build_corpus_binding(chunks)


def test_entire_run_is_prevalidated_before_first_embedding_or_write() -> None:
    chunks = [
        _approved_chunk(1),
        _approved_chunk(2),
        _approved_chunk(3).model_copy(update={"approved_for_active_rag": False}),
    ]
    provider = RecordingPassageProvider()
    store = RecordingIndexStore()
    service = VectorIndexingService(provider, store, batch_size=2)

    with pytest.raises(ValueError, match="aktif indekse alınamaz"):
        service.index(chunks)

    assert store.validated == []
    assert provider.passage_batches == []
    assert store.upsert_calls == []
    assert store.corpus_binding is None


def test_duplicate_chunk_ids_fail_before_embedding_or_write() -> None:
    first = _approved_chunk(1)
    duplicate = _approved_chunk(2).model_copy(update={"chunk_id": first.chunk_id})
    provider = RecordingPassageProvider()
    store = RecordingIndexStore()

    with pytest.raises(VectorIndexingError, match="yinelenen chunk_id"):
        VectorIndexingService(provider, store).index([first, duplicate])

    assert store.validated == []
    assert provider.passage_batches == []
    assert store.upsert_calls == []
    assert store.corpus_binding is None


def test_indexing_rejects_store_revision_or_dimension_mismatch() -> None:
    provider = RecordingPassageProvider()
    store = RecordingIndexStore()
    store.embedding_code_revision = "different-code"

    with pytest.raises(RuntimeContractError, match="embedding_code_revision"):
        VectorIndexingService(provider, store).index([_approved_chunk(1)])

    assert provider.passage_batches == []
    assert store.validated == []


def test_empty_index_run_does_not_call_provider_or_store() -> None:
    provider = RecordingPassageProvider()
    store = RecordingIndexStore()

    report = VectorIndexingService(provider, store, batch_size=3).index([])

    assert report.chunk_count == 0
    assert report.indexed_count == 0
    assert report.batch_count == 0
    assert provider.passage_batches == []
    assert store.validated == []
    assert store.upsert_calls == []
    assert report.corpus_fingerprint == build_corpus_binding([]).fingerprint
