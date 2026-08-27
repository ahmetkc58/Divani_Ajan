"""Verified immutable revisions used by remote-code model adapters."""

from __future__ import annotations

import re


# Hugging Face API üzerinden 24 Ağustos 2026 tarihinde doğrulandı. Jina v3
# auto_map kodu ayrı xlm-roberta-flash-implementation deposundan geldiği için
# model ve remote-code commitleri bilinçli olarak ayrıdır.
JINA_EMBEDDINGS_V3_REVISION = "ab036b023d30b4d1138c4c3bfa9f0c445ab455d6"
JINA_EMBEDDINGS_V3_CODE_REVISION = "bd55a5ec8e6c0fb1d6c26efb4b6a4a74ce8a88d3"

_FULL_COMMIT_PATTERN = re.compile(r"^[0-9a-fA-F]{40}$")


def require_full_commit(value: object, *, field_name: str) -> str:
    """Return a normalized full Git commit or fail closed."""

    if not isinstance(value, str) or not _FULL_COMMIT_PATTERN.fullmatch(value.strip()):
        raise ValueError(
            f"{field_name} doğrulanmış tam 40-hex Git commit'i olmalıdır."
        )
    return value.strip().lower()


__all__ = [
    "JINA_EMBEDDINGS_V3_CODE_REVISION",
    "JINA_EMBEDDINGS_V3_REVISION",
    "require_full_commit",
]
