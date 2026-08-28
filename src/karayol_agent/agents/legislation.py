from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from karayol_agent.retrieval.contracts import (
    COMPETITION_SNAPSHOT_NOTICE,
    CorpusMode,
    competition_snapshot_chunk_blockers,
)
from karayol_agent.retrieval.repository import LegislationRepository
from karayol_agent.retrieval.runtime import build_analysis_query
from karayol_agent.schemas import (
    DocumentAnalysis,
    LegislationChunk,
    RetrievalDiagnostics,
    SearchHit,
    VerifiedReference,
)
from karayol_agent.text_utils import truncate


class RankedRetriever(Protocol):
    """Minimal interface implemented by the legacy BM25 index."""

    def search(self, query: str, top_k: int = 5) -> Sequence[SearchHit]: ...


@dataclass(frozen=True, slots=True)
class LegislationSearchResult:
    hits: list[SearchHit]
    diagnostics: RetrievalDiagnostics


@dataclass(frozen=True, slots=True)
class _SourceDecision:
    trusted: bool
    note: str
    corpus_mode: str
    currentness_verified: bool
    legal_reliance_allowed: bool
    usage_notice: str | None = None


class LegislationResearchAgent:
    name = "Mevzuat Araştırma Ajanı (Researcher)"

    def __init__(self, index: RankedRetriever, *, top_k: int = 5) -> None:
        # ``index`` remains as a compatibility attribute for existing callers.
        self.index = index
        self.retriever = index
        self.top_k = top_k

    def run(self, analysis: DocumentAnalysis) -> list[SearchHit]:
        """Preserve the legacy list-returning API used by evaluation code."""

        return self.run_with_diagnostics(analysis).hits

    def run_with_diagnostics(
        self, analysis: DocumentAnalysis
    ) -> LegislationSearchResult:
        query = self._query_for(analysis)
        return self._search(query, analysis)

    def run_requirements_with_diagnostics(
        self, analysis: DocumentAnalysis
    ) -> LegislationSearchResult:
        """Retrieve type-specific writing, signature and mandatory-field rules."""

        base_query = self._query_for(analysis)
        type_rule_terms = {
            "ust_yazi": (
                "resmi yazışma zorunlu alanlar şekil şartları tarih sayı konu "
                "muhatap imza ek dağıtım"
            ),
            "dilekce": "dilekçe zorunlu unsurlar tarih imza başvuran makam",
        }.get(analysis.general_document_type)
        query = f"{base_query} {type_rule_terms}" if type_rule_terms else base_query
        return self._search(query, analysis)

    def search_query_with_diagnostics(
        self, query: str, analysis: DocumentAnalysis
    ) -> LegislationSearchResult:
        """Run a caller-supplied, analysis-scoped query for bounded agentic search."""

        return self._search(query, analysis)

    def _search(
        self,
        query: str,
        analysis: DocumentAnalysis,
    ) -> LegislationSearchResult:
        search_for_analysis = getattr(self.retriever, "search_for_analysis", None)
        search_with_diagnostics = getattr(
            self.retriever, "search_with_diagnostics", None
        )
        if callable(search_for_analysis):
            response = search_for_analysis(query, analysis, top_k=self.top_k)
        elif callable(search_with_diagnostics):
            # Runtime AnalysisAwareHybridRetriever exposes ``bind`` and accepts
            # the structured analysis. A direct HybridRetriever accepts text.
            search_input: DocumentAnalysis | str = (
                analysis
                if callable(getattr(self.retriever, "bind", None))
                or getattr(self.retriever, "expects_analysis", False)
                else query
            )
            response = search_with_diagnostics(search_input, top_k=self.top_k)
        else:
            response = self.retriever.search(query, top_k=self.top_k)
        return self._coerce_result(response)

    @staticmethod
    def _query_for(analysis: DocumentAnalysis) -> str:
        return build_analysis_query(analysis)

    def _coerce_result(self, response: Any) -> LegislationSearchResult:
        response_hits = getattr(response, "hits", None)
        raw_diagnostics = getattr(response, "diagnostics", None)
        if response_hits is None:
            try:
                hits = list(response)
            except TypeError as exc:
                raise TypeError(
                    "Retriever bir hit listesi veya tanılı sonuç döndürmeli."
                ) from exc
        else:
            hits = list(response_hits)

        for position, hit in enumerate(hits, start=1):
            if not isinstance(hit, SearchHit):
                raise TypeError(
                    f"Retriever sonucu {position} SearchHit değil: "
                    f"{type(hit).__name__}."
                )

        if raw_diagnostics is None:
            mode = str(getattr(self.retriever, "retrieval_mode", "bm25"))
            diagnostics = RetrievalDiagnostics(
                mode=mode,
                dense_status=(
                    "not_requested" if mode == "bm25" else "not_reported"
                ),
                lexical_candidate_count=len(hits),
                fused_candidate_count=len({hit.chunk.chunk_id for hit in hits}),
                channel_top_n=self.top_k,
            )
        elif isinstance(raw_diagnostics, RetrievalDiagnostics):
            diagnostics = raw_diagnostics
        else:
            model_dump = getattr(raw_diagnostics, "model_dump", None)
            if callable(model_dump):
                diagnostic_data = model_dump()
            elif isinstance(raw_diagnostics, dict):
                diagnostic_data = dict(raw_diagnostics)
            else:
                raise TypeError("Retriever diagnostics sözleşmesi geçersiz.")
            diagnostic_data.setdefault(
                "mode", str(getattr(self.retriever, "retrieval_mode", "hybrid"))
            )
            diagnostics = RetrievalDiagnostics.model_validate(diagnostic_data)
        return LegislationSearchResult(hits=hits, diagnostics=diagnostics)


class SourceVerificationAgent:
    name = "Kaynak Doğrulama Ajanı (Auditor)"

    def __init__(self, min_retrieval_score: float = 0.20) -> None:
        if (
            isinstance(min_retrieval_score, bool)
            or not math.isfinite(min_retrieval_score)
            or not 0 <= min_retrieval_score <= 1
        ):
            raise ValueError("Dense retrieval kabul eşiği 0 ile 1 arasında olmalıdır.")
        self.min_retrieval_score = float(min_retrieval_score)

    def run(
        self, hits: list[SearchHit], analysis: DocumentAnalysis
    ) -> list[VerifiedReference]:
        if not hits:
            return []
        top_score = max(hit.score for hit in hits)
        verified: list[VerifiedReference] = []
        for hit in hits:
            relative_score = hit.score / top_score if top_score else 0.0
            contributions = list(hit.channel_contributions)
            channels = list(
                dict.fromkeys(contribution.channel for contribution in contributions)
            )
            has_lexical_evidence = len(hit.matched_terms) >= 1
            if has_lexical_evidence and "lexical" not in channels:
                channels.insert(0, "lexical")
            dense_raw_scores = [
                contribution.raw_score
                for contribution in contributions
                if contribution.channel == "dense"
                and math.isfinite(contribution.raw_score)
            ]
            best_dense_score = max(dense_raw_scores, default=None)
            has_accepted_dense_evidence = (
                best_dense_score is not None
                and best_dense_score >= self.min_retrieval_score
            )
            has_concept_gate_evidence = hit.relevance_accepted is True
            if has_concept_gate_evidence and "concept_gate" not in channels:
                channels.append("concept_gate")
            has_ranked_evidence = (
                has_lexical_evidence
                or has_accepted_dense_evidence
                or has_concept_gate_evidence
            )
            source_decision = self._source_decision(hit.chunk)
            trusted_source = source_decision.trusted
            source_note = source_decision.note
            snapshot_requires_relevance = (
                source_decision.corpus_mode
                == CorpusMode.COMPETITION_SNAPSHOT.value
            )
            relevance_gate_passed = (
                hit.relevance_accepted is True
                if snapshot_requires_relevance
                else hit.relevance_accepted is not False
            )
            ranking_score_passed = (
                hit.relevance_accepted is True or relative_score >= 0.30
            )

            accepted = (
                ranking_score_passed
                and has_ranked_evidence
                and trusted_source
                and relevance_gate_passed
            )
            if snapshot_requires_relevance and hit.relevance_accepted is not True:
                note = "Snapshot kaynağı incelenmiş alaka kapısından geçmedi."
            elif hit.relevance_accepted is False:
                note = "Kaynak niyet ve metin alaka kapısını geçemedi."
            elif not ranking_score_passed:
                note = "Kaynak parçası göreli skor eşiğini geçemedi."
            elif not trusted_source:
                note = "Kaynak güven sınırını geçemedi: " + source_note
            elif not has_ranked_evidence and dense_raw_scores:
                note = (
                    "Dense ham benzerlik skoru mutlak kabul eşiğini geçemedi: "
                    f"en_yuksek={best_dense_score:.4f}, "
                    f"esik={self.min_retrieval_score:.4f}."
                )
            elif has_lexical_evidence:
                note = (
                    "Sorgu terimleri güvenilir kaynak parçasında bulundu ve göreli "
                    "skor eşiğini geçti."
                )
            elif has_accepted_dense_evidence:
                note = (
                    "Dense kanal katkısı ile kaynak türü, onay, yürürlük, metin ve "
                    "atıf doğrulamaları tekrar denetlendi."
                )
            elif has_concept_gate_evidence:
                note = (
                    "Girdi kavram grubu görünür hüküm kavram grubuyla "
                    "deterministik olarak eşlendi."
                )
            else:
                note = "Kaynak parçasında doğrulanabilir retrieval kanıtı bulunamadı."

            if accepted and hit.relevance_accepted is True:
                relevance_score = (
                    f"{hit.relevance_score:.2f}"
                    if hit.relevance_score is not None
                    else "belirtilmedi"
                )
                note = (
                    "Niyet ve görünür metin alaka kapısı geçti "
                    f"(profil={hit.relevance_profile}, "
                    f"skor={relevance_score}). {note}"
                )

            if (
                accepted
                and source_decision.corpus_mode
                == CorpusMode.COMPETITION_SNAPSHOT.value
            ):
                note = f"{note} {source_note} {COMPETITION_SNAPSHOT_NOTICE}"

            verified.append(
                VerifiedReference(
                    chunk_id=hit.chunk.chunk_id,
                    document_id=hit.chunk.document_id,
                    title=hit.chunk.title,
                    article=hit.chunk.article,
                    paragraph=hit.chunk.paragraph,
                    clause=hit.chunk.clause,
                    source=hit.chunk.source,
                    page=hit.chunk.page,
                    page_end=hit.chunk.page_end,
                    source_url=hit.chunk.source_url,
                    source_kind=hit.chunk.source_kind,
                    corpus_mode=source_decision.corpus_mode,
                    currentness_verified=source_decision.currentness_verified,
                    legal_reliance_allowed=(
                        accepted and source_decision.legal_reliance_allowed
                    ),
                    usage_notice=source_decision.usage_notice,
                    domain=hit.chunk.domain,
                    excerpt=truncate(hit.chunk.text, 360),
                    score=round(relative_score, 4),
                    verified=accepted,
                    verification_note=note,
                    evidence_channels=channels,
                    channel_contributions=contributions,
                    relevance_score=hit.relevance_score,
                    relevance_accepted=hit.relevance_accepted,
                    relevance_reasons=list(hit.relevance_reasons),
                    relevance_profile=hit.relevance_profile,
                    relevance_basis=hit.relevance_basis,
                )
            )
        return verified

    @staticmethod
    def _trusted_source(chunk: LegislationChunk) -> tuple[bool, str]:
        decision = SourceVerificationAgent._source_decision(chunk)
        return decision.trusted, decision.note

    @staticmethod
    def _source_decision(chunk: LegislationChunk) -> _SourceDecision:
        if chunk.source_kind == "public_legislation":
            blockers = LegislationRepository.public_chunk_blockers(chunk)
            trusted = not blockers
            return _SourceDecision(
                trusted=trusted,
                note=(
                    "kamu kaynağı doğrulama engelleri: " + ", ".join(blockers)
                    if blockers
                    else "doğrulanmış kamu mevzuatı"
                ),
                corpus_mode=CorpusMode.VERIFIED_PUBLIC.value,
                currentness_verified=trusted,
                legal_reliance_allowed=trusted,
            )
        if chunk.source_kind == CorpusMode.COMPETITION_SNAPSHOT.value:
            blockers = competition_snapshot_chunk_blockers(chunk)
            return _SourceDecision(
                trusted=not blockers,
                note=(
                    "yarışma snapshot doğrulama engelleri: "
                    + ", ".join(blockers)
                    if blockers
                    else (
                        "Yarışma snapshot sözleşmesi ve kaynak izi doğrulandı; "
                        "mevzuat güncelliği/yürürlüğü doğrulanmadı."
                    )
                ),
                corpus_mode=CorpusMode.COMPETITION_SNAPSHOT.value,
                currentness_verified=False,
                legal_reliance_allowed=False,
                usage_notice=COMPETITION_SNAPSHOT_NOTICE,
            )
        if (
            chunk.source_kind == "synthetic"
            and chunk.status == "sentetik_demo_kurali"
        ):
            return _SourceDecision(
                trusted=True,
                note="açıkça işaretlenmiş sentetik demo kuralı",
                corpus_mode=CorpusMode.TRUSTED_SYNTHETIC.value,
                currentness_verified=False,
                legal_reliance_allowed=False,
            )
        return _SourceDecision(
            trusted=False,
            note=(
                "kaynak ne tam doğrulanmış kamu mevzuatı, ne geçerli yarışma "
                "snapshot parçası ne de açıkça işaretlenmiş sentetik demo kuralı"
            ),
            corpus_mode="unknown",
            currentness_verified=False,
            legal_reliance_allowed=False,
        )


__all__ = [
    "LegislationResearchAgent",
    "LegislationSearchResult",
    "RankedRetriever",
    "SourceVerificationAgent",
]
