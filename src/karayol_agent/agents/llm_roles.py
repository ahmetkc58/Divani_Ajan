from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Protocol

from karayol_agent.llm import (
    DataClassification,
    LegalAgentRole,
    LLMCallResult,
    LLMTask,
    StructuredLLMRequest,
)
from karayol_agent.schemas import (
    DocumentAnalysis,
    GraphDecisionTrace,
    RoutingRecommendation,
    TemplateDecision,
    VerifiedReference,
)


DOCUMENT_TYPES = (
    "yol_bakim_talebi",
    "trafik_guvenligi_bildirimi",
    "hasar_bildirimi",
    "bilgi_talebi",
    "sikayet",
    "ust_yazi",
    "dilekce",
    "genel_basvuru",
)

EXTRACTION_FIELDS = (
    "gonderen",
    "konu",
    "konum",
    "tarih",
    "talep",
    "eposta",
    "telefon",
    "muhatap",
)


class StructuredGateway(Protocol):
    config: Any

    def invoke(self, request: StructuredLLMRequest) -> LLMCallResult: ...


@dataclass(frozen=True, slots=True)
class FieldCandidate:
    value: str | None
    evidence: str | None


@dataclass(frozen=True, slots=True)
class UnderstandingOutcome:
    call: LLMCallResult
    document_type: str | None = None
    confidence: float | None = None
    summary: str | None = None
    fields: Mapping[str, FieldCandidate] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class AdjudicationOutcome:
    call: LLMCallResult
    selected_template_id: str | None = None
    selected_unit_id: str | None = None
    accepted_reference_ids: tuple[str, ...] = ()
    confidence: float | None = None
    rationale: str | None = None
    requires_human_review: bool = False
    unsupported_claims: tuple[str, ...] = ()


def _nullable_field_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "value": {"type": ["string", "null"], "maxLength": 500},
            "evidence": {"type": ["string", "null"], "maxLength": 700},
        },
        "required": ["value", "evidence"],
        "additionalProperties": False,
    }


def _head_and_tail(text: str, *, limit: int = 12_000) -> str:
    if len(text) <= limit:
        return text
    head = int(limit * 0.58)
    tail = limit - head
    return text[:head] + "\n[ORTA_BOLUM_YEREL_OLARAK_KISALTILDI]\n" + text[-tail:]


class LLMDocumentUnderstandingAgent:
    """Optional structured understanding; deterministic analysis remains the base."""

    name = "LLM Yapılandırılmış Anlama Ajanı"

    def __init__(self, gateway: StructuredGateway) -> None:
        self.gateway = gateway

    def run(
        self,
        *,
        text: str,
        deterministic_analysis: DocumentAnalysis,
        data_classification: DataClassification,
    ) -> UnderstandingOutcome:
        field_properties = {
            name: _nullable_field_schema() for name in EXTRACTION_FIELDS
        }
        schema = {
            "type": "object",
            "properties": {
                "document_type": {
                    "type": "string",
                    "enum": list(DOCUMENT_TYPES),
                },
                "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                "summary": {"type": "string", "maxLength": 500},
                "fields": {
                    "type": "object",
                    "properties": field_properties,
                    "required": list(EXTRACTION_FIELDS),
                    "additionalProperties": False,
                },
            },
            "required": ["document_type", "confidence", "summary", "fields"],
            "additionalProperties": False,
        }
        result = self.gateway.invoke(
            StructuredLLMRequest(
                task=LLMTask.EXTRACTION,
                role=LegalAgentRole.RESEARCHER,
                input_data={
                    "document_text": _head_and_tail(text),
                    "deterministic_document_type": deterministic_analysis.document_type,
                    "deterministic_summary": deterministic_analysis.summary,
                    "deterministic_missing_fields": deterministic_analysis.missing_fields,
                },
                output_schema=schema,
                data_classification=data_classification,
                allow_automatic_redaction=False,
                trusted_instructions=(
                    "Kapalı evrak türü listesinden seçim yap. Her alan için değer ile "
                    "birlikte belgeden birebir kısa kanıt parçası ver; açık kanıt yoksa "
                    "hem value hem evidence null olsun. Göndereni üstbilgi, hitap ve "
                    "imza bloğunu birlikte değerlendirerek seç. Özette yeni olgu ekleme."
                ),
            )
        )
        if not result.succeeded or result.output is None:
            return UnderstandingOutcome(call=result)
        payload = result.output
        candidates = {
            name: FieldCandidate(
                value=payload["fields"][name]["value"],
                evidence=payload["fields"][name]["evidence"],
            )
            for name in EXTRACTION_FIELDS
        }
        return UnderstandingOutcome(
            call=result,
            document_type=str(payload["document_type"]),
            confidence=float(payload["confidence"]),
            summary=str(payload["summary"]),
            fields=candidates,
        )


class LLMAdjudicatorAgent:
    """LegalGraph-style Adjudicator over locally researched/audited evidence."""

    name = "LLM Karar Ajanı (Adjudicator)"

    def __init__(self, gateway: StructuredGateway) -> None:
        self.gateway = gateway

    def run(
        self,
        *,
        analysis: DocumentAnalysis,
        references: list[VerifiedReference],
        template_decision: TemplateDecision,
        routing: RoutingRecommendation,
        graph_trace: GraphDecisionTrace | None,
        allowed_template_ids: list[str],
        allowed_unit_ids: list[str],
        data_classification: DataClassification,
    ) -> AdjudicationOutcome:
        if not allowed_template_ids or not allowed_unit_ids:
            raise ValueError("Adjudicator kapalı şablon ve birim adayları gerektirir.")
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
                "selected_template_id": {
                    "type": "string",
                    "enum": sorted(set(allowed_template_ids)),
                },
                "selected_unit_id": {
                    "type": "string",
                    "enum": sorted(set(allowed_unit_ids)),
                },
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
                "selected_template_id",
                "selected_unit_id",
                "accepted_reference_ids",
                "confidence",
                "rationale",
                "requires_human_review",
                "unsupported_claims",
            ],
            "additionalProperties": False,
        }
        graph_payload = (
            graph_trace.model_dump(mode="json")
            if graph_trace is not None
            else {"strategy": "not_available", "applied": False}
        )
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
                    "deterministic_template_id": template_decision.template_id,
                    "deterministic_unit_id": routing.unit_id,
                    "allowed_template_ids": sorted(set(allowed_template_ids)),
                    "allowed_unit_ids": sorted(set(allowed_unit_ids)),
                    "graph_advice": graph_payload,
                },
                output_schema=schema,
                data_classification=data_classification,
                allow_automatic_redaction=False,
                trusted_instructions=(
                    "Researcher kapalı aday listesini ve Auditor tarafından doğrulanmış "
                    "kimlikleri "
                    "kullan. Yalnız allowlist içindeki şablon/birimi seç. Kabul edilen "
                    "referanslar Auditor listesinin alt kümesi olmalı. currentness_verified "
                    "ve legal_reliance_allowed false ise bunu kesin hukuk hükmü sayma. "
                    "Sentetik graf yalnız karar desteğidir. Çelişki veya yetersiz kanıtta "
                    "requires_human_review=true döndür."
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
            selected_template_id=str(payload["selected_template_id"]),
            selected_unit_id=str(payload["selected_unit_id"]),
            accepted_reference_ids=accepted_ids,
            confidence=float(payload["confidence"]),
            rationale=str(payload["rationale"]),
            requires_human_review=(
                bool(payload["requires_human_review"])
                or bool(unknown_reference_ids)
            ),
            unsupported_claims=unsupported_claims,
        )
