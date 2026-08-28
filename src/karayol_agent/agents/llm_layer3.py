"""Katman 3: kaynak-bağlı kararın güvenli bir resmî yazı taslağına dönüşümü.

LLM3 şablon seçer, LLM5 kapalı organizasyon kataloğundan birim önerir,
LLM6 kullanıcıya kaynak-bağlı yanıt stratejileri sunar ve LLM4 yalnız seçilen
şablonun metin alanlarını doldurur. Hiçbir ajan ham LaTeX, serbest birim kimliği
veya katalog dışı şablon üretemez.
"""

from __future__ import annotations

import json
import time
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from karayol_agent.llm import (
    DataClassification,
    LegalAgentRole,
    LLMCallResult,
    LLMTask,
    StructuredLLMRequest,
)
from karayol_agent.official_writing_rules import ALLOWED_CLOSINGS_BY_RELATION
from karayol_agent.schemas import (
    DocumentAnalysis,
    ResponseStrategyOption,
    RoutingRecommendation,
    TemplateDecision,
    UnitRecord,
    VerifiedReference,
)
from karayol_agent.text_utils import truncate

from .llm_roles import StructuredGateway


def _invoke_with_retry(
    gateway: StructuredGateway,
    request: StructuredLLMRequest,
) -> LLMCallResult:
    """Geçici ağ hatasında yalnız bir kez, kısa gecikmeyle yeniden dene."""

    result = gateway.invoke(request)
    if result.failure is not None and result.failure.retryable:
        time.sleep(3.0)
        return gateway.invoke(request)
    return result


@dataclass(frozen=True, slots=True)
class TemplateCatalogEntry:
    template_id: str
    display_name: str
    when_to_use: str
    required_fields_summary: tuple[str, ...] = ()


class TemplateCatalog:
    def __init__(self, entries: Sequence[TemplateCatalogEntry]) -> None:
        if not entries:
            raise ValueError("Şablon kataloğu boş olamaz.")
        self.entries = tuple(entries)
        self._by_id = {entry.template_id: entry for entry in self.entries}

    @classmethod
    def load(cls, path: Path) -> "TemplateCatalog":
        payload = json.loads(path.read_text(encoding="utf-8"))
        raw_entries = payload.get("entries", []) if isinstance(payload, dict) else payload
        return cls(
            [
                TemplateCatalogEntry(
                    template_id=str(item["template_id"]),
                    display_name=str(item["display_name"]),
                    when_to_use=str(item["when_to_use"]),
                    required_fields_summary=tuple(
                        str(field_name)
                        for field_name in item.get("required_fields_summary", [])
                    ),
                )
                for item in raw_entries
            ]
        )


@dataclass(frozen=True, slots=True)
class TemplateSelectionOutcome:
    call: LLMCallResult
    selected_template_id: str | None = None
    confidence: float | None = None
    rationale: str | None = None
    requires_human_review: bool = False


class LLMTemplateSelectionAgent:
    name = "LLM3 — Şablon Seçim Ajanı"

    def __init__(self, gateway: StructuredGateway, catalog: TemplateCatalog) -> None:
        self.gateway = gateway
        self.catalog = catalog

    def run(
        self,
        *,
        analysis: DocumentAnalysis,
        deterministic_decision: TemplateDecision,
        verified_references: Sequence[VerifiedReference],
        allowed_template_ids: Sequence[str],
        data_classification: DataClassification,
    ) -> TemplateSelectionOutcome:
        allowed = sorted(set(allowed_template_ids))
        if not allowed:
            raise ValueError("LLM3 kapalı şablon adayları gerektirir.")
        candidates = [
            entry for entry in self.catalog.entries if entry.template_id in allowed
        ]
        schema = {
            "type": "object",
            "properties": {
                "selected_template_id": {"type": "string", "enum": allowed},
                "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                "rationale": {"type": "string", "maxLength": 600},
                "requires_human_review": {"type": "boolean"},
            },
            "required": [
                "selected_template_id",
                "confidence",
                "rationale",
                "requires_human_review",
            ],
            "additionalProperties": False,
        }
        result = _invoke_with_retry(
            self.gateway,
            StructuredLLMRequest(
                task=LLMTask.TEMPLATE_SELECTION,
                role=LegalAgentRole.TEMPLATE_SELECTOR,
                input_data={
                    "analysis": {
                        "document_type": analysis.document_type,
                        "summary": analysis.summary,
                        "missing_fields": analysis.missing_fields,
                    },
                    "deterministic_template_id": deterministic_decision.template_id,
                    "verified_source_titles": [
                        reference.title
                        for reference in verified_references
                        if reference.verified
                    ][:10],
                    "candidate_templates": [
                        {
                            "template_id": entry.template_id,
                            "display_name": entry.display_name,
                            "when_to_use": entry.when_to_use,
                            "required_fields": entry.required_fields_summary,
                        }
                        for entry in candidates
                    ],
                },
                output_schema=schema,
                data_classification=data_classification,
                allow_automatic_redaction=False,
                trusted_instructions=(
                    "Yalnız candidate_templates içindeki bir template_id seç. "
                    "Kararı yalnız analysis, doğrulanmış kaynak başlıkları ve katalog "
                    "açıklamalarına dayandır; model önbilgisi kullanma. Eksik zorunlu "
                    "alan varsa eksik_bilgi_talebi_v1 dışında şablon seçme. "
                    "Belirsizlikte requires_human_review=true döndür."
                ),
            )
        )
        if not result.succeeded or result.output is None:
            return TemplateSelectionOutcome(call=result, requires_human_review=True)
        payload = result.output
        return TemplateSelectionOutcome(
            call=result,
            selected_template_id=str(payload["selected_template_id"]),
            confidence=float(payload["confidence"]),
            rationale=str(payload["rationale"]),
            requires_human_review=bool(payload["requires_human_review"]),
        )


@dataclass(frozen=True, slots=True)
class RoutingOutcome:
    call: LLMCallResult
    selected_unit_id: str | None = None
    traversal_path: tuple[str, ...] = ()
    confidence: float | None = None
    rationale: str | None = None
    requires_human_review: bool = False


class LLMRoutingAgent:
    name = "LLM5 — Birim Yönlendirme Ajanı"

    def __init__(self, gateway: StructuredGateway) -> None:
        self.gateway = gateway

    def run(
        self,
        *,
        analysis: DocumentAnalysis,
        units: Sequence[UnitRecord],
        deterministic_routing: RoutingRecommendation,
        allowed_unit_ids: Sequence[str],
        data_classification: DataClassification,
    ) -> RoutingOutcome:
        allowed = sorted(set(allowed_unit_ids))
        if not allowed:
            raise ValueError("LLM5 kapalı birim adayları gerektirir.")
        candidates = [unit for unit in units if unit.unit_id in allowed]
        schema = {
            "type": "object",
            "properties": {
                "selected_unit_id": {"type": "string", "enum": allowed},
                "traversal_path": {
                    "type": "array",
                    "items": {"type": "string", "maxLength": 120},
                    "maxItems": 8,
                },
                "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                "rationale": {"type": "string", "maxLength": 600},
                "requires_human_review": {"type": "boolean"},
            },
            "required": [
                "selected_unit_id",
                "traversal_path",
                "confidence",
                "rationale",
                "requires_human_review",
            ],
            "additionalProperties": False,
        }
        result = _invoke_with_retry(
            self.gateway,
            StructuredLLMRequest(
                task=LLMTask.ROUTING,
                role=LegalAgentRole.ROUTER,
                input_data={
                    "analysis": {
                        "document_type": analysis.document_type,
                        "operational_category": analysis.operational_category,
                        "summary": analysis.summary,
                        "keywords": analysis.keywords,
                    },
                    "deterministic_unit_id": deterministic_routing.unit_id,
                    "candidate_units": [
                        {
                            "unit_id": unit.unit_id,
                            "unit_name": unit.unit_name,
                            "hierarchy": unit.hierarchy,
                            "parent_id": unit.parent_id,
                            "unit_type": unit.unit_type,
                            "keywords": unit.keywords,
                            "responsibilities": unit.responsibilities,
                        }
                        for unit in candidates
                    ],
                },
                output_schema=schema,
                data_classification=data_classification,
                allow_automatic_redaction=False,
                trusted_instructions=(
                    "Yalnız candidate_units kataloğunu ve analysis içindeki belge "
                    "olgularını kullan. parent_id alanlarıyla üstten alta gezin; "
                    "katalog dışı kurum/birim uydurma. Belirsizlikte insan incelemesi iste."
                ),
            )
        )
        if not result.succeeded or result.output is None:
            return RoutingOutcome(call=result, requires_human_review=True)
        payload = result.output
        return RoutingOutcome(
            call=result,
            selected_unit_id=str(payload["selected_unit_id"]),
            traversal_path=tuple(str(item) for item in payload["traversal_path"]),
            confidence=float(payload["confidence"]),
            rationale=str(payload["rationale"]),
            requires_human_review=bool(payload["requires_human_review"]),
        )


@dataclass(frozen=True, slots=True)
class ResponseStrategyProposalOutcome:
    call: LLMCallResult
    options: tuple[ResponseStrategyOption, ...] = ()


class LLMResponseStrategyAgent:
    name = "LLM6 — Yanıt Stratejisi Ajanı"

    def __init__(self, gateway: StructuredGateway) -> None:
        self.gateway = gateway

    def run(
        self,
        *,
        analysis: DocumentAnalysis,
        verified_references: Sequence[VerifiedReference],
        data_classification: DataClassification,
    ) -> ResponseStrategyProposalOutcome:
        references = [reference for reference in verified_references if reference.verified]
        reference_ids = sorted({reference.chunk_id for reference in references})
        if not reference_ids:
            return ResponseStrategyProposalOutcome(
                call=self._abstain_call(),
                options=(),
            )
        schema = {
            "type": "object",
            "properties": {
                "options": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "option_id": {"type": "string", "maxLength": 40},
                            "label": {"type": "string", "maxLength": 160},
                            "description": {"type": "string", "maxLength": 400},
                            "reference_ids": {
                                "type": "array",
                                "items": {"type": "string", "enum": reference_ids},
                                "minItems": 1,
                                "maxItems": 6,
                            },
                        },
                        "required": [
                            "option_id",
                            "label",
                            "description",
                            "reference_ids",
                        ],
                        "additionalProperties": False,
                    },
                    "minItems": 2,
                    "maxItems": 4,
                }
            },
            "required": ["options"],
            "additionalProperties": False,
        }
        result = _invoke_with_retry(
            self.gateway,
            StructuredLLMRequest(
                task=LLMTask.SUMMARY,
                role=LegalAgentRole.RESPONSE_ADVISOR,
                input_data={
                    "analysis": {
                        "document_type": analysis.document_type,
                        "summary": analysis.summary,
                        "missing_fields": analysis.missing_fields,
                    },
                    "verified_sources": [
                        {
                            "chunk_id": reference.chunk_id,
                            "title": reference.title,
                            "article": reference.article,
                            "excerpt": truncate(reference.excerpt, 600),
                        }
                        for reference in references[:10]
                    ],
                },
                output_schema=schema,
                data_classification=data_classification,
                allow_automatic_redaction=False,
                trusted_instructions=(
                    "Birbirinden farklı 2-4 yanıt stratejisi öner. Her stratejiyi "
                    "yalnız verified_sources içindeki açık hükümlere dayandır ve "
                    "dayandığı kimlikleri reference_ids alanında ver. Model önbilgisi, "
                    "kaynakta bulunmayan hak, süre, yükümlülük veya sonuç ekleme."
                ),
            )
        )
        if not result.succeeded or result.output is None:
            return ResponseStrategyProposalOutcome(call=result, options=())
        options = tuple(
            ResponseStrategyOption(
                option_id=str(item["option_id"]),
                label=str(item["label"]),
                description=str(item["description"]),
                reference_ids=[str(value) for value in item["reference_ids"]],
            )
            for item in result.output["options"]
            if str(item["option_id"]) != "custom"
        )
        return ResponseStrategyProposalOutcome(call=result, options=options)

    def _abstain_call(self) -> LLMCallResult:
        from karayol_agent.llm import LLMStatus

        return LLMCallResult(
            status=LLMStatus.SUCCESS,
            provider=self.gateway.config.provider,
            model=self.gateway.config.model,
            output={"abstained": True, "reason": "verified_source_missing"},
        )


@dataclass(frozen=True, slots=True)
class TemplateFillOutcome:
    call: LLMCallResult
    subject: str | None = None
    paragraphs: tuple[str, ...] = ()
    closing: str | None = None


class LLMTemplateFillAgent:
    name = "LLM4 — Şablon Doldurma Ajanı"

    def __init__(self, gateway: StructuredGateway) -> None:
        self.gateway = gateway

    def run(
        self,
        *,
        analysis: DocumentAnalysis,
        template_id: str,
        template_structure: dict[str, Any],
        authority_relation: str,
        verified_references: Sequence[VerifiedReference],
        response_strategy: ResponseStrategyOption | None,
        response_custom_text: str | None,
        data_classification: DataClassification,
    ) -> TemplateFillOutcome:
        references = [reference for reference in verified_references if reference.verified]
        allowed_closings = list(
            ALLOWED_CLOSINGS_BY_RELATION.get(authority_relation, ())
        )
        properties: dict[str, Any] = {
            "subject": {"type": "string", "maxLength": 200},
            "paragraphs": {
                "type": "array",
                "items": {"type": "string", "maxLength": 700},
                "minItems": 1,
                "maxItems": 8,
            },
        }
        required = ["subject", "paragraphs"]
        if allowed_closings:
            properties["closing"] = {"type": "string", "enum": allowed_closings}
            required.append("closing")
        schema = {
            "type": "object",
            "properties": properties,
            "required": required,
            "additionalProperties": False,
        }
        result = _invoke_with_retry(
            self.gateway,
            StructuredLLMRequest(
                task=LLMTask.DRAFT_FIELDS,
                role=LegalAgentRole.DRAFTER,
                input_data={
                    "template_id": template_id,
                    "template_structure": template_structure,
                    "analysis": {
                        "document_type": analysis.document_type,
                        "summary": analysis.summary,
                        "fields": {
                            name: field.value
                            for name, field in analysis.fields.items()
                            if field.value
                        },
                    },
                    "verified_sources": [
                        {
                            "chunk_id": reference.chunk_id,
                            "title": reference.title,
                            "article": reference.article,
                            "excerpt": truncate(reference.excerpt, 600),
                        }
                        for reference in references[:8]
                    ],
                    "response_strategy": (
                        response_strategy.model_dump(mode="json")
                        if response_strategy is not None
                        else None
                    ),
                    "response_custom_text": response_custom_text,
                },
                output_schema=schema,
                data_classification=data_classification,
                allow_automatic_redaction=False,
                trusted_instructions=(
                    "Yalnız analysis, template_structure, seçilmiş strateji ve "
                    "verified_sources içeriğini kullan. Kaynakta veya belgede olmayan "
                    "olgu/hüküm uydurma. LaTeX, Markdown veya biçimlendirme kodu "
                    "üretme; yalnız düz metin alanlarını doldur. Bu metin doğrudan "
                    "muhataba gönderilecektir: şablon/taslak adı, model veya ajan adı, "
                    "retrieval skoru, snapshot, kaynak güncelliği ya da iç doğrulama "
                    "uyarısı yazma. Yalnız kurumun muhataba ileteceği nihai yazı "
                    "cümlelerini üret."
                ),
            )
        )
        if not result.succeeded or result.output is None:
            return TemplateFillOutcome(call=result)
        return TemplateFillOutcome(
            call=result,
            subject=str(result.output["subject"]),
            paragraphs=tuple(str(item) for item in result.output["paragraphs"]),
            closing=result.output.get("closing"),
        )


__all__ = [
    "LLMRoutingAgent",
    "LLMResponseStrategyAgent",
    "LLMTemplateFillAgent",
    "LLMTemplateSelectionAgent",
    "ResponseStrategyProposalOutcome",
    "RoutingOutcome",
    "TemplateCatalog",
    "TemplateFillOutcome",
    "TemplateSelectionOutcome",
]
