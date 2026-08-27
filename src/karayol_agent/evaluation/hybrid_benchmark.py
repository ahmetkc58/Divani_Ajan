"""Isolated Jina/Qdrant benchmark wiring for the frozen synthetic gold set.

This module intentionally does not relax :class:`QdrantStore` or the public
legislation repository.  Synthetic demo rules are written only to a collection
whose name starts with ``benchmark_`` and remain labelled as synthetic in the
payload.  The resulting retriever is suitable for offline ablation reports,
never for production legal evidence.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from hashlib import sha256
from importlib import import_module
from pathlib import Path
from time import perf_counter
from typing import Any
from uuid import uuid4

from karayol_agent.retrieval.bm25 import BM25Index
from karayol_agent.retrieval.corpus import build_corpus_binding
from karayol_agent.retrieval.embeddings import EmbeddingProvider
from karayol_agent.retrieval.hybrid import HybridRetriever
from karayol_agent.retrieval.qdrant_store import stable_point_id
from karayol_agent.retrieval.repository import (
    LegislationRepository,
    RepositoryApprovalError,
)
from karayol_agent.retrieval.vector_indexing import build_passage_text
from karayol_agent.schemas import LegislationChunk, SearchHit


class SyntheticBenchmarkError(RuntimeError):
    """The isolated synthetic benchmark cannot be prepared or queried."""


@dataclass(frozen=True, slots=True)
class SyntheticBenchmarkIndexReport:
    collection_name: str
    chunk_count: int
    embedding_model: str
    embedding_dimension: int
    embedding_model_revision: str | None
    embedding_code_revision: str | None
    passage_task: str
    query_task: str
    corpus_fingerprint: str
    corpus_source_path: str | None
    corpus_source_sha256: str | None
    index_seconds: float
    benchmark_only: bool = True


@dataclass(frozen=True, slots=True)
class SyntheticHybridBenchmarkRuntime:
    retriever: HybridRetriever
    dense_retriever: "SyntheticQdrantDenseRetriever"
    index_report: SyntheticBenchmarkIndexReport


class SyntheticQdrantDenseRetriever:
    """Real Qdrant dense search with a hard synthetic-benchmark boundary."""

    benchmark_only = True
    production_safe = False

    def __init__(
        self,
        chunks: list[LegislationChunk],
        embedding_provider: EmbeddingProvider,
        *,
        client: Any | None = None,
        models_module: Any | None = None,
        qdrant_path: Path | None = None,
        collection_name: str | None = None,
        corpus_source_path: str | None = None,
        corpus_source_sha256: str | None = None,
    ) -> None:
        if not chunks:
            raise SyntheticBenchmarkError("Sentetik benchmark korpusu boş olamaz.")
        self._validate_chunks(chunks)

        resolved_collection = collection_name or (
            f"benchmark_synthetic_legal_{uuid4().hex}"
        )
        if not resolved_collection.startswith("benchmark_"):
            raise SyntheticBenchmarkError(
                "Sentetik koleksiyon adı güvenlik için 'benchmark_' ile başlamalıdır."
            )

        self.embedding_provider = embedding_provider
        self.collection_name = resolved_collection
        self._models = models_module or self._load_qdrant_models()
        self._owns_client = client is None
        self.client = client or self._build_local_client(qdrant_path)
        self._chunks = {chunk.chunk_id: chunk for chunk in chunks}
        corpus_binding = build_corpus_binding(chunks)
        self.query_count = 0
        self.query_seconds = 0.0

        started = perf_counter()
        self._create_collection()
        passages = [build_passage_text(chunk) for chunk in chunks]
        vectors = embedding_provider.embed_passages(passages)
        if len(vectors) != len(chunks):
            raise SyntheticBenchmarkError(
                "Passage embedding sayısı benchmark chunk sayısıyla eşleşmiyor."
            )
        points = [
            self._models.PointStruct(
                id=stable_point_id(chunk.chunk_id),
                vector=vector,
                payload={
                    "benchmark_only": True,
                    "source_kind": "synthetic",
                    "corpus_fingerprint": corpus_binding.fingerprint,
                    "chunk": chunk.model_dump(mode="json"),
                },
            )
            for chunk, vector in zip(chunks, vectors, strict=True)
        ]
        try:
            self.client.upsert(
                collection_name=self.collection_name,
                points=points,
                wait=True,
            )
        except Exception as exc:
            raise SyntheticBenchmarkError(
                "Sentetik benchmark noktaları Qdrant'a yazılamadı."
            ) from exc

        self.index_report = SyntheticBenchmarkIndexReport(
            collection_name=self.collection_name,
            chunk_count=len(chunks),
            embedding_model=embedding_provider.model_name,
            embedding_dimension=embedding_provider.dimension,
            embedding_model_revision=embedding_provider.passage_metadata.model_revision,
            embedding_code_revision=embedding_provider.passage_metadata.code_revision,
            passage_task=embedding_provider.passage_metadata.task.value,
            query_task=embedding_provider.query_metadata.task.value,
            corpus_fingerprint=corpus_binding.fingerprint,
            corpus_source_path=corpus_source_path,
            corpus_source_sha256=corpus_source_sha256,
            index_seconds=round(perf_counter() - started, 6),
        )

    def search(self, query: str, top_k: int = 5) -> list[SearchHit]:
        if isinstance(top_k, bool) or not isinstance(top_k, int) or top_k < 0:
            raise ValueError("top_k negatif olmayan bir tam sayı olmalıdır.")
        if top_k == 0 or not query.strip():
            return []

        started = perf_counter()
        query_vector = self.embedding_provider.embed_queries([query])[0]
        try:
            response = self.client.query_points(
                collection_name=self.collection_name,
                query=query_vector,
                limit=top_k,
                with_payload=True,
            )
        except Exception as exc:
            raise SyntheticBenchmarkError(
                "Sentetik benchmark Qdrant sorgusu çalıştırılamadı."
            ) from exc
        finally:
            self.query_count += 1
            self.query_seconds += perf_counter() - started

        points = getattr(response, "points", response)
        hits: list[SearchHit] = []
        for point in points:
            payload = getattr(point, "payload", None) or {}
            if payload.get("benchmark_only") is not True:
                raise SyntheticBenchmarkError(
                    "Qdrant sonucu benchmark_only güvenlik işaretini taşımıyor."
                )
            if payload.get("source_kind") != "synthetic":
                raise SyntheticBenchmarkError(
                    "Qdrant benchmark sonucunda sentetik olmayan kaynak bulundu."
                )
            if payload.get("corpus_fingerprint") != self.index_report.corpus_fingerprint:
                raise SyntheticBenchmarkError(
                    "Qdrant benchmark sonucu farklı corpus parmak izi taşıyor."
                )
            try:
                chunk = LegislationChunk.model_validate(payload["chunk"])
                score = float(getattr(point, "score"))
            except (KeyError, TypeError, ValueError) as exc:
                raise SyntheticBenchmarkError(
                    "Qdrant benchmark sonucu geçersiz payload/skor taşıyor."
                ) from exc
            if chunk.chunk_id not in self._chunks or not math.isfinite(score):
                raise SyntheticBenchmarkError(
                    "Qdrant benchmark sonucu indeks sözleşmesiyle eşleşmiyor."
                )
            hits.append(SearchHit(chunk=chunk, score=score))
        return hits

    def close(self) -> None:
        if not self._owns_client:
            return
        close = getattr(self.client, "close", None)
        if callable(close):
            close()

    def _create_collection(self) -> None:
        try:
            self.client.create_collection(
                collection_name=self.collection_name,
                vectors_config=self._models.VectorParams(
                    size=self.embedding_provider.dimension,
                    distance=self._models.Distance.COSINE,
                ),
            )
        except Exception as exc:
            raise SyntheticBenchmarkError(
                "İzole sentetik Qdrant koleksiyonu oluşturulamadı."
            ) from exc

    @staticmethod
    def _validate_chunks(chunks: list[LegislationChunk]) -> None:
        seen: set[str] = set()
        for chunk in chunks:
            if chunk.chunk_id in seen:
                raise SyntheticBenchmarkError(
                    f"Yinelenen sentetik chunk kimliği: {chunk.chunk_id}."
                )
            seen.add(chunk.chunk_id)
            if (
                chunk.source_kind != "synthetic"
                or chunk.status != "sentetik_demo_kurali"
            ):
                raise SyntheticBenchmarkError(
                    f"{chunk.chunk_id}: yalnız açıkça sentetik demo kuralı "
                    "benchmark koleksiyonuna alınabilir."
                )
            if not (chunk.context_text or "").strip():
                raise SyntheticBenchmarkError(
                    f"{chunk.chunk_id}: contextual benchmark için context_text gerekli."
                )

    @staticmethod
    def _load_qdrant_models() -> Any:
        try:
            return import_module("qdrant_client.models")
        except Exception as exc:
            raise SyntheticBenchmarkError(
                "qdrant-client benchmark bağımlılığı kurulu değil."
            ) from exc

    @staticmethod
    def _build_local_client(qdrant_path: Path | None) -> Any:
        try:
            client_type = getattr(import_module("qdrant_client"), "QdrantClient")
            if qdrant_path is None:
                return client_type(location=":memory:")
            resolved = qdrant_path.resolve()
            resolved.mkdir(parents=True, exist_ok=True)
            return client_type(path=str(resolved))
        except Exception as exc:
            raise SyntheticBenchmarkError(
                "Yerel Qdrant benchmark istemcisi oluşturulamadı."
            ) from exc


def contextualize_synthetic_chunks(
    chunks: list[LegislationChunk],
) -> list[LegislationChunk]:
    """Add deterministic structural context without changing citable text."""

    contextualized: list[LegislationChunk] = []
    for chunk in chunks:
        context = " > ".join(
            value.strip()
            for value in (chunk.title, chunk.section, chunk.article or "")
            if value and value.strip()
        )
        contextualized.append(chunk.model_copy(update={"context_text": context}))
    return contextualized


def build_synthetic_hybrid_benchmark(
    *,
    legislation_path: Path,
    embedding_provider: EmbeddingProvider,
    client: Any | None = None,
    models_module: Any | None = None,
    qdrant_path: Path | None = None,
    collection_name: str | None = None,
    channel_top_n: int = 20,
    rrf_k: int = 60,
) -> SyntheticHybridBenchmarkRuntime:
    """Build a real Jina/Qdrant + BM25 benchmark over trusted synthetic data."""

    try:
        chunks = LegislationRepository(
            legislation_path,
            trusted_synthetic=True,
        ).load()
    except RepositoryApprovalError as exc:
        raise SyntheticBenchmarkError(
            "Sentetik benchmark korpusu güven sınırını karşılamıyor."
        ) from exc
    contextual_chunks = contextualize_synthetic_chunks(chunks)
    dense = SyntheticQdrantDenseRetriever(
        contextual_chunks,
        embedding_provider,
        client=client,
        models_module=models_module,
        qdrant_path=qdrant_path,
        collection_name=collection_name,
        corpus_source_path=_portable_source_path(legislation_path),
        corpus_source_sha256=_file_sha256(legislation_path),
    )
    retriever = HybridRetriever(
        BM25Index(contextual_chunks),
        dense,
        channel_top_n=channel_top_n,
        rrf_k=rrf_k,
    )
    return SyntheticHybridBenchmarkRuntime(
        retriever=retriever,
        dense_retriever=dense,
        index_report=dense.index_report,
    )


def _file_sha256(path: Path) -> str:
    digest = sha256()
    try:
        with path.resolve().open("rb") as source:
            for block in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(block)
    except OSError as exc:
        raise SyntheticBenchmarkError(
            f"Sentetik benchmark corpus hash'i okunamadı: {path}."
        ) from exc
    return digest.hexdigest()


def _portable_source_path(path: Path) -> str:
    resolved = path.resolve()
    project_root = Path(__file__).resolve().parents[3]
    try:
        return resolved.relative_to(project_root).as_posix()
    except ValueError:
        return resolved.name


__all__ = [
    "SyntheticBenchmarkError",
    "SyntheticBenchmarkIndexReport",
    "SyntheticHybridBenchmarkRuntime",
    "SyntheticQdrantDenseRetriever",
    "build_synthetic_hybrid_benchmark",
    "contextualize_synthetic_chunks",
]
