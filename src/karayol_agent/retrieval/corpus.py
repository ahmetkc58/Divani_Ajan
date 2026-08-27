"""Deterministic identity contract for an exact legislation chunk corpus."""

from __future__ import annotations

import json
import re
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass, field
from hashlib import sha256

from karayol_agent.schemas import LegislationChunk


_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


class CorpusBindingError(ValueError):
    """The supplied chunks cannot form an unambiguous corpus identity."""


@dataclass(frozen=True, slots=True)
class CorpusBinding:
    """Fingerprint plus exact IDs and canonical content digests represented by it."""

    fingerprint: str
    chunk_ids: tuple[str, ...]
    chunk_fingerprints: tuple[tuple[str, str], ...]
    # Cached lookup structures built once in __post_init__. ``upsert``/
    # ``dense_search`` call ``expected_chunk_fingerprint``/``allowed_chunk_ids``
    # once per chunk; rebuilding a dict/frozenset from ``chunk_fingerprints``/
    # ``chunk_ids`` on every call made large-corpus indexing effectively O(n^2).
    _chunk_fingerprint_index: dict[str, str] = field(
        default_factory=dict, repr=False, compare=False
    )
    _allowed_chunk_ids_cache: frozenset[str] = field(
        default_factory=frozenset, repr=False, compare=False
    )

    def __post_init__(self) -> None:
        normalized_fingerprint = self.fingerprint.strip().lower()
        if not _SHA256_PATTERN.fullmatch(normalized_fingerprint):
            raise CorpusBindingError("Corpus fingerprint geçerli bir SHA-256 değil.")
        normalized_ids = tuple(sorted(self.chunk_ids))
        if any(
            not isinstance(chunk_id, str) or not chunk_id.strip()
            for chunk_id in normalized_ids
        ):
            raise CorpusBindingError("Corpus binding boş bir chunk_id içeremez.")
        if len(set(normalized_ids)) != len(normalized_ids):
            raise CorpusBindingError("Corpus binding yinelenen chunk_id içeremez.")

        normalized_chunk_fingerprints: list[tuple[str, str]] = []
        for position, item in enumerate(self.chunk_fingerprints):
            if not isinstance(item, tuple) or len(item) != 2:
                raise CorpusBindingError(
                    "Corpus binding chunk_fingerprints öğeleri "
                    f"(chunk_id, sha256) çifti olmalıdır; konum={position}."
                )
            chunk_id, digest = item
            if not isinstance(chunk_id, str) or not chunk_id.strip():
                raise CorpusBindingError(
                    "Corpus binding boş bir chunk fingerprint kimliği içeremez."
                )
            if not isinstance(digest, str):
                raise CorpusBindingError(
                    f"{chunk_id} için chunk fingerprint metin olmalıdır."
                )
            normalized_digest = digest.strip().lower()
            if not _SHA256_PATTERN.fullmatch(normalized_digest):
                raise CorpusBindingError(
                    f"{chunk_id} için chunk fingerprint geçerli bir SHA-256 değil."
                )
            normalized_chunk_fingerprints.append((chunk_id, normalized_digest))

        normalized_chunk_fingerprints.sort(key=lambda item: item[0])
        fingerprint_ids = tuple(
            chunk_id for chunk_id, _ in normalized_chunk_fingerprints
        )
        if fingerprint_ids != normalized_ids:
            raise CorpusBindingError(
                "Corpus binding chunk_id listesi ile chunk fingerprint kimlikleri "
                "birebir eşleşmelidir."
            )
        object.__setattr__(self, "fingerprint", normalized_fingerprint)
        object.__setattr__(self, "chunk_ids", normalized_ids)
        object.__setattr__(
            self,
            "chunk_fingerprints",
            tuple(normalized_chunk_fingerprints),
        )
        object.__setattr__(
            self, "_chunk_fingerprint_index", dict(normalized_chunk_fingerprints)
        )
        object.__setattr__(self, "_allowed_chunk_ids_cache", frozenset(normalized_ids))

    @property
    def allowed_chunk_ids(self) -> frozenset[str]:
        """Return an immutable local allow-list for query-result validation."""

        return self._allowed_chunk_ids_cache

    def expected_chunk_fingerprint(self, chunk_id: str) -> str | None:
        """Return the bound canonical digest for ``chunk_id``, if it exists."""

        return self._chunk_fingerprint_index.get(chunk_id)


def canonical_chunk_json(chunk: LegislationChunk) -> str:
    """Serialize one complete legislation chunk canonically."""

    if not isinstance(chunk, LegislationChunk):
        raise TypeError(
            "chunk LegislationChunk olmalıdır; "
            f"{type(chunk).__name__} alındı."
        )
    return json.dumps(
        chunk.model_dump(mode="json"),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def chunk_fingerprint(chunk: LegislationChunk) -> str:
    """Return the SHA-256 identity of one complete canonical chunk."""

    return sha256(canonical_chunk_json(chunk).encode("utf-8")).hexdigest()


def canonical_corpus_json(chunks: Iterable[LegislationChunk]) -> str:
    """Serialize complete chunks canonically after sorting by ``chunk_id``."""

    legal_chunks = list(chunks)
    for position, chunk in enumerate(legal_chunks):
        if not isinstance(chunk, LegislationChunk):
            raise TypeError(
                f"chunks[{position}] LegislationChunk olmalıdır; "
                f"{type(chunk).__name__} alındı."
            )
    duplicate_ids = sorted(
        chunk_id
        for chunk_id, count in Counter(
            chunk.chunk_id for chunk in legal_chunks
        ).items()
        if count > 1
    )
    if duplicate_ids:
        raise CorpusBindingError(
            "Corpus fingerprint yinelenen chunk_id ile üretilemez: "
            + ", ".join(duplicate_ids)
            + "."
        )
    records = [
        chunk.model_dump(mode="json")
        for chunk in sorted(legal_chunks, key=lambda item: item.chunk_id)
    ]
    return json.dumps(
        records,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def build_corpus_binding(chunks: Iterable[LegislationChunk]) -> CorpusBinding:
    """Return the SHA-256 identity and exact IDs for ``chunks``."""

    legal_chunks = list(chunks)
    canonical_json = canonical_corpus_json(legal_chunks)
    return CorpusBinding(
        fingerprint=sha256(canonical_json.encode("utf-8")).hexdigest(),
        chunk_ids=tuple(chunk.chunk_id for chunk in legal_chunks),
        chunk_fingerprints=tuple(
            (chunk.chunk_id, chunk_fingerprint(chunk)) for chunk in legal_chunks
        ),
    )


__all__ = [
    "CorpusBinding",
    "CorpusBindingError",
    "build_corpus_binding",
    "canonical_corpus_json",
    "canonical_chunk_json",
    "chunk_fingerprint",
]
