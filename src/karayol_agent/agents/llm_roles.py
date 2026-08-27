from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from karayol_agent.llm import (
    DataClassification,
    LegalAgentRole,
    LLMCallResult,
    LLMTask,
    StructuredLLMRequest,
)
from karayol_agent.schemas import DocumentAnalysis, VerifiedReference


class StructuredGateway(Protocol):
    config: Any

    def invoke(self, request: StructuredLLMRequest) -> LLMCallResult: ...


@dataclass(frozen=True, slots=True)
class AdjudicationOutcome:
    """Pure evidence-synthesis outcome (KATMAN 2 Adjudicator).

    Template/unit selection is no longer decided here — it moved to the
    dedicated KATMAN 3 agents (``LLMTemplateSelectionAgent``,
    ``LLMRoutingAgent`` in ``agents.llm_layer3``), which consume
    ``accepted_reference_ids``/``rationale`` as their evidence input.
    """

    call: LLMCallResult
    accepted_reference_ids: tuple[str, ...] = ()
    confidence: float | None = None
    rationale: str | None = None
    requires_human_review: bool = False
    unsupported_claims: tuple[str, ...] = ()


def _head_and_tail(text: str, *, limit: int = 12_000) -> str:
    if len(text) <= limit:
        return text
    head = int(limit * 0.58)
    tail = limit - head
    return text[:head] + "\n[ORTA_BOLUM_YEREL_OLARAK_KISALTILDI]\n" + text[-tail:]


class LLMAdjudicatorAgent:
    """LegalGraph-style Adjudicator over locally researched/audited evidence.

    Scoped to pure evidence synthesis: it decides which verified references
    are admissible and whether the overall evidence picture warrants human
    review. It never picks a template or a routing unit — those are
    downstream KATMAN 3 decisions made by dedicated agents that consume this
    outcome.
    """

    name = "LLM Karar Ajanı (Adjudicator)"

    def __init__(self, gateway: StructuredGateway) -> None:
        self.gateway = gateway

    def run(
        self,
        *,
        analysis: DocumentAnalysis,
        references: list[VerifiedReference],
        data_classification: DataClassification,
    ) -> AdjudicationOutcome:
        verified_references = [reference for reference in references if reference.verified]
        verified_ids = {reference.chunk_id for reference in verified_references}
        reference_item_schema: dict[str, Any] = {
            "type": "string",
            "maxLength": 120,
        }
        if verified_ids:
            reference_item_schema["enum"] = sorted(verified_ids)
        schema = {
            "type": "object",
            "properties": {
                "accepted_reference_ids": {
                    "type": "array",
                    "items": reference_item_schema,
                    "maxItems": min(10, len(verified_ids)),
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
        include_reference_excerpts = (
            data_classification is DataClassification.SYNTHETIC
        )
        researcher_candidates = []
        for reference in verified_references:
            candidate = {
                "chunk_id": reference.chunk_id,
                "title": reference.title,
                "article": reference.article,
                "page": reference.page,
                "verified": reference.verified,
                "currentness_verified": reference.currentness_verified,
                "legal_reliance_allowed": reference.legal_reliance_allowed,
            }
            if include_reference_excerpts:
                candidate["excerpt"] = reference.excerpt
            researcher_candidates.append(candidate)
        result = self.gateway.invoke(
            StructuredLLMRequest(
                task=LLMTask.ADJUDICATION,
                role=LegalAgentRole.ADJUDICATOR,
                input_data={
                    "researcher_candidates": researcher_candidates,
                    "auditor_verified_reference_ids": sorted(verified_ids),
                    "analysis": {
                        "document_type": analysis.document_type,
                        "summary": analysis.summary,
                        "missing_fields": analysis.missing_fields,
                    },
                },
                output_schema=schema,
                data_classification=data_classification,
                allow_automatic_redaction=False,
                trusted_instructions=(
                    "Researcher kapalı aday listesini ve Auditor tarafından "
                    "doğrulanmış kimlikleri kullan. Kabul edilen referanslar "
                    "Auditor listesinin alt kümesi olmalı. "
                    "currentness_verified ve legal_reliance_allowed false ise "
                    "bunu kesin hukuk hükmü sayma. Çelişki veya yetersiz "
                    "kanıtta requires_human_review=true döndür."
                ),
            )
        )
        if not result.succeeded or result.output is None:
            return AdjudicationOutcome(call=result, requires_human_review=True)
        payload = result.output
        raw_accepted_ids = tuple(
            str(item) for item in payload["accepted_reference_ids"]
        )
        unknown_reference_ids = sorted(set(raw_accepted_ids) - verified_ids)
        accepted_ids = tuple(
            item
            for item in raw_accepted_ids
            if item in verified_ids
        )
        unsupported_claims = tuple(
            str(item) for item in payload["unsupported_claims"]
        )
        if unknown_reference_ids:
            unsupported_claims = (
                *unsupported_claims,
                "Auditor kümesi dışında referans kimliği döndürüldü: "
                + ", ".join(unknown_reference_ids),
            )
        return AdjudicationOutcome(
            call=result,
            accepted_reference_ids=accepted_ids,
            confidence=float(payload["confidence"]),
            rationale=str(payload["rationale"]),
            requires_human_review=(
                bool(payload["requires_human_review"])
                or bool(unknown_reference_ids)
            ),
            unsupported_claims=unsupported_claims,
        )
