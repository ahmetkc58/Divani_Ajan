from __future__ import annotations

from karayol_agent.retrieval import BM25Index
from karayol_agent.schemas import DocumentAnalysis, SearchHit, VerifiedReference
from karayol_agent.text_utils import truncate


class LegislationResearchAgent:
    name = "Mevzuat Araştırma Ajanı"

    def __init__(self, index: BM25Index, *, top_k: int = 5) -> None:
        self.index = index
        self.top_k = top_k

    def run(self, analysis: DocumentAnalysis) -> list[SearchHit]:
        query_parts = [
            analysis.document_type.replace("_", " "),
            analysis.summary,
            *analysis.keywords,
        ]
        subject = analysis.fields.get("konu")
        request = analysis.fields.get("talep")
        if subject and subject.value:
            query_parts.append(subject.value)
        if request and request.value:
            query_parts.append(request.value)
        return self.index.search(" ".join(query_parts), top_k=self.top_k)


class SourceVerificationAgent:
    name = "Kaynak Doğrulama Ajanı"

    def run(
        self, hits: list[SearchHit], analysis: DocumentAnalysis
    ) -> list[VerifiedReference]:
        if not hits:
            return []
        top_score = max(hit.score for hit in hits)
        verified: list[VerifiedReference] = []
        for hit in hits:
            relative_score = hit.score / top_score if top_score else 0.0
            has_evidence = len(hit.matched_terms) >= 1
            accepted = relative_score >= 0.30 and has_evidence
            note = (
                "Sorgu terimleri kaynak parçasında bulundu ve göreli skor eşiğini geçti."
                if accepted
                else "Kaynak parçası göreli skor veya terim eşleşmesi eşiğini geçemedi."
            )
            verified.append(
                VerifiedReference(
                    chunk_id=hit.chunk.chunk_id,
                    title=hit.chunk.title,
                    article=hit.chunk.article,
                    source=hit.chunk.source,
                    page=hit.chunk.page,
                    excerpt=truncate(hit.chunk.text, 360),
                    score=round(relative_score, 4),
                    verified=accepted,
                    verification_note=note,
                )
            )
        return verified

