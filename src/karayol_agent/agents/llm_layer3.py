"""KATMAN 3 — LLM3 (şablon seçimi), LLM4 (şablon doldurma), LLM5 (birim
yönlendirme, org grafiği) ve LLM6 (yanıt stratejisi elde etme).

Her ajan, karşılık gelen deterministik ajanı (``TemplateSelectionAgent``,
``DraftingAgent``, ``RoutingAgent``) taban olarak korur; LLM yalnız kapalı bir
izin listesi/şema üzerinden, güven eşiği geçtiğinde geçersiz kılabilen bir
öneri sağlar. LLM4 hiçbir zaman ham LaTeX üretmez veya döndürmez — yalnız
``DraftPayload``'ın içerik alanlarına karşılık gelen yapılandırılmış metin
üretir; asıl LaTeX render'ı her zaman deterministik Jinja2 şablonlarıyla
yapılır (bkz. ``karayol_agent.latex.renderer``).
"""

from __future__ import annotations

import json
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

from .llm_roles import StructuredGateway, _head_and_tail


# ---------------------------------------------------------------------------
# LLM3 — şablon seçimi
# ---------------------------------------------------------------------------


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
        entries = [
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
        return cls(entries)

    def get(self, template_id: str) -> TemplateCatalogEntry | None:
        return self._by_id.get(template_id)


@dataclass(frozen=True, slots=True)
class TemplateSelectionOutcome:
    call: LLMCallResult
    selected_template_id: str | None = None
    confidence: float | None = None
    rationale: str | None = None
    requires_human_review: bool = False


class LLMTemplateSelectionAgent:
    """LLM3: şablon kataloğunun kısa metadata'sından (ham LaTeX değil) seçim yapar."""

    name = "LLM Şablon Seçim Ajanı (LLM3)"

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
            entry
            for entry in self.catalog.entries
            if entry.template_id in allowed
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
        result = self.gateway.invoke(
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
                    "verified_reference_titles": [
                        reference.title
                        for reference in verified_references
                        if reference.verified
                    ][:10],
                    "candidate_templates": [
                        {
                            "template_id": entry.template_id,
                            "display_name": entry.display_name,
                            "when_to_use": entry.when_to_use,
                        }
                        for entry in candidates
                    ],
                },
                output_schema=schema,
                data_classification=data_classification,
                allow_automatic_redaction=False,
                trusted_instructions=(
                    "Yalnız candidate_templates içindeki bir template_id seç. "
                    "Eksik zorunlu alan varsa eksik_bilgi_talebi_v1 dışında bir "
                    "şablon seçme. Belirsizlikte requires_human_review=true "
                    "döndür."
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


# ---------------------------------------------------------------------------
# LLM4 — seçilen şablonu doldurma
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class TemplateFillOutcome:
    call: LLMCallResult
    subject: str | None = None
    paragraphs: tuple[str, ...] = ()
    closing: str | None = None
    confidence: float | None = None


class LLMTemplateFillAgent:
    """LLM4: seçilen TEK şablonun içerik alanlarını (asla LaTeX değil) doldurur."""

    name = "LLM Şablon Doldurma Ajanı (LLM4)"

    def __init__(self, gateway: StructuredGateway) -> None:
        self.gateway = gateway

    def run(
        self,
        *,
        analysis: DocumentAnalysis,
        template_id: str,
        template_tex_reference: str,
        authority_relation: str,
        verified_references: Sequence[VerifiedReference],
        response_strategy: ResponseStrategyOption | None,
        response_custom_text: str | None,
        data_classification: DataClassification,
    ) -> TemplateFillOutcome:
        allowed_closings = list(
            ALLOWED_CLOSINGS_BY_RELATION.get(authority_relation, ())
        )
        properties: dict[str, Any] = {
            "subject": {"type": "string", "maxLength": 200},
            "paragraphs": {
                "type": "array",
                "items": {"type": "string", "maxLength": 500},
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
        result = self.gateway.invoke(
            StructuredLLMRequest(
                task=LLMTask.DRAFT_FIELDS,
                role=LegalAgentRole.DRAFTER,
                input_data={
                    "template_id": template_id,
                    # Reference-only: LLM4 must never emit LaTeX/markup back.
                    "template_structure_reference": truncate(
                        template_tex_reference, 4000
                    ),
                    "analysis": {
                        "document_type": analysis.document_type,
                        "summary": analysis.summary,
                        "fields": {
                            name: field.value
                            for name, field in analysis.fields.items()
                            if field.value
                        },
                    },
                    "verified_reference_excerpts": [
                        {
                            "chunk_id": reference.chunk_id,
                            "title": reference.title,
                            "excerpt": truncate(reference.excerpt, 500),
                        }
                        for reference in verified_references
                        if reference.verified
                    ][:6],
                    "response_strategy": (
                        {
                            "label": response_strategy.label,
                            "description": response_strategy.description,
                        }
                        if response_strategy is not None
                        else None
                    ),
                    "response_custom_text": response_custom_text,
                },
                output_schema=schema,
                data_classification=data_classification,
                allow_automatic_redaction=False,
                trusted_instructions=(
                    "template_structure_reference yalnız hangi alanların "
                    "doldurulacağını anlaman için verildi; ASLA LaTeX, "
                    "Markdown veya biçimlendirme kodu üretme, yalnız düz "
                    "metin resmi yazışma içeriği üret. Yalnız doğrulanmış "
                    "kanıtlarda (verified_reference_excerpts) veya analysis "
                    "içinde bulunan olgulara dayan; yeni olgu uydurma. "
                    "response_strategy verilmişse taslağın tonunu ona göre "
                    "belirle."
                ),
            )
        )
        if not result.succeeded or result.output is None:
            return TemplateFillOutcome(call=result)
        payload = result.output
        return TemplateFillOutcome(
            call=result,
            subject=str(payload["subject"]),
            paragraphs=tuple(str(item) for item in payload["paragraphs"]),
            closing=payload.get("closing"),
            confidence=None,
        )


# ---------------------------------------------------------------------------
# LLM5 — birim yönlendirme (org grafiği)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class RoutingOutcome:
    call: LLMCallResult
    selected_unit_id: str | None = None
    traversal_path: tuple[str, ...] = ()
    confidence: float | None = None
    rationale: str | None = None
    requires_human_review: bool = False


class LLMRoutingAgent:
    """LLM5: org şeması grafiğini (yalnız anonim JSON katalog) gezerek birim seçer."""

    name = "LLM Yönlendirme Ajanı (LLM5)"

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
        candidate_units = [unit for unit in units if unit.unit_id in allowed]
        schema = {
            "type": "object",
            "properties": {
                "selected_unit_id": {"type": "string", "enum": allowed},
                "traversal_path": {
                    "type": "array",
                    "items": {"type": "string", "maxLength": 120},
                    "maxItems": 6,
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
        result = self.gateway.invoke(
            StructuredLLMRequest(
                task=LLMTask.ROUTING,
                role=LegalAgentRole.ROUTER,
                input_data={
                    "analysis": {
                        "document_type": analysis.document_type,
                        "summary": analysis.summary,
                        "keywords": analysis.keywords,
                    },
                    "deterministic_unit_id": deterministic_routing.unit_id,
                    "units": [
                        {
                            "unit_id": unit.unit_id,
                            "unit_name": unit.unit_name,
                            "hierarchy": unit.hierarchy,
                            "parent_id": unit.parent_id,
                            "unit_type": unit.unit_type,
                            "keywords": unit.keywords,
                            "responsibilities": unit.responsibilities,
                        }
                        for unit in candidate_units
                    ],
                },
                output_schema=schema,
                data_classification=data_classification,
                allow_automatic_redaction=False,
                trusted_instructions=(
                    "units listesindeki parent_id alanlarını bir organizasyon "
                    "grafiği olarak kullan; üstten alta akıl yürüterek en "
                    "uygun birimi seç ve izlediğin yolu traversal_path olarak "
                    "birim adlarıyla döndür. Yalnız allowed listesindeki bir "
                    "unit_id seç. Belirsizlikte requires_human_review=true "
                    "döndür."
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


# ---------------------------------------------------------------------------
# LLM6 — yanıt stratejisi elde etme (insan-döngüde)
# ---------------------------------------------------------------------------

CUSTOM_RESPONSE_STRATEGY_OPTION_ID = "custom"

_FALLBACK_RESPONSE_STRATEGY_OPTIONS = (
    ResponseStrategyOption(
        option_id="kabul",
        label="Kabul ve gereğini yerine getir",
        description=(
            "Başvuru talebi kabul edilir ve gereği doğrudan yerine getirilir."
        ),
    ),
    ResponseStrategyOption(
        option_id="ek_bilgi_veya_red",
        label="Ek bilgi/mevzuat dayanağı iste veya reddet",
        description=(
            "Başvuru eksik bilgi, uygunsuz talep veya mevzuat dayanağı "
            "nedeniyle ek bilgi istenerek ya da reddedilerek yanıtlanır."
        ),
    ),
)


@dataclass(frozen=True, slots=True)
class ResponseStrategyProposalOutcome:
    call: LLMCallResult
    options: tuple[ResponseStrategyOption, ...] = ()


class LLMResponseStrategyAgent:
    """LLM6: taslak hazırlanmadan önce kullanıcıya yanıt stratejisi sorar."""

    name = "LLM Yanıt Stratejisi Ajanı (LLM6)"

    def __init__(self, gateway: StructuredGateway) -> None:
        self.gateway = gateway

    def run(
        self,
        *,
        analysis: DocumentAnalysis,
        verified_references: Sequence[VerifiedReference],
        data_classification: DataClassification,
    ) -> ResponseStrategyProposalOutcome:
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
                        },
                        "required": ["option_id", "label", "description"],
                        "additionalProperties": False,
                    },
                    "minItems": 2,
                    "maxItems": 4,
                },
            },
            "required": ["options"],
            "additionalProperties": False,
        }
        result = self.gateway.invoke(
            StructuredLLMRequest(
                task=LLMTask.SUMMARY,
                role=LegalAgentRole.RESPONSE_ADVISOR,
                input_data={
                    "analysis": {
                        "document_type": analysis.document_type,
                        "summary": analysis.summary,
                        "missing_fields": analysis.missing_fields,
                    },
                    "verified_reference_titles": [
                        reference.title
                        for reference in verified_references
                        if reference.verified
                    ][:10],
                },
                output_schema=schema,
                data_classification=data_classification,
                allow_automatic_redaction=False,
                trusted_instructions=(
                    "2 ile 4 arasında, birbirinden belirgin şekilde farklı "
                    "yanıt duruşu (ör. kabul, kısmi kabul, ek bilgi talebi, "
                    "red) öner. option_id kısa ve benzersiz olmalı, "
                    f"'{CUSTOM_RESPONSE_STRATEGY_OPTION_ID}' kullanma (o "
                    "seçenek ayrıca eklenecek)."
                ),
            )
        )
        if not result.succeeded or result.output is None:
            return ResponseStrategyProposalOutcome(
                call=result, options=_FALLBACK_RESPONSE_STRATEGY_OPTIONS
            )
        payload = result.output
        options = tuple(
            ResponseStrategyOption(
                option_id=str(item["option_id"]),
                label=str(item["label"]),
                description=str(item["description"]),
            )
            for item in payload["options"]
            if str(item["option_id"]) != CUSTOM_RESPONSE_STRATEGY_OPTION_ID
        )
        if not options:
            return ResponseStrategyProposalOutcome(
                call=result, options=_FALLBACK_RESPONSE_STRATEGY_OPTIONS
            )
        return ResponseStrategyProposalOutcome(call=result, options=options)


__all__ = [
    "CUSTOM_RESPONSE_STRATEGY_OPTION_ID",
    "LLMRoutingAgent",
    "LLMResponseStrategyAgent",
    "LLMTemplateFillAgent",
    "LLMTemplateSelectionAgent",
    "ResponseStrategyProposalOutcome",
    "RoutingOutcome",
    "TemplateCatalog",
    "TemplateCatalogEntry",
    "TemplateFillOutcome",
    "TemplateSelectionOutcome",
]
