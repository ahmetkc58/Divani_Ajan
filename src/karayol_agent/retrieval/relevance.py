"""Transparent intent-and-text relevance control for the fixed legal snapshot.

Hybrid retrieval is deliberately broad: it is good at producing candidates but
RRF does not know whether a provision actually governs the incident in the
incoming document.  This module adds a small, deterministic post-retrieval
layer for the two competition-demo intents that have engineering labels.

The rules never name a law, article or chunk ID.  They require observable
concept groups both in the submitted text and in the text shown to the user. A
classifier label or a query-expansion phrase can therefore never create a
citation on its own. A context-only match is not promoted into a citation whose
displayed child text is unhelpful. Unknown intents fail closed until they
receive their own reviewed profile.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from karayol_agent.schemas import (
    DocumentAnalysis,
    LegislationChunk,
    RetrievalDiagnostics,
    SearchHit,
)
from karayol_agent.text_utils import (
    normalize_for_search,
    normalize_whitespace,
    tokenize,
)


ROAD_SURFACE_PROFILE = "road_surface_maintenance_v1"
TRAFFIC_SIGN_PROFILE = "traffic_sign_damage_v1"
GENERIC_ARCHIVE_PROFILE = "generic_archive_lexical_overlap_v1"
RELEVANCE_STRATEGY = "intent_profile_concept_gate_v2"


GENERIC_QUERY_STOPWORDS = frozenset(
    {
        "acaba",
        "ait",
        "başvuru",
        "belge",
        "bilgi",
        "bildiriyorum",
        "edilmesi",
        "ederek",
        "etmek",
        "gereğinin",
        "hakkında",
        "istiyorum",
        "konu",
        "lütfen",
        "müdürlüğü",
        "nedir",
        "talep",
        "talebim",
        "tarafından",
        "üzere",
        "yapılması",
    }
)


PROFILE_EXPANSIONS: dict[str, tuple[str, ...]] = {
    ROAD_SURFACE_PROFILE: (
        "karayolu yapısı",
        "yol yüzeyi",
        "bozukluk ve eksiklik",
        "bakım ve onarım",
        "derhal giderilir",
        "trafik güvenliğini sağlayacak durumda bulundurmak",
        "yapım ve bakımından sorumlu kuruluş",
    ),
    TRAFFIC_SIGN_PROFILE: (
        "trafik işaretleri",
        "trafik işaret levhaları",
        "kırmak sökmek bozmak",
        "bozukluk ve eksiklik",
        "derhal giderilir",
        "sürekliliği ve işlerliği",
        "bakım onarım",
        "sorumlu kuruluş",
    ),
}


class AnalysisAwareRetriever(Protocol):
    retrieval_mode: str

    def search_for_analysis(
        self,
        query: str,
        analysis: DocumentAnalysis | Mapping[str, Any],
        top_k: int = 5,
    ) -> Any: ...


@dataclass(frozen=True, slots=True)
class RelevanceDecision:
    profile: str
    score: float
    accepted: bool
    reasons: tuple[str, ...]
    basis: str


@dataclass(frozen=True, slots=True)
class QueryIntentDecision:
    profile: str
    supported: bool
    score: float
    concepts: tuple[str, ...]
    reasons: tuple[str, ...]
    evidence_basis: str


@dataclass(frozen=True, slots=True)
class QueryFocusedSearchResponse:
    hits: list[SearchHit]
    diagnostics: RetrievalDiagnostics


class AnalysisAwareTextRetrieverAdapter:
    """Adapt a text-query retriever to the analysis-aware candidate contract."""

    analysis_aware = True

    def __init__(self, base_retriever: Any, *, mode: str) -> None:
        if mode not in {"bm25", "hybrid"}:
            raise ValueError("Text retriever adapter mode bm25 veya hybrid olmalıdır.")
        self.base_retriever = base_retriever
        self.retrieval_mode = mode
        for name in (
            "vector_store",
            "embedding_provider",
            "lexical_retriever",
            "domain_resolver",
            "channel_top_n",
            "rrf_k",
            "federated_readiness",
        ):
            if hasattr(base_retriever, name):
                setattr(self, name, getattr(base_retriever, name))

    def search_for_analysis(
        self,
        query: str,
        analysis: DocumentAnalysis | Mapping[str, Any],
        top_k: int = 5,
    ) -> QueryFocusedSearchResponse | Any:
        del analysis
        search_with_diagnostics = getattr(
            self.base_retriever, "search_with_diagnostics", None
        )
        if callable(search_with_diagnostics):
            return search_with_diagnostics(query, top_k=top_k)
        hits = list(self.base_retriever.search(query, top_k=top_k))
        return QueryFocusedSearchResponse(
            hits=hits,
            diagnostics=RetrievalDiagnostics(
                mode=self.retrieval_mode,
                dense_status=(
                    "not_requested"
                    if self.retrieval_mode == "bm25"
                    else "not_reported"
                ),
                lexical_candidate_count=len(hits),
                fused_candidate_count=len({hit.chunk.chunk_id for hit in hits}),
            ),
        )


def resolve_relevance_profile(
    analysis: DocumentAnalysis | Mapping[str, Any],
) -> str | None:
    """Resolve only intents backed by the reviewed snapshot relevance set."""

    document_type = _string_value(_read_value(analysis, "document_type"))
    analysis_text = _analysis_text(analysis)
    if document_type == "yol_bakim_talebi":
        return ROAD_SURFACE_PROFILE
    if document_type == "hasar_bildirimi" and _contains_any(
        analysis_text,
        ("yol yüz", "asfalt", "çukur", "kaplama", "bozuk yol"),
    ):
        return ROAD_SURFACE_PROFILE
    if document_type == "trafik_guvenligi_bildirimi" and _contains_any(
        analysis_text,
        ("trafik işaret", "işaret levha", "levha"),
    ):
        return TRAFFIC_SIGN_PROFILE
    return None


def build_relevance_query(query: str, profile: str) -> str:
    """Append reviewed, article-agnostic concept phrases to the base query."""

    expansions = PROFILE_EXPANSIONS.get(profile)
    if expansions is None:
        return normalize_whitespace(query)
    values = [query, *expansions]
    unique: list[str] = []
    seen: set[str] = set()
    for value in values:
        clean = normalize_whitespace(value)
        key = normalize_for_search(clean)
        if clean and key not in seen:
            seen.add(key)
            unique.append(clean)
    return " ".join(unique)


def build_query_evidence_text(
    analysis: DocumentAnalysis | Mapping[str, Any],
    *,
    fallback_query: str = "",
) -> tuple[str, str]:
    """Return user-derived evidence without classifier labels or expansions."""

    raw_evidence = _string_value(
        _read_value(analysis, "retrieval_evidence_text")
    )
    if raw_evidence:
        return normalize_whitespace(raw_evidence), "submitted_text"

    values = [_string_value(_read_value(analysis, "summary"))]
    fields = _read_value(analysis, "fields")
    if isinstance(fields, Mapping):
        for field_name in ("konu", "talep"):
            field = fields.get(field_name)
            source = _string_value(_read_value(field, "source"))
            value = _string_value(_read_value(field, "value"))
            if source and value:
                values.append(value)
    keywords = _read_value(analysis, "keywords")
    if isinstance(keywords, Sequence) and not isinstance(keywords, (str, bytes)):
        values.extend(_string_value(item) for item in keywords)
    evidence = normalize_whitespace(" ".join(value for value in values if value))
    if evidence:
        return evidence, "analysis_source_fields"
    return normalize_whitespace(fallback_query), "fallback_query"


def assess_query_intent(
    *,
    profile: str,
    evidence_text: str,
    evidence_basis: str = "submitted_text",
) -> QueryIntentDecision:
    """Require incident concepts in the submitted text before retrieval."""

    text = normalize_for_search(evidence_text)
    if profile == ROAD_SURFACE_PROFILE:
        groups = (
            (
                "road_surface_asset",
                (
                    "asfalt",
                    "kaplama",
                    "yol yüz",
                    "karayolu yüz",
                    "sürüş yüz",
                    "yol gövde",
                    "çukur",
                    "oyuk",
                ),
            ),
            (
                "physical_surface_defect",
                (
                    "çukur",
                    "oyuk",
                    "çatlak",
                    "çökünt",
                    "çökmüş",
                    "bozul",
                    "deform",
                    "bozuk kaplama",
                    "hasarlı asfalt",
                ),
            ),
            (
                "repair_or_safety_request",
                (
                    "bakım",
                    "onar",
                    "tamir",
                    "gider",
                    "düzelt",
                    "yenile",
                    "yama",
                    "kapatıl",
                    "trafik güven",
                    "gereğinin yapıl",
                ),
            ),
        )
        vetoes = (
            "tazminat",
            "değer kayb",
            "sigorta",
            "ihale",
            "satın alma",
            "teknik şartname",
            "bitüm oran",
            "tabaka kalın",
            "iş başvuru",
            "personel alım",
        )
        required_count = 3
    elif profile == TRAFFIC_SIGN_PROFILE:
        groups = (
            (
                "official_traffic_sign",
                (
                    "trafik işaret",
                    "işaret levha",
                    "trafik levha",
                    "yön levha",
                ),
            ),
            (
                "sign_damage_or_loss",
                (
                    "devril",
                    "kırıl",
                    "kırık",
                    "sökül",
                    "hasar",
                    "bozul",
                    "eksik",
                    "kaybol",
                    "yerinden çık",
                    "görünm",
                    "arız",
                    "yamul",
                ),
            ),
            (
                "restore_or_report_request",
                (
                    "onar",
                    "tamir",
                    "gider",
                    "düzelt",
                    "yenile",
                    "yerine kon",
                    "gereğinin yapıl",
                    "talep",
                    "bildir",
                    "trafik güven",
                ),
            ),
        )
        vetoes = (
            "cezaya itiraz",
            "ceza itiraz",
            "sigorta",
            "tazminat",
            "levhanın bedeli",
            "araç plaka",
            "ayırım işaret",
            "okul geçidi görevli",
            "reklam tabela",
            "teknik ölçü",
            "levha görsel",
        )
        # A damaged official sign is already a reportable safety incident;
        # explicit remedy/report language improves the score but is optional.
        required_count = 2
    elif profile == GENERIC_ARCHIVE_PROFILE:
        content_terms = _generic_content_terms(evidence_text)
        supported = len(content_terms) >= 2
        reasons = (
            (
                "Geniş arşiv sorgusu için anlamlı terimler bulundu: "
                + ", ".join(content_terms[:12])
                + "."
            )
            if supported
            else "Geniş arşiv sorgusu için en az iki anlamlı terim gerekli."
        )
        return QueryIntentDecision(
            profile=profile,
            supported=supported,
            score=1.0 if supported else len(content_terms) / 2,
            concepts=tuple(content_terms[:12]),
            reasons=(reasons,),
            evidence_basis=evidence_basis,
        )
    else:
        return QueryIntentDecision(
            profile=profile,
            supported=False,
            score=0.0,
            concepts=(),
            reasons=("İncelenmiş bir sorgu niyeti profili bulunmuyor.",),
            evidence_basis=evidence_basis,
        )

    matched = tuple(name for name, patterns in groups if _contains_any(text, patterns))
    veto_matches = tuple(
        pattern for pattern in vetoes if normalize_for_search(pattern) in text
    )
    score = round(len(matched) / len(groups), 4)
    required = all(name in matched for name, _ in groups[:required_count])
    supported = required and not veto_matches
    reasons = [f"Girdi kavramı bulundu: {name}." for name in matched]
    missing = [name for name, _ in groups[:required_count] if name not in matched]
    if missing:
        reasons.append("Zorunlu girdi kavramları eksik: " + ", ".join(missing) + ".")
    if veto_matches:
        reasons.append(
            "İncelenmiş profil dışı amaç saptandı: " + ", ".join(veto_matches) + "."
        )
    if supported:
        reasons.append("Kullanıcı metni incelenmiş olay profiliyle uyumlu.")
    return QueryIntentDecision(
        profile=profile,
        supported=supported,
        score=score,
        concepts=matched,
        reasons=tuple(reasons),
        evidence_basis=evidence_basis,
    )


def assess_query_relevance(
    chunk: LegislationChunk,
    *,
    profile: str,
    query: str,
    threshold: float = 0.75,
    query_intent: QueryIntentDecision | None = None,
) -> RelevanceDecision:
    """Score a candidate using its user-visible text, not hidden context alone."""

    if isinstance(threshold, bool) or not 0 <= threshold <= 1:
        raise ValueError("Relevance eşiği 0 ile 1 arasında olmalıdır.")
    intent = query_intent or assess_query_intent(
        profile=profile,
        evidence_text=query,
        evidence_basis="direct_query",
    )
    display_text = normalize_for_search(chunk.text)
    context_text = normalize_for_search(chunk.context_text or "")
    normalized_query = normalize_for_search(query)
    if profile == ROAD_SURFACE_PROFILE:
        score, required, reasons = _road_surface_score(
            display_text, normalized_query
        )
        context_required = _road_surface_score(context_text, normalized_query)[1]
    elif profile == TRAFFIC_SIGN_PROFILE:
        score, required, reasons = _traffic_sign_score(
            display_text, normalized_query
        )
        context_required = _traffic_sign_score(context_text, normalized_query)[1]
    elif profile == GENERIC_ARCHIVE_PROFILE:
        score, required, reasons = _generic_archive_score(
            display_text,
            normalized_query,
        )
        context_required = _generic_archive_score(
            context_text,
            normalized_query,
        )[1]
    else:
        return RelevanceDecision(
            profile=profile,
            score=0.0,
            accepted=False,
            reasons=("İncelenmiş bir alaka profili bulunmuyor.",),
            basis="unsupported_profile",
        )

    score *= 0.85 + 0.15 * intent.score
    score = round(max(0.0, min(score, 1.0)), 4)
    accepted = intent.supported and required and score >= threshold
    basis = (
        "query_and_text"
        if intent.supported and required
        else "context_only"
        if intent.supported and context_required
        else "query_not_supported"
        if not intent.supported
        else "none"
    )
    if not intent.supported:
        reasons.append("Kullanıcı metni incelenmiş olay profiliyle uyuşmadı.")
    if not required and context_required:
        reasons.append(
            "İlişki yalnız üst bağlamda; gösterilecek chunk metni tek başına yeterli değil."
        )
    if score < threshold:
        reasons.append(f"Alaka skoru eşik altında: {score:.2f} < {threshold:.2f}.")
    if accepted:
        reasons.append("Nesne ve görev/giderme kavram grupları birlikte doğrulandı.")
    return RelevanceDecision(
        profile=profile,
        score=score,
        accepted=accepted,
        reasons=tuple(reasons),
        basis=basis,
    )


class AnalysisAwareDeterministicReranker:
    """Expand, broadly retrieve, then rerank/gate reviewed snapshot intents."""

    analysis_aware = True
    expects_analysis = True
    retrieval_mode = "hybrid"

    def __init__(
        self,
        base_retriever: AnalysisAwareRetriever,
        *,
        candidate_top_k: int = 40,
        threshold: float = 0.75,
        fallback_policy: str = "reviewed_only",
    ) -> None:
        if (
            isinstance(candidate_top_k, bool)
            or not isinstance(candidate_top_k, int)
            or candidate_top_k < 1
        ):
            raise ValueError("Relevance aday sayısı en az 1 olmalıdır.")
        if isinstance(threshold, bool) or not 0 <= threshold <= 1:
            raise ValueError("Relevance eşiği 0 ile 1 arasında olmalıdır.")
        if fallback_policy not in {"reviewed_only", "lexical_overlap"}:
            raise ValueError("Bilinmeyen snapshot relevance fallback politikası.")
        self.base_retriever = base_retriever
        self.candidate_top_k = candidate_top_k
        self.threshold = float(threshold)
        self.fallback_policy = fallback_policy
        self.retrieval_mode = str(
            getattr(base_retriever, "retrieval_mode", "hybrid")
        )
        # Readiness and operational probes use these public runtime attributes.
        for name in (
            "vector_store",
            "embedding_provider",
            "lexical_retriever",
            "domain_resolver",
            "channel_top_n",
            "rrf_k",
            "federated_readiness",
        ):
            if hasattr(base_retriever, name):
                setattr(self, name, getattr(base_retriever, name))

    def search_for_analysis(
        self,
        query: str,
        analysis: DocumentAnalysis | Mapping[str, Any],
        top_k: int = 5,
    ) -> QueryFocusedSearchResponse | Any:
        if isinstance(top_k, bool) or not isinstance(top_k, int) or top_k < 1:
            raise ValueError("Relevance sonuç sayısı pozitif bir tam sayı olmalıdır.")
        profile = resolve_relevance_profile(analysis)
        if profile is None and self.fallback_policy == "lexical_overlap":
            profile = GENERIC_ARCHIVE_PROFILE
        if profile is None:
            return self._abstention_response(
                profile=None,
                query_decision=None,
                warning=(
                    "Bu evrak türü için incelenmiş bir snapshot alaka profili "
                    "yok; yanlış atıf üretmemek için sonuçlardan kaçınıldı."
                ),
            )

        evidence_text, evidence_basis = build_query_evidence_text(
            analysis,
            fallback_query=query,
        )
        query_decision = assess_query_intent(
            profile=profile,
            evidence_text=evidence_text,
            evidence_basis=evidence_basis,
        )
        if not query_decision.supported:
            return self._abstention_response(
                profile=profile,
                query_decision=query_decision,
                warning=(
                    "Evrak sınıfı eşleşti; ancak kullanıcı metninde "
                    "incelenmiş olay kavramları birlikte bulunamadı. Yanlış "
                    "atıf üretmemek için sonuçlardan kaçınıldı."
                ),
            )

        expanded_query = build_relevance_query(query, profile)
        response = self.base_retriever.search_for_analysis(
            expanded_query,
            analysis,
            top_k=max(top_k, self.candidate_top_k),
        )
        candidates = list(getattr(response, "hits", response))
        accepted: list[SearchHit] = []
        for hit in candidates:
            if not isinstance(hit, SearchHit):
                raise TypeError("Relevance adayı SearchHit olmalıdır.")
            decision = assess_query_relevance(
                hit.chunk,
                profile=profile,
                query=evidence_text,
                threshold=self.threshold,
                query_intent=query_decision,
            )
            if not decision.accepted:
                continue
            accepted.append(
                SearchHit(
                    chunk=hit.chunk,
                    score=hit.score,
                    matched_terms=_visible_original_matched_terms(
                        hit,
                        evidence_text,
                    ),
                    expansion_matched_terms=_expansion_matched_terms(
                        hit,
                        evidence_text,
                    ),
                    fusion_method=(
                        f"{hit.fusion_method}+{RELEVANCE_STRATEGY}"
                        if hit.fusion_method
                        else RELEVANCE_STRATEGY
                    ),
                    channel_contributions=list(hit.channel_contributions),
                    relevance_score=decision.score,
                    relevance_accepted=True,
                    relevance_reasons=list(decision.reasons),
                    relevance_profile=profile,
                    relevance_basis=decision.basis,
                )
            )

        accepted.sort(
            key=lambda hit: (
                -(hit.relevance_score or 0.0),
                -hit.score,
                hit.chunk.chunk_id,
            )
        )
        final_hits = accepted[:top_k]
        raw_diagnostics = getattr(response, "diagnostics", None)
        diagnostics = _coerce_diagnostics(raw_diagnostics, self.retrieval_mode)
        abstention_warning = (
            "Sorgu-odaklı alaka eşiğini geçen kaynak bulunamadı; yanlış atıf "
            "üretmemek için sonuçlardan kaçınıldı."
            if not final_hits
            else None
        )
        warning = diagnostics.warning
        if abstention_warning:
            warning = (
                f"{warning} {abstention_warning}"
                if warning
                else abstention_warning
            )
        diagnostics = diagnostics.model_copy(
            update={
                "warning": warning,
                "relevance_strategy": RELEVANCE_STRATEGY,
                "relevance_profile": profile,
                "relevance_candidate_top_k": self.candidate_top_k,
                "relevance_candidate_count": len(candidates),
                "relevance_accepted_count": len(accepted),
                "relevance_rejected_count": len(candidates) - len(accepted),
                "relevance_threshold": self.threshold,
                "relevance_abstained": not final_hits,
                "relevance_query_expansion": list(PROFILE_EXPANSIONS.get(profile, ())),
                "relevance_query_supported": query_decision.supported,
                "relevance_query_score": query_decision.score,
                "relevance_query_concepts": list(query_decision.concepts),
                "relevance_query_reasons": list(query_decision.reasons),
                "relevance_query_evidence_basis": query_decision.evidence_basis,
            }
        )
        return QueryFocusedSearchResponse(hits=final_hits, diagnostics=diagnostics)

    def _abstention_response(
        self,
        *,
        profile: str | None,
        query_decision: QueryIntentDecision | None,
        warning: str,
    ) -> QueryFocusedSearchResponse:
        return QueryFocusedSearchResponse(
            hits=[],
            diagnostics=RetrievalDiagnostics(
                mode=self.retrieval_mode,
                dense_status=(
                    "not_requested"
                    if self.retrieval_mode == "bm25"
                    else "not_used_query_gate"
                ),
                warning=warning,
                relevance_strategy=RELEVANCE_STRATEGY,
                relevance_profile=profile,
                relevance_candidate_top_k=self.candidate_top_k,
                relevance_threshold=self.threshold,
                relevance_abstained=True,
                relevance_query_expansion=(
                    list(PROFILE_EXPANSIONS.get(profile, ())) if profile else []
                ),
                relevance_query_supported=(
                    query_decision.supported if query_decision else False
                ),
                relevance_query_score=(
                    query_decision.score if query_decision else 0.0
                ),
                relevance_query_concepts=(
                    list(query_decision.concepts) if query_decision else []
                ),
                relevance_query_reasons=(
                    list(query_decision.reasons)
                    if query_decision
                    else ["İncelenmiş profil bulunmuyor."]
                ),
                relevance_query_evidence_basis=(
                    query_decision.evidence_basis if query_decision else None
                ),
            ),
        )

    def search_with_diagnostics(
        self,
        analysis: DocumentAnalysis | Mapping[str, Any],
        top_k: int = 5,
    ) -> QueryFocusedSearchResponse | Any:
        # Local import avoids a runtime/relevance import cycle.
        from karayol_agent.retrieval.runtime import build_analysis_query

        query = build_analysis_query(analysis)
        return self.search_for_analysis(query, analysis, top_k=top_k)

    def search(
        self,
        analysis: DocumentAnalysis | Mapping[str, Any],
        top_k: int = 5,
    ) -> Sequence[SearchHit]:
        return self.search_with_diagnostics(analysis, top_k=top_k).hits


def _road_surface_score(text: str, query: str) -> tuple[float, bool, list[str]]:
    object_match = _contains_any(
        text,
        (
            "karayolu yapı",
            "karayolunu kullananlara",
            "yolun yapı",
            "sorumlu olduğu yollar",
            "yolları trafik düzeni",
        ),
    )
    duty_match = _contains_any(
        text,
        (
            "bozukluk",
            "eksiklik",
            "derhal gider",
            "en kısa zamanda ortadan kaldırarak karayolunu",
            "zarar vermeyecek duruma getir",
            "trafik düzeni ve güvenliğini sağlayacak durumda bulundur",
        ),
    )
    responsibility_match = _contains_any(
        text,
        (
            "yapım ve bakımından sorumlu",
            "yapımı, bakımı, işletilmesinden sorumlu",
            "görevli ve sorumlu",
            "ilgili kuruluş",
        ),
    )
    score = 0.35 * object_match + 0.50 * duty_match + 0.15 * responsibility_match
    reasons = _positive_reasons(
        object_match,
        duty_match,
        responsibility_match,
        object_label="Karayolu/yol yapısı nesnesi bulundu.",
        duty_label="Bozukluğu giderme veya yolu güvenli tutma görevi bulundu.",
    )
    conflicts = (
        "akaryakıt",
        "servis istasyonu",
        "işletme izni",
        "araç bakım",
        "trafik kazası tespit tutanağı",
        "okul geçidi",
    )
    if _contains_any(text, conflicts) and not _contains_any(query, conflicts):
        score -= 0.40
        reasons.append("Sorguda olmayan tesis/araç/kaza bağlamı alaka skorunu düşürdü.")
    return score, object_match and duty_match, reasons


def _traffic_sign_score(text: str, query: str) -> tuple[float, bool, list[str]]:
    object_match = _contains_any(
        text,
        ("trafik işaret", "işaret levha"),
    )
    duty_match = _contains_any(
        text,
        (
            "kırarak",
            "kırmak",
            "sökerek",
            "sökmek",
            "şekillerde boz",
            "bozukluk",
            "eksiklik",
            "derhal gider",
            "sürekliliği ve işlerliği",
            "devamlılığını ve işlerliğini",
            "güvenliğini sağlayacak şekilde yapmak ve bulundur",
            "işaretlerinin bakım, onarım ve işletil",
        ),
    )
    responsibility_match = _contains_any(
        text,
        (
            "sorumlu kuruluş",
            "görevli kuruluş",
            "ilgili kuruluş",
            "temin ve tesis",
            "yükümlüdür",
        ),
    )
    score = 0.45 * object_match + 0.40 * duty_match + 0.15 * responsibility_match
    reasons = _positive_reasons(
        object_match,
        duty_match,
        responsibility_match,
        object_label="Trafik işareti/işaret levhası nesnesi bulundu.",
        duty_label="Hasar, giderme, bakım veya işlerlik görevi bulundu.",
    )
    conflicts = (
        "okul geçidi",
        "trafik kazası",
        "sigorta",
        "sürücüler",
        "kavşaklarda",
        "park yerlerinde",
    )
    if _contains_any(text, conflicts) and not _contains_any(query, conflicts):
        score -= 0.40
        reasons.append("Sorguda olmayan sürücü/kaza/geçit bağlamı alaka skorunu düşürdü.")
    return score, object_match and duty_match, reasons


def _generic_archive_score(
    text: str,
    query: str,
) -> tuple[float, bool, list[str]]:
    """Gate broad archive hits using only visible, user-derived term overlap."""

    query_terms = _generic_content_terms(query)
    text_terms = _generic_content_terms(text)
    matched = [
        query_term
        for query_term in query_terms
        if any(_generic_terms_match(query_term, text_term) for text_term in text_terms)
    ]
    required_count = min(3, len(query_terms))
    required = required_count >= 2 and len(matched) >= required_count
    denominator = min(4, len(query_terms)) or 1
    coverage = min(1.0, len(matched) / denominator)
    score = round(0.5 + 0.5 * coverage, 4) if matched else 0.0
    reasons = []
    if matched:
        reasons.append(
            "Kullanıcı metni ile görünür kaynak metninde anlamlı terim örtüşmesi: "
            + ", ".join(matched[:12])
            + "."
        )
    if not required:
        reasons.append(
            f"Görünür kaynak metninde gerekli {required_count} anlamlı sorgu "
            "terimi doğrulanamadı."
        )
    if required:
        reasons.append(
            "Sonuç geniş arşiv keşif profiliyle metinsel olarak doğrulandı; "
            "hukuki uygulanabilirlik doğrulanmadı."
        )
    return score, required, reasons


def _generic_content_terms(value: str) -> list[str]:
    unique: list[str] = []
    seen: set[str] = set()
    for token in tokenize(value):
        if (
            len(token) < 4
            or token.isdigit()
            or token in GENERIC_QUERY_STOPWORDS
            or token in seen
        ):
            continue
        seen.add(token)
        unique.append(token)
    return unique


def _generic_terms_match(left: str, right: str) -> bool:
    if left == right:
        return True
    prefix_length = min(5, len(left), len(right))
    return prefix_length >= 4 and left[:prefix_length] == right[:prefix_length]


def _positive_reasons(
    object_match: bool,
    duty_match: bool,
    responsibility_match: bool,
    *,
    object_label: str,
    duty_label: str,
) -> list[str]:
    reasons: list[str] = []
    if object_match:
        reasons.append(object_label)
    if duty_match:
        reasons.append(duty_label)
    if responsibility_match:
        reasons.append("Sorumlu/görevli kuruluş bağı bulundu.")
    if not object_match:
        reasons.append("Olayın nesne kavramı gösterilen metinde bulunamadı.")
    if not duty_match:
        reasons.append("Giderme/bakım/güvenli tutma yükümlülüğü bulunamadı.")
    return reasons


def _visible_original_matched_terms(
    hit: SearchHit,
    evidence_text: str,
) -> list[str]:
    """Keep only submitted-query tokens also present in visible chunk text."""

    evidence_tokens = set(tokenize(evidence_text))
    visible_tokens = set(tokenize(hit.chunk.text))
    return list(
        dict.fromkeys(
            term
            for term in hit.matched_terms
            if normalize_for_search(term) in evidence_tokens
            and normalize_for_search(term) in visible_tokens
        )
    )


def _expansion_matched_terms(
    hit: SearchHit,
    evidence_text: str,
) -> list[str]:
    """Expose system-injected candidate terms without treating them as evidence."""

    evidence_tokens = set(tokenize(evidence_text))
    inherited = list(hit.expansion_matched_terms)
    injected = [
        term
        for term in hit.matched_terms
        if normalize_for_search(term) not in evidence_tokens
    ]
    return list(dict.fromkeys([*inherited, *injected]))


def _coerce_diagnostics(value: Any, mode: str) -> RetrievalDiagnostics:
    if isinstance(value, RetrievalDiagnostics):
        return value
    if value is None:
        return RetrievalDiagnostics(mode=mode)
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        data = model_dump()
    elif isinstance(value, Mapping):
        data = dict(value)
    else:
        raise TypeError("Retriever diagnostics sözleşmesi geçersiz.")
    data.setdefault("mode", mode)
    return RetrievalDiagnostics.model_validate(data)


def _analysis_text(analysis: DocumentAnalysis | Mapping[str, Any]) -> str:
    values = [
        _string_value(_read_value(analysis, "document_type")),
        _string_value(_read_value(analysis, "summary")),
    ]
    keywords = _read_value(analysis, "keywords")
    if isinstance(keywords, Sequence) and not isinstance(keywords, (str, bytes)):
        values.extend(_string_value(item) for item in keywords)
    fields = _read_value(analysis, "fields")
    if isinstance(fields, Mapping):
        for field in fields.values():
            values.append(_string_value(_read_value(field, "value")))
    return normalize_for_search(" ".join(value for value in values if value))


def _contains_any(value: str, patterns: Sequence[str]) -> bool:
    return any(normalize_for_search(pattern) in value for pattern in patterns)


def _read_value(value: Any, name: str) -> Any:
    if isinstance(value, Mapping):
        return value.get(name)
    return getattr(value, name, None)


def _string_value(value: Any) -> str:
    if value is None:
        return ""
    enum_value = getattr(value, "value", value)
    return str(enum_value).strip()


__all__ = [
    "AnalysisAwareTextRetrieverAdapter",
    "AnalysisAwareDeterministicReranker",
    "PROFILE_EXPANSIONS",
    "QueryFocusedSearchResponse",
    "QueryIntentDecision",
    "RELEVANCE_STRATEGY",
    "ROAD_SURFACE_PROFILE",
    "RelevanceDecision",
    "TRAFFIC_SIGN_PROFILE",
    "assess_query_relevance",
    "assess_query_intent",
    "build_relevance_query",
    "build_query_evidence_text",
    "resolve_relevance_profile",
]
