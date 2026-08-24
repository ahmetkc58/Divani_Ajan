from __future__ import annotations

import math
import warnings
from collections.abc import Mapping, Sequence
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field

from karayol_agent.schemas import (
    LegislationChunk,
    RetrievalChannelContribution as ChannelContribution,
    SearchHit,
)


DEFAULT_CHANNEL_TOP_N = 20
DEFAULT_RRF_K = 60


class RankedRetriever(Protocol):
    """Minimal interface shared by BM25 and a dense-search adapter."""

    def search(self, query: str, top_k: int = 5) -> Sequence[SearchHit]: ...


class DenseRetrievalWarning(RuntimeWarning):
    """Dense retrieval could not run and lexical-only retrieval was used."""


class HybridSearchHit(SearchHit):
    """A ``SearchHit`` carrying the evidence used to produce its RRF score.

    ``score`` is always the fused RRF score. Raw lexical and dense scores are
    deliberately retained only in ``channel_contributions``; they never enter
    the fusion arithmetic.
    """

    fusion_method: Literal["rrf"] = "rrf"
    channel_contributions: list[ChannelContribution] = Field(default_factory=list)

    @property
    def fusion_score(self) -> float:
        return self.score

    def to_search_hit(self) -> SearchHit:
        """Return the exact legacy model when a strict boundary requires it."""

        return SearchHit(
            chunk=self.chunk,
            score=self.score,
            matched_terms=list(self.matched_terms),
            fusion_method=self.fusion_method,
            channel_contributions=list(self.channel_contributions),
        )


DenseStatus = Literal["used", "empty", "unavailable", "error"]


class HybridRetrievalDiagnostics(BaseModel):
    """Per-request channel health and candidate-count diagnostics."""

    model_config = ConfigDict(frozen=True)

    dense_status: DenseStatus
    fallback_used: bool
    warning: str | None = None
    dense_error_type: str | None = None
    lexical_candidate_count: int = Field(ge=0)
    dense_candidate_count: int = Field(ge=0)
    fused_candidate_count: int = Field(ge=0)
    channel_top_n: int = Field(ge=1)
    rrf_k: int = Field(ge=0)


class HybridSearchResponse(BaseModel):
    """Hybrid hits plus explicit diagnostics for the same search request."""

    hits: list[HybridSearchHit] = Field(default_factory=list)
    diagnostics: HybridRetrievalDiagnostics


def _channel_sort_key(channel: str) -> tuple[int, str]:
    # Prefer the existing lexical source as the canonical chunk representation
    # if two backends return the same stable chunk_id. All other ordering is
    # lexical so callers cannot affect ties through Mapping insertion order.
    priority = {"lexical": 0, "dense": 1}
    return priority.get(channel, 2), channel


def _validate_rrf_arguments(*, k: int, top_k: int | None) -> None:
    if isinstance(k, bool) or not isinstance(k, int) or k < 0:
        raise ValueError("RRF k must be a non-negative integer")
    if top_k is not None and (
        isinstance(top_k, bool) or not isinstance(top_k, int) or top_k < 0
    ):
        raise ValueError("top_k must be a non-negative integer or None")


def reciprocal_rank_fusion(
    rankings: Mapping[str, Sequence[SearchHit]],
    *,
    k: int = DEFAULT_RRF_K,
    top_k: int | None = None,
) -> list[HybridSearchHit]:
    """Fuse already-ranked channels with pure Reciprocal Rank Fusion.

    Each ``chunk_id`` contributes at most once per channel, using its first
    occurrence's one-based rank. Result ties are resolved solely by
    ``chunk_id``; raw backend scores are observable but have no sorting or
    arithmetic role.
    """

    _validate_rrf_arguments(k=k, top_k=top_k)

    chunks: dict[str, LegislationChunk] = {}
    matched_terms: dict[str, list[str]] = {}
    contributions: dict[str, list[ChannelContribution]] = {}
    fused_scores: dict[str, float] = {}

    for channel in sorted(rankings, key=_channel_sort_key):
        if not channel:
            raise ValueError("RRF channel names must not be empty")

        seen_in_channel: set[str] = set()
        for rank, hit in enumerate(rankings[channel], start=1):
            if not isinstance(hit, SearchHit):
                raise TypeError(
                    f"{channel} ranking item {rank} must be a SearchHit, "
                    f"got {type(hit).__name__}"
                )
            chunk_id = hit.chunk.chunk_id
            if chunk_id in seen_in_channel:
                continue
            seen_in_channel.add(chunk_id)

            raw_score = float(hit.score)
            if not math.isfinite(raw_score):
                raise ValueError(
                    f"{channel} ranking item {rank} has a non-finite raw score"
                )

            contribution = 1.0 / (k + rank)
            chunks.setdefault(chunk_id, hit.chunk)
            contributions.setdefault(chunk_id, []).append(
                ChannelContribution(
                    channel=channel,
                    rank=rank,
                    raw_score=raw_score,
                    rrf_contribution=contribution,
                )
            )
            fused_scores[chunk_id] = fused_scores.get(chunk_id, 0.0) + contribution

            terms = matched_terms.setdefault(chunk_id, [])
            for term in hit.matched_terms:
                if term not in terms:
                    terms.append(term)

    fused = [
        HybridSearchHit(
            chunk=chunks[chunk_id],
            score=fused_scores[chunk_id],
            matched_terms=matched_terms[chunk_id],
            channel_contributions=contributions[chunk_id],
        )
        for chunk_id in chunks
    ]
    fused.sort(key=lambda hit: (-hit.score, hit.chunk.chunk_id))
    return fused if top_k is None else fused[:top_k]


def fuse_lexical_and_dense(
    lexical_hits: Sequence[SearchHit],
    dense_hits: Sequence[SearchHit],
    *,
    k: int = DEFAULT_RRF_K,
    top_k: int | None = None,
) -> list[HybridSearchHit]:
    """Convenience wrapper for the project's two retrieval channels."""

    return reciprocal_rank_fusion(
        {"lexical": lexical_hits, "dense": dense_hits},
        k=k,
        top_k=top_k,
    )


class HybridRetriever:
    """Run independent lexical/dense searches and combine them with pure RRF."""

    def __init__(
        self,
        lexical_retriever: RankedRetriever,
        dense_retriever: RankedRetriever | None = None,
        *,
        channel_top_n: int = DEFAULT_CHANNEL_TOP_N,
        rrf_k: int = DEFAULT_RRF_K,
    ) -> None:
        if (
            isinstance(channel_top_n, bool)
            or not isinstance(channel_top_n, int)
            or channel_top_n < 1
        ):
            raise ValueError("channel_top_n must be a positive integer")
        _validate_rrf_arguments(k=rrf_k, top_k=None)

        self.lexical_retriever = lexical_retriever
        self.dense_retriever = dense_retriever
        self.channel_top_n = channel_top_n
        self.rrf_k = rrf_k

    def search(self, query: str, top_k: int = 5) -> list[HybridSearchHit]:
        """Drop-in ``BM25Index.search`` shape with richer ``SearchHit`` items."""

        return self.search_with_diagnostics(query, top_k=top_k).hits

    def search_as_search_hits(self, query: str, top_k: int = 5) -> list[SearchHit]:
        """Return exact legacy ``SearchHit`` instances for strict consumers."""

        return [hit.to_search_hit() for hit in self.search(query, top_k=top_k)]

    def search_with_diagnostics(
        self, query: str, top_k: int = 5
    ) -> HybridSearchResponse:
        _validate_rrf_arguments(k=self.rrf_k, top_k=top_k)

        lexical_hits = list(
            self.lexical_retriever.search(query, top_k=self.channel_top_n)
        )[: self.channel_top_n]

        dense_hits: list[SearchHit] = []
        warning_message: str | None = None
        dense_error_type: str | None = None
        if self.dense_retriever is None:
            dense_status: DenseStatus = "unavailable"
            warning_message = (
                "Dense retriever is not configured; using BM25-only fallback."
            )
        else:
            try:
                dense_hits = list(
                    self.dense_retriever.search(query, top_k=self.channel_top_n)
                )[: self.channel_top_n]
                dense_status = "used" if dense_hits else "empty"
            except Exception as exc:
                dense_status = "error"
                dense_error_type = type(exc).__name__
                warning_message = (
                    f"Dense retrieval failed ({dense_error_type}); "
                    "using BM25-only fallback."
                )

        if warning_message is not None:
            warnings.warn(
                warning_message,
                DenseRetrievalWarning,
                stacklevel=2,
            )

        # Validate/fuse dense data inside the guarded path as well. A backend
        # returning malformed hits is a dense-channel failure, not a reason to
        # take down the reliable BM25 fallback.
        try:
            fused_hits = fuse_lexical_and_dense(
                lexical_hits,
                dense_hits,
                k=self.rrf_k,
                top_k=top_k,
            )
        except (TypeError, ValueError) as exc:
            if dense_hits:
                dense_status = "error"
                dense_error_type = type(exc).__name__
                warning_message = (
                    f"Dense retrieval returned invalid results ({dense_error_type}); "
                    "using BM25-only fallback."
                )
                warnings.warn(
                    warning_message,
                    DenseRetrievalWarning,
                    stacklevel=2,
                )
                dense_hits = []
                fused_hits = fuse_lexical_and_dense(
                    lexical_hits,
                    dense_hits,
                    k=self.rrf_k,
                    top_k=top_k,
                )
            else:
                raise

        diagnostics = HybridRetrievalDiagnostics(
            dense_status=dense_status,
            fallback_used=dense_status in {"unavailable", "error"},
            warning=warning_message,
            dense_error_type=dense_error_type,
            lexical_candidate_count=len(lexical_hits),
            dense_candidate_count=len(dense_hits),
            fused_candidate_count=len(
                {hit.chunk.chunk_id for hit in [*lexical_hits, *dense_hits]}
            ),
            channel_top_n=self.channel_top_n,
            rrf_k=self.rrf_k,
        )
        return HybridSearchResponse(hits=fused_hits, diagnostics=diagnostics)


__all__ = [
    "ChannelContribution",
    "DEFAULT_CHANNEL_TOP_N",
    "DEFAULT_RRF_K",
    "DenseRetrievalWarning",
    "HybridRetrievalDiagnostics",
    "HybridRetriever",
    "HybridSearchHit",
    "HybridSearchResponse",
    "RankedRetriever",
    "fuse_lexical_and_dense",
    "reciprocal_rank_fusion",
]
