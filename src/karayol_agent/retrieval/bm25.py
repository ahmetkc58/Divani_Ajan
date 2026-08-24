from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass

from karayol_agent.schemas import LegislationChunk, SearchHit
from karayol_agent.text_utils import tokenize


_STOP_WORDS = {
    "acaba", "adı", "ama", "ancak", "bir", "bu", "da", "de", "daha", "en",
    "gibi", "ile", "için", "ise", "mi", "mı", "mu", "mü", "ne", "olarak",
    "olan", "ve", "veya", "şu", "çok", "tarafından",
}


def _search_tokens(value: str) -> list[str]:
    return [token for token in tokenize(value) if token not in _STOP_WORDS and len(token) > 1]


@dataclass(slots=True)
class _IndexedDocument:
    chunk: LegislationChunk
    tokens: list[str]
    frequencies: Counter[str]


class BM25Index:
    """Küçük/orta MVP koleksiyonları için bağımlılıksız Okapi BM25."""

    retrieval_mode = "bm25"

    def __init__(
        self,
        chunks: list[LegislationChunk],
        *,
        k1: float = 1.5,
        b: float = 0.75,
    ) -> None:
        self.k1 = k1
        self.b = b
        self.documents: list[_IndexedDocument] = []
        self.document_frequency: Counter[str] = Counter()

        for chunk in chunks:
            searchable = " ".join(
                [
                    chunk.context_text or "",
                    chunk.title,
                    chunk.section,
                    chunk.article or "",
                    chunk.text,
                    *chunk.tags,
                ]
            )
            tokens = _search_tokens(searchable)
            frequencies = Counter(tokens)
            self.documents.append(_IndexedDocument(chunk, tokens, frequencies))
            self.document_frequency.update(frequencies.keys())

        self.average_length = (
            sum(len(document.tokens) for document in self.documents) / len(self.documents)
            if self.documents
            else 0.0
        )

    def search(self, query: str, top_k: int = 5) -> list[SearchHit]:
        query_terms = list(dict.fromkeys(_search_tokens(query)))
        if not query_terms or not self.documents:
            return []

        scored: list[SearchHit] = []
        document_count = len(self.documents)
        for document in self.documents:
            score = 0.0
            matched_terms: list[str] = []
            doc_length = max(len(document.tokens), 1)
            for term in query_terms:
                frequency = document.frequencies.get(term, 0)
                if not frequency:
                    continue
                matched_terms.append(term)
                doc_frequency = self.document_frequency[term]
                inverse_document_frequency = math.log(
                    1 + (document_count - doc_frequency + 0.5) / (doc_frequency + 0.5)
                )
                denominator = frequency + self.k1 * (
                    1 - self.b + self.b * doc_length / max(self.average_length, 1)
                )
                score += inverse_document_frequency * (
                    frequency * (self.k1 + 1) / denominator
                )
            if score > 0:
                scored.append(
                    SearchHit(
                        chunk=document.chunk,
                        score=round(score, 6),
                        matched_terms=matched_terms,
                    )
                )

        scored.sort(key=lambda hit: (-hit.score, hit.chunk.chunk_id))
        return scored[:top_k]
