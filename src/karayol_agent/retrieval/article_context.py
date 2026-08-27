"""Retrieval-time expansion of a single chunk to its full legal article.

A ``LegislationChunk`` is fıkra/bent-sized (see
``karayol_agent.ingestion.chunker.LegalStructureChunker``), so a retrieval hit
that lands on a mid-article clause carries only that clause's text — not the
article's opening definition or its other paragraphs. This module groups the
active corpus by ``(document_id, article)`` once at startup so a hit can be
expanded to the full article text before it becomes a citation excerpt or an
LLM prompt candidate.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping

from karayol_agent.schemas import LegislationChunk

ArticleKey = tuple[str, str]
ArticleIndex = Mapping[ArticleKey, list[LegislationChunk]]


def build_article_index(chunks: Iterable[LegislationChunk]) -> ArticleIndex:
    """Group chunks by ``(document_id, article)``, preserving corpus order.

    Corpus order already reflects paragraph/clause reading order (chunks are
    emitted article-by-article, then paragraph-by-paragraph, then
    clause-by-clause), so no secondary sort is attempted here. Chunks with no
    ``document_id`` or ``article`` (unstructured/legacy corpora) are skipped;
    callers fall back to the single retrieved chunk's own text for those.
    """

    grouped: dict[ArticleKey, list[LegislationChunk]] = defaultdict(list)
    for chunk in chunks:
        if not chunk.document_id or not chunk.article:
            continue
        grouped[(chunk.document_id, chunk.article)].append(chunk)
    return grouped


def full_article_text(
    chunk: LegislationChunk, article_index: ArticleIndex | None
) -> str:
    """Return the stitched full-article text for ``chunk``.

    Falls back to ``chunk.text`` alone when the article/document is unknown
    or no sibling fragments are indexed (e.g. corpora not chunked by
    ``LegalStructureChunker``), so callers never need a special case.
    """

    if article_index is None or not chunk.document_id or not chunk.article:
        return chunk.text
    siblings = article_index.get((chunk.document_id, chunk.article))
    if not siblings:
        return chunk.text

    seen: set[str] = set()
    parts: list[str] = []
    for sibling in siblings:
        if sibling.chunk_id in seen:
            continue
        seen.add(sibling.chunk_id)
        parts.append(sibling.text)
    return "\n\n".join(parts)


__all__ = ["ArticleIndex", "ArticleKey", "build_article_index", "full_article_text"]
