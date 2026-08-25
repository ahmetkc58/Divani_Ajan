"""Batch indexing service for contextual legal passages in Qdrant."""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass

from karayol_agent.schemas import LegislationChunk

from .corpus import build_corpus_binding
from .embeddings import EmbeddingProvider
from .qdrant_store import QdrantStore
from .repository import LegislationRepository
from .runtime import validate_embedding_store_contract


class VectorIndexingError(ValueError):
    """A chunk batch cannot satisfy the contextual vector-index contract."""


@dataclass(frozen=True, slots=True)
class VectorIndexingReport:
    """Observable summary of one completed indexing run."""

    chunk_count: int
    indexed_count: int
    batch_count: int
    collection_name: str
    embedding_model: str
    embedding_dimension: int
    embedding_model_revision: str | None
    embedding_code_revision: str | None
    embedding_task: str
    index_version: str
    corpus_fingerprint: str


def build_passage_text(chunk: LegislationChunk) -> str:
    """Return the exact contextual input used for ``retrieval.passage``.

    ``context_text`` is synthetic search context and ``text`` remains the
    original, citable legal content. A blank context is rejected so an index run
    cannot silently mix contextual and non-contextual vector generations.
    """

    if not isinstance(chunk, LegislationChunk):
        raise TypeError("build_passage_text bir LegislationChunk bekler.")
    context_text = (chunk.context_text or "").strip()
    original_text = chunk.text.strip()
    if not context_text:
        raise VectorIndexingError(
            f"{chunk.chunk_id}: context_text olmadan contextual indeks oluşturulamaz."
        )
    if not original_text:
        raise VectorIndexingError(
            f"{chunk.chunk_id}: original text boş olamaz."
        )
    return f"{context_text}\n\n{original_text}"


class VectorIndexingService:
    """Prevalidate, passage-embed and upsert approved chunks in fixed batches."""

    def __init__(
        self,
        embedding_provider: EmbeddingProvider,
        vector_store: QdrantStore,
        *,
        batch_size: int = 16,
    ) -> None:
        if (
            isinstance(batch_size, bool)
            or not isinstance(batch_size, int)
            or batch_size < 1
        ):
            raise ValueError("batch_size pozitif bir tam sayı olmalıdır.")
        self.embedding_provider = embedding_provider
        self.vector_store = vector_store
        self.batch_size = batch_size

    def index_chunks(
        self,
        chunks: Iterable[LegislationChunk],
        *,
        wait: bool = True,
    ) -> VectorIndexingReport:
        """Index a fully validated run, avoiding embeddings before validation."""

        legal_chunks = list(chunks)
        for position, chunk in enumerate(legal_chunks):
            if not isinstance(chunk, LegislationChunk):
                raise TypeError(
                    f"chunks[{position}] LegislationChunk olmalıdır; "
                    f"{type(chunk).__name__} alındı."
                )

        chunk_ids = [chunk.chunk_id for chunk in legal_chunks]
        duplicate_ids = sorted(
            chunk_id for chunk_id, count in Counter(chunk_ids).items() if count > 1
        )
        if duplicate_ids:
            raise VectorIndexingError(
                "İndeksleme girdisinde yinelenen chunk_id var: "
                + ", ".join(duplicate_ids)
                + "."
            )

        validate_embedding_store_contract(
            self.embedding_provider,
            self.vector_store,
        )

        # Validate every record before binding the long-lived store, invoking an
        # expensive model, or allowing a partial Qdrant write.
        passage_texts: list[str] = []
        for chunk in legal_chunks:
            passage_texts.append(build_passage_text(chunk))
            blockers = LegislationRepository.public_chunk_blockers(chunk)
            if blockers:
                raise VectorIndexingError(
                    f"{chunk.chunk_id} aktif indekse alınamaz: "
                    + ", ".join(blockers)
                    + "."
                )

        corpus_binding = build_corpus_binding(legal_chunks)
        self.vector_store.bind_corpus(corpus_binding)
        for chunk in legal_chunks:
            self.vector_store.build_payload(chunk)

        indexed_count = 0
        batch_count = 0
        passage_task = _passage_task(self.embedding_provider)
        for start in range(0, len(legal_chunks), self.batch_size):
            batch_chunks = legal_chunks[start : start + self.batch_size]
            batch_texts = passage_texts[start : start + self.batch_size]
            vectors = list(self.embedding_provider.embed_passages(batch_texts))
            if len(vectors) != len(batch_chunks):
                raise VectorIndexingError(
                    "EmbeddingProvider batch sayısı uyuşmuyor: "
                    f"beklenen={len(batch_chunks)}, alınan={len(vectors)}."
                )
            upserted = self.vector_store.upsert(
                batch_chunks,
                vectors,
                embedding_task=passage_task,
                wait=wait,
            )
            if upserted != len(batch_chunks):
                raise VectorIndexingError(
                    "Qdrant upsert sayısı uyuşmuyor: "
                    f"beklenen={len(batch_chunks)}, alınan={upserted}."
                )
            indexed_count += upserted
            batch_count += 1

        passage_metadata = self.embedding_provider.passage_metadata
        return VectorIndexingReport(
            chunk_count=len(legal_chunks),
            indexed_count=indexed_count,
            batch_count=batch_count,
            collection_name=self.vector_store.collection_name,
            embedding_model=passage_metadata.model_name,
            embedding_dimension=passage_metadata.dimension,
            embedding_model_revision=passage_metadata.model_revision,
            embedding_code_revision=passage_metadata.code_revision,
            embedding_task=passage_task,
            index_version=self.vector_store.index_version,
            corpus_fingerprint=corpus_binding.fingerprint,
        )

    def index(
        self,
        chunks: Iterable[LegislationChunk],
        *,
        wait: bool = True,
    ) -> VectorIndexingReport:
        """Short alias for callers such as an ingestion command."""

        return self.index_chunks(chunks, wait=wait)


def _passage_task(provider: EmbeddingProvider) -> str:
    task = provider.passage_metadata.task
    return str(getattr(task, "value", task))


BatchVectorIndexingService = VectorIndexingService


__all__ = [
    "BatchVectorIndexingService",
    "VectorIndexingError",
    "VectorIndexingReport",
    "VectorIndexingService",
    "build_passage_text",
]
