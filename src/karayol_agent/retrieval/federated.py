"""Federated retrieval for embedding-incompatible legal corpora."""

from __future__ import annotations

import math
import time
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import httpx

from karayol_agent.schemas import (
    DocumentAnalysis,
    LegislationChunk,
    RetrievalDiagnostics,
    SearchHit,
)

from .hybrid import reciprocal_rank_fusion


EXTERNAL_COLLECTION = "legal_chunks_direct"
EXTERNAL_EMBEDDING_MODEL = "bge-m3-embed"
EXTERNAL_EMBEDDING_DIMENSION = 1024


@dataclass(frozen=True, slots=True)
class FederatedSearchResponse:
    hits: list[SearchHit]
    diagnostics: RetrievalDiagnostics


class EvrenQueryEmbeddingClient:
    """OpenAI-compatible query embedding client for EVREN."""

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model: str = EXTERNAL_EMBEDDING_MODEL,
        dimension: int = EXTERNAL_EMBEDDING_DIMENSION,
        timeout: float = 60.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.dimension = dimension
        self.timeout = timeout

    def embed_query(self, text: str) -> list[float]:
        if not text.strip():
            raise ValueError("Embedding sorgusu boş olamaz.")
        last_error: Exception | None = None
        for attempt in range(3):
            try:
                response = httpx.post(
                    f"{self.base_url}/embeddings",
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json",
                    },
                    json={"model": self.model, "input": [text]},
                    timeout=self.timeout,
                )
                response.raise_for_status()
                vector = response.json()["data"][0]["embedding"]
                values = [float(value) for value in vector]
                if len(values) != self.dimension or not all(
                    math.isfinite(value) for value in values
                ):
                    raise ValueError(
                        "EVREN embedding yanıtı 1024 boyutlu sonlu bir vektör değil."
                    )
                return values
            except (httpx.HTTPError, KeyError, TypeError, ValueError) as exc:
                last_error = exc
                if attempt < 2:
                    time.sleep(1.5 * (2**attempt))
        raise RuntimeError("EVREN BGE-M3 embedding isteği başarısız.") from last_error


class RemoteExternalDenseRetriever:
    """Query the transformed shared snapshot without loading its large JSON."""

    retrieval_mode = "dense"

    def __init__(
        self,
        *,
        embedding_client: EvrenQueryEmbeddingClient,
        qdrant_url: str,
        qdrant_prefix: str,
        qdrant_api_key: str,
        corpus_fingerprint: str,
        collection_name: str = EXTERNAL_COLLECTION,
        timeout: float = 60.0,
        client: Any | None = None,
    ) -> None:
        self.embedding_client = embedding_client
        self.qdrant_url = qdrant_url
        self.qdrant_prefix = qdrant_prefix
        self.qdrant_api_key = qdrant_api_key
        self.corpus_fingerprint = corpus_fingerprint
        self.collection_name = collection_name
        self.timeout = timeout
        self._client = client

    @property
    def client(self) -> Any:
        if self._client is None:
            from qdrant_client import QdrantClient

            self._client = QdrantClient(
                url=self.qdrant_url,
                port=443,
                prefix=self.qdrant_prefix,
                api_key=self.qdrant_api_key,
                timeout=self.timeout,
                prefer_grpc=False,
            )
        return self._client

    def search(self, query: str, top_k: int = 20) -> list[SearchHit]:
        if top_k < 1:
            raise ValueError("top_k pozitif olmalıdır.")
        vector = self.embedding_client.embed_query(query)

        response = self.client.query_points(
            collection_name=self.collection_name,
            query=vector,
            # The uploaded source contains exact duplicate rows that share a
            # transformed chunk_id. Over-fetch, then keep the best point for
            # each logical chunk so one document cannot crowd out the list.
            limit=min(top_k * 4, 250),
            with_payload=True,
            with_vectors=False,
        )
        points = getattr(response, "points", response)
        hits: list[SearchHit] = []
        seen_chunk_ids: set[str] = set()
        for point in points:
            payload = getattr(point, "payload", None)
            if not isinstance(payload, Mapping):
                continue
            if (
                payload.get("corpus_fingerprint") != self.corpus_fingerprint
                or payload.get("source_kind") != "competition_snapshot"
            ):
                continue
            score = float(getattr(point, "score"))
            chunk_id = str(payload.get("chunk_id", ""))
            if math.isfinite(score) and chunk_id not in seen_chunk_ids:
                seen_chunk_ids.add(chunk_id)
                hits.append(
                    SearchHit(chunk=self._chunk_from_payload(payload), score=score)
                )
                if len(hits) >= top_k:
                    break
        return hits

    def validate_readiness(self) -> dict[str, object]:
        info = self.client.get_collection(self.collection_name)
        params = getattr(getattr(info, "config", None), "params", None)
        vectors = getattr(params, "vectors", None)
        size = getattr(vectors, "size", None)
        points_count = int(getattr(info, "points_count", 0) or 0)
        if size != EXTERNAL_EMBEDDING_DIMENSION:
            raise ValueError(
                f"{self.collection_name} vektör boyutu uyuşmuyor: {size}."
            )
        if points_count < 1:
            raise ValueError(f"{self.collection_name} boş.")
        return {
            "name": self.collection_name,
            "point_count": points_count,
            "embedding_model": self.embedding_client.model,
            "embedding_dimension": size,
            "storage_mode": "remote",
        }

    @staticmethod
    def _chunk_from_payload(payload: Mapping[str, Any]) -> LegislationChunk:
        values = {
            name: payload.get(name)
            for name in LegislationChunk.model_fields
            if name in payload
        }
        values["source"] = payload.get("source_path", payload.get("source", ""))
        values["text"] = payload.get("original_text", payload.get("text", ""))
        return LegislationChunk.model_validate(values)


class FederatedAnalysisRetriever:
    """Fuse local UAB and remote external ranks without mixing vector spaces."""

    analysis_aware = True
    retrieval_mode = "hybrid"

    def __init__(
        self,
        primary_retriever: Any,
        external_retriever: RemoteExternalDenseRetriever,
        *,
        channel_top_n: int = 40,
        rrf_k: int = 60,
    ) -> None:
        self.primary_retriever = primary_retriever
        self.external_retriever = external_retriever
        self.channel_top_n = channel_top_n
        self.rrf_k = rrf_k
        self.lexical_retriever = getattr(primary_retriever, "lexical_retriever", None)

    def search_for_analysis(
        self,
        query: str,
        analysis: DocumentAnalysis | Mapping[str, Any],
        top_k: int = 5,
    ) -> FederatedSearchResponse:
        candidate_count = max(top_k, self.channel_top_n)
        primary_response = self.primary_retriever.search_for_analysis(
            query, analysis, top_k=candidate_count
        )
        primary_hits = list(getattr(primary_response, "hits", primary_response))
        primary_diagnostics = getattr(primary_response, "diagnostics", None)

        external_hits: list[SearchHit] = []
        external_error: Exception | None = None
        try:
            external_hits = self.external_retriever.search(
                query, top_k=candidate_count
            )
        except Exception as exc:  # remote failure deliberately falls back locally
            external_error = exc

        fused = reciprocal_rank_fusion(
            {"lexical": primary_hits, "dense": external_hits},
            k=self.rrf_k,
            top_k=top_k,
        )
        warnings = [
            value
            for value in (getattr(primary_diagnostics, "warning", None),)
            if value
        ]
        if external_error is not None:
            warnings.append(
                "Uzak dış korpus kullanılamadı "
                f"({type(external_error).__name__}); UAB sonuçları kullanıldı."
            )
        diagnostics = RetrievalDiagnostics(
            mode="hybrid",
            dense_status=(
                "error"
                if external_error is not None
                else ("used" if external_hits else "empty")
            ),
            fallback_used=external_error is not None,
            warning=" ".join(warnings) or None,
            dense_error_type=(type(external_error).__name__ if external_error else None),
            lexical_candidate_count=len(primary_hits),
            dense_candidate_count=len(external_hits),
            fused_candidate_count=len(
                {hit.chunk.chunk_id for hit in [*primary_hits, *external_hits]}
            ),
            channel_top_n=self.channel_top_n,
            rrf_k=self.rrf_k,
        )
        return FederatedSearchResponse(
            hits=[hit.to_search_hit() for hit in fused], diagnostics=diagnostics
        )

    def federated_readiness(self) -> dict[str, object]:
        primary_store = getattr(self.primary_retriever, "vector_store", None)
        if primary_store is None:
            raise ValueError("UAB vektör deposu bulunamadı.")
        primary = primary_store.validate_readiness()
        external = self.external_retriever.validate_readiness()
        return {
            "ready": True,
            "retrieval_mode": "hybrid_federated",
            "detail": (
                f"İki korpus hazır: UAB {primary.compatible_point_count} nokta, "
                f"uzak dış korpus {external['point_count']} nokta."
            ),
            "collections": [
                {
                    "name": primary.collection_name,
                    "point_count": primary.compatible_point_count,
                    "embedding_model": primary.embedding_model,
                    "storage_mode": primary.storage_mode,
                },
                external,
            ],
        }


__all__ = [
    "EvrenQueryEmbeddingClient",
    "FederatedAnalysisRetriever",
    "FederatedSearchResponse",
    "RemoteExternalDenseRetriever",
]
