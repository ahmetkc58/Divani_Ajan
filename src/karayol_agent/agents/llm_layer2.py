"""KATMAN 2 — Search-o1: Researcher/Auditor/Adjudicator gain autonomous,
tool-calling-driven search via ``AgenticToolLLMGateway`` + ``llm-large``.

Each wrapper keeps the existing deterministic agent (``LegislationResearchAgent``,
``SourceVerificationAgent``) as the mandatory floor/fallback and only *adds*
LLM-driven behaviour on top — consistent with every other LLM role in this
codebase. The Adjudicator wrapper reuses the existing, unmodified
``AdjudicationOutcome`` contract from ``agents.llm_roles`` so the
orchestrator's safety gate (``_apply_llm_evidence_synthesis``) needs no
changes at all.
"""

from __future__ import annotations

from dataclasses import dataclass

from karayol_agent.agents.legislation import LegislationResearchAgent, SourceVerificationAgent
from karayol_agent.agents.llm_roles import AdjudicationOutcome
from karayol_agent.agents.search_tool import LegislationSearchTool
from karayol_agent.llm.agentic_gateway import AgenticCallResult, AgenticToolLLMGateway
from karayol_agent.llm.contracts import (
    DataClassification,
    LegalAgentRole,
    LLMCallResult,
    LLMFailure,
    LLMStatus,
    LLMTask,
)
from karayol_agent.schemas import DocumentAnalysis, RetrievalDiagnostics, SearchHit, VerifiedReference


def _to_llm_call_result(
    agentic_result: AgenticCallResult, gateway: AgenticToolLLMGateway
) -> LLMCallResult:
    """Adapt an agentic multi-turn result into the single-shot trace currency.

    Lets every KATMAN 2 Search-o1 outcome flow through the existing
    ``EvrakOrchestrator._record_llm_step``/``state.llm_trace`` machinery
    unchanged.
    """

    if agentic_result.succeeded:
        return LLMCallResult(
            status=LLMStatus.SUCCESS,
            provider=gateway.config.provider,
            model=gateway.config.model,
            output=agentic_result.output,
            network_attempted=agentic_result.network_attempted,
            redacted=agentic_result.redacted,
            redaction_count=agentic_result.redaction_count,
        )
    return LLMCallResult(
        status=LLMStatus.PROVIDER_ERROR,
        provider=gateway.config.provider,
        model=gateway.config.model,
        failure=LLMFailure(
            code=agentic_result.failure_code or "agentic_failure",
            message=agentic_result.failure_message or "Search-o1 döngüsü başarısız oldu.",
        ),
        network_attempted=agentic_result.network_attempted,
        redacted=agentic_result.redacted,
        redaction_count=agentic_result.redaction_count,
    )


# ---------------------------------------------------------------------------
# Researcher
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SearchO1ResearchOutcome:
    hits: list[SearchHit]
    diagnostics: RetrievalDiagnostics
    call: LLMCallResult
    turns_used: int


class SearchO1ResearchAgent:
    """Researcher: deterministic seed query + up to N autonomous follow-up searches."""

    name = "Mevzuat Araştırma Ajanı — Search-o1 (KATMAN 2)"

    def __init__(
        self,
        gateway: AgenticToolLLMGateway,
        researcher: LegislationResearchAgent,
        verifier: SourceVerificationAgent,
        *,
        max_turns: int = 3,
    ) -> None:
        self._gateway = gateway
        self._researcher = researcher
        self._verifier = verifier
        self._max_turns = max_turns

    def run(
        self, analysis: DocumentAnalysis, *, data_classification: DataClassification
    ) -> SearchO1ResearchOutcome:
        seed = self._researcher.run_with_diagnostics(analysis)
        tool = LegislationSearchTool(self._researcher, self._verifier, analysis)
        schema = {
            "type": "object",
            "properties": {
                "reasoning": {"type": "string", "maxLength": 600},
                "search_complete": {"type": "boolean"},
            },
            "required": ["reasoning", "search_complete"],
            "additionalProperties": False,
        }
        agentic_result = self._gateway.run(
            role=LegalAgentRole.RESEARCHER.value,
            task=LLMTask.EXTRACTION.value,
            input_data={
                "document_type": analysis.document_type,
                "summary": analysis.summary,
                "keywords": analysis.keywords,
                "seed_result_titles": [hit.chunk.title for hit in seed.hits[:5]],
            },
            final_answer_schema=schema,
            tool=tool.as_tool_definition(),
            trusted_instructions=(
                "İlk arama sonuçları (seed_result_titles) yetersizse "
                "search_legislation aracıyla farklı/daha dar bir sorgu dene; "
                "yeterli görüyorsan search_complete=true ile bitir."
            ),
            data_classification=data_classification,
            max_turns=self._max_turns,
        )
        merged_hits = list(seed.hits)
        seen_ids = {hit.chunk.chunk_id for hit in merged_hits}
        for hit in tool.verified_hits:
            if hit.chunk.chunk_id in seen_ids:
                continue
            merged_hits.append(hit)
            seen_ids.add(hit.chunk.chunk_id)
        return SearchO1ResearchOutcome(
            hits=merged_hits,
            diagnostics=seed.diagnostics,
            call=_to_llm_call_result(agentic_result, self._gateway),
            turns_used=agentic_result.turns_used,
        )


# ---------------------------------------------------------------------------
# Auditor
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SearchO1AuditOutcome:
    references: list[VerifiedReference]
    call: LLMCallResult
    requires_human_review: bool
    concern_notes: str | None


class SearchO1AuditorAgent:
    """Auditor: the deterministic trust-contract floor is unconditional and
    unchanged (``SourceVerificationAgent.run``). An LLM scrutiny pass runs
    ONLY over already-verified-but-low-score candidates, may search for
    corroborating/contradicting evidence, and can only add a
    ``requires_human_review`` flag — it can never upgrade a source the
    deterministic floor rejected.
    """

    name = "Kaynak Doğrulama Ajanı — Search-o1 (KATMAN 2)"

    def __init__(
        self,
        gateway: AgenticToolLLMGateway,
        researcher: LegislationResearchAgent,
        verifier: SourceVerificationAgent,
        *,
        max_turns: int = 2,
        low_confidence_threshold: float = 0.5,
    ) -> None:
        self._gateway = gateway
        self._researcher = researcher
        self._verifier = verifier
        self._max_turns = max_turns
        self._low_confidence_threshold = low_confidence_threshold

    def run(
        self,
        hits: list[SearchHit],
        analysis: DocumentAnalysis,
        *,
        data_classification: DataClassification,
    ) -> SearchO1AuditOutcome:
        references = self._verifier.run(hits, analysis)
        borderline = [
            reference
            for reference in references
            if reference.verified and reference.score < self._low_confidence_threshold
        ]
        if not borderline:
            return SearchO1AuditOutcome(
                references=references,
                call=LLMCallResult(
                    status=LLMStatus.SUCCESS,
                    provider=self._gateway.config.provider,
                    model=self._gateway.config.model,
                    output={"skipped": True},
                ),
                requires_human_review=False,
                concern_notes=None,
            )
        tool = LegislationSearchTool(self._researcher, self._verifier, analysis)
        schema = {
            "type": "object",
            "properties": {
                "requires_human_review": {"type": "boolean"},
                "concern_notes": {"type": ["string", "null"], "maxLength": 600},
            },
            "required": ["requires_human_review", "concern_notes"],
            "additionalProperties": False,
        }
        agentic_result = self._gateway.run(
            role=LegalAgentRole.AUDITOR.value,
            task=LLMTask.EVIDENCE_AUDIT.value,
            input_data={
                "candidate_references": [
                    {
                        "chunk_id": reference.chunk_id,
                        "title": reference.title,
                        "article": reference.article,
                        "excerpt": reference.excerpt,
                    }
                    for reference in borderline
                ]
            },
            final_answer_schema=schema,
            tool=tool.as_tool_definition(),
            trusted_instructions=(
                "Bu düşük güvenli kanıt adaylarını incele; birbirleriyle "
                "veya bilinen mevzuat yapısıyla çelişen bir şey görürsen "
                "search_legislation ile çapraz kontrol yap. Şüphe varsa "
                "requires_human_review=true döndür. Bu değerlendirme mevcut "
                "güven kararını YÜKSELTEMEZ, yalnız ek inceleme "
                "işaretleyebilir."
            ),
            data_classification=data_classification,
            max_turns=self._max_turns,
        )
        call_result = _to_llm_call_result(agentic_result, self._gateway)
        if not agentic_result.succeeded or agentic_result.output is None:
            # EVIDENCE_AUDIT's established fallback is ABSTAIN: a failed
            # scrutiny pass never blocks the deterministic floor's own
            # verified/unverified decision, it just means no second opinion.
            return SearchO1AuditOutcome(
                references=references,
                call=call_result,
                requires_human_review=False,
                concern_notes=None,
            )
        payload = agentic_result.output
        return SearchO1AuditOutcome(
            references=references,
            call=call_result,
            requires_human_review=bool(payload["requires_human_review"]),
            concern_notes=payload.get("concern_notes"),
        )


# ---------------------------------------------------------------------------
# Adjudicator
# ---------------------------------------------------------------------------


class SearchO1AdjudicatorAgent:
    """Adjudicator: same final contract as the narrowed ``LLMAdjudicatorAgent``
    (``AdjudicationOutcome``), now reachable via 0-N autonomous searches
    before answering. The orchestrator's existing confidence/evidence gate
    (``_apply_llm_evidence_synthesis``) applies unchanged.
    """

    name = "LLM Karar Ajanı — Search-o1 (KATMAN 2 Adjudicator)"

    def __init__(
        self,
        gateway: AgenticToolLLMGateway,
        researcher: LegislationResearchAgent,
        verifier: SourceVerificationAgent,
        *,
        max_turns: int = 1,
    ) -> None:
        self._gateway = gateway
        self._researcher = researcher
        self._verifier = verifier
        self._max_turns = max_turns

    def run(
        self,
        *,
        analysis: DocumentAnalysis,
        references: list[VerifiedReference],
        data_classification: DataClassification,
    ) -> AdjudicationOutcome:
        verified_references = [reference for reference in references if reference.verified]
        verified_ids = {reference.chunk_id for reference in verified_references}
        tool = LegislationSearchTool(self._researcher, self._verifier, analysis)
        schema = {
            "type": "object",
            "properties": {
                "accepted_reference_ids": {
                    "type": "array",
                    "items": {"type": "string", "maxLength": 120},
                    "maxItems": 10,
                },
                "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                "rationale": {"type": "string", "maxLength": 600},
                "requires_human_review": {"type": "boolean"},
                "unsupported_claims": {
                    "type": "array",
                    "items": {"type": "string", "maxLength": 300},
                    "maxItems": 10,
                },
            },
            "required": [
                "accepted_reference_ids",
                "confidence",
                "rationale",
                "requires_human_review",
                "unsupported_claims",
            ],
            "additionalProperties": False,
        }
        agentic_result = self._gateway.run(
            role=LegalAgentRole.ADJUDICATOR.value,
            task=LLMTask.ADJUDICATION.value,
            input_data={
                "researcher_candidates": [
                    {
                        "chunk_id": reference.chunk_id,
                        "title": reference.title,
                        "article": reference.article,
                        "page": reference.page,
                        "verified": reference.verified,
                        "currentness_verified": reference.currentness_verified,
                        "legal_reliance_allowed": reference.legal_reliance_allowed,
                    }
                    for reference in verified_references
                ],
                "auditor_verified_reference_ids": sorted(verified_ids),
                "analysis": {
                    "document_type": analysis.document_type,
                    "summary": analysis.summary,
                    "missing_fields": analysis.missing_fields,
                },
            },
            final_answer_schema=schema,
            tool=tool.as_tool_definition(),
            trusted_instructions=(
                "Yalnız Auditor tarafından doğrulanmış kimlikleri veya "
                "search_legislation ile bu oturumda yeni doğrulanmış "
                "kimlikleri kabul et. currentness_verified ve "
                "legal_reliance_allowed false ise bunu kesin hukuk hükmü "
                "sayma. Mevcut kanıtlar yetersizse en fazla "
                f"{self._max_turns} kez search_legislation çağırabilirsin. "
                "Çelişki veya yetersiz kanıtta requires_human_review=true "
                "döndür."
            ),
            data_classification=data_classification,
            max_turns=self._max_turns,
        )
        call_result = _to_llm_call_result(agentic_result, self._gateway)
        if not agentic_result.succeeded or agentic_result.output is None:
            return AdjudicationOutcome(call=call_result, requires_human_review=True)
        payload = agentic_result.output
        all_known_ids = verified_ids | tool.seen_chunk_ids
        raw_accepted_ids = tuple(str(item) for item in payload["accepted_reference_ids"])
        unknown_reference_ids = sorted(set(raw_accepted_ids) - all_known_ids)
        accepted_ids = tuple(item for item in raw_accepted_ids if item in all_known_ids)
        unsupported_claims = tuple(str(item) for item in payload["unsupported_claims"])
        if unknown_reference_ids:
            unsupported_claims = (
                *unsupported_claims,
                "Doğrulanmış küme dışında referans kimliği döndürüldü: "
                + ", ".join(unknown_reference_ids),
            )
        return AdjudicationOutcome(
            call=call_result,
            accepted_reference_ids=accepted_ids,
            confidence=float(payload["confidence"]),
            rationale=str(payload["rationale"]),
            requires_human_review=(
                bool(payload["requires_human_review"]) or bool(unknown_reference_ids)
            ),
            unsupported_claims=unsupported_claims,
        )


__all__ = [
    "SearchO1AdjudicatorAgent",
    "SearchO1AuditOutcome",
    "SearchO1AuditorAgent",
    "SearchO1ResearchAgent",
    "SearchO1ResearchOutcome",
]
