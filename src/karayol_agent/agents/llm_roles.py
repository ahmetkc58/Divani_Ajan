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
from karayol_agent.document_types import COMPETITION_DOCUMENT_TYPES
from karayol_agent.schemas import (
    DocumentLayout,
    DocumentAnalysis,
    GraphDecisionTrace,
    Layer1Requirement,
    RoutingRecommendation,
    TemplateDecision,
    VerifiedReference,
)
from karayol_agent.text_utils import normalize_for_search


DOCUMENT_TYPES = COMPETITION_DOCUMENT_TYPES

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
    general_document_type: str | None = None
    document_subtype: str | None = None
    operational_category: str | None = None
    important_facts: tuple[str, ...] = ()
    rag_reference_ids: tuple[str, ...] = ()


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
    requirements: tuple[Layer1Requirement, ...] = ()
    missing_fields: tuple[str, ...] = ()
    format_violations: tuple[str, ...] = ()
    important_results: tuple[str, ...] = ()
    repair_attempted: bool = False
    repair_succeeded: bool = False
    repair_call: LLMCallResult | None = None
    initial_validation_warnings: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class _AdjudicationValidation:
    accepted_reference_ids: tuple[str, ...]
    unknown_reference_ids: tuple[str, ...]
    requirements: tuple[Layer1Requirement, ...]
    grounded_missing_fields: tuple[str, ...]
    unsupported_claims: tuple[str, ...]
    server_warnings: tuple[str, ...]
    invalid_requirements: tuple[Mapping[str, Any], ...]


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


def _layout_payload(layout: DocumentLayout | None) -> list[dict[str, Any]]:
    if layout is None:
        return []
    selected_lines = (
        layout.lines
        if len(layout.lines) <= 500
        else [*layout.lines[:300], *layout.lines[-200:]]
    )
    payload: list[dict[str, Any]] = []
    for line in selected_lines:
        item: dict[str, Any] = {
            "line_id": line.line_id,
            "page": line.page,
            "text": line.text,
            "source": line.source,
            "confidence": line.confidence,
        }
        if line.bbox is not None:
            item["bbox"] = line.bbox.model_dump(mode="json")
        else:
            item["bbox"] = None
        payload.append(item)
    return payload


def _reference_payload(references: list[VerifiedReference]) -> list[dict[str, Any]]:
    return [
        {
            "chunk_id": reference.chunk_id,
            "title": reference.title,
            "article": reference.article,
            "page": reference.page,
            "excerpt": reference.excerpt,
            "currentness_verified": reference.currentness_verified,
            "legal_reliance_allowed": reference.legal_reliance_allowed,
        }
        for reference in references
        if reference.verified
    ]


def _requirement_catalog_payload(
    analysis: DocumentAnalysis,
    references: list[VerifiedReference],
    curated_rules: list[Mapping[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Build a closed, source-addressable rule candidate set for LLM-2."""

    curated = [dict(rule) for rule in (curated_rules or [])]
    curated_reference_ids = {
        str(rule.get("legal_reference_id"))
        for rule in curated
        if rule.get("legal_reference_id")
    }
    broad_candidates = [
        {
            "rule_candidate_id": f"rule:{reference.chunk_id}",
            "document_type": analysis.general_document_type,
            "operational_category": analysis.operational_category,
            "legal_reference_id": reference.chunk_id,
            "title": reference.title,
            "article": reference.article,
            "rule_text": reference.excerpt,
        }
        for reference in references
        if reference.verified and reference.chunk_id not in curated_reference_ids
    ]
    return curated + broad_candidates


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
        references: list[VerifiedReference],
        document_type_candidates: list[Mapping[str, Any]],
        document_layout: DocumentLayout | None,
        data_classification: DataClassification,
    ) -> UnderstandingOutcome:
        field_properties = {
            name: _nullable_field_schema() for name in EXTRACTION_FIELDS
        }
        allowed_general_types = list(COMPETITION_DOCUMENT_TYPES)
        schema = {
            "type": "object",
            "properties": {
                "document_type": {
                    "type": "string",
                    "enum": list(DOCUMENT_TYPES),
                },
                "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                "summary": {"type": "string", "maxLength": 500},
                "general_document_type": {
                    "type": "string",
                    "enum": allowed_general_types,
                },
                "document_subtype": {"type": ["string", "null"], "maxLength": 160},
                "operational_category": {"type": "string", "maxLength": 120},
                "important_facts": {
                    "type": "array",
                    "items": {"type": "string", "maxLength": 400},
                    "maxItems": 10,
                },
                "rag_reference_ids": {
                    "type": "array",
                    "items": {"type": "string", "maxLength": 120},
                    "maxItems": 10,
                },
                "fields": {
                    "type": "object",
                    "properties": field_properties,
                    "required": list(EXTRACTION_FIELDS),
                    "additionalProperties": False,
                },
            },
            "required": [
                "document_type",
                "confidence",
                "summary",
                "fields",
                "general_document_type",
                "document_subtype",
                "operational_category",
                "important_facts",
                "rag_reference_ids",
            ],
            "additionalProperties": False,
        }
        request = StructuredLLMRequest(
                task=LLMTask.EXTRACTION,
                role=LegalAgentRole.RESEARCHER,
                input_data={
                    "document_text": _head_and_tail(text),
                    "document_lines": _layout_payload(document_layout),
                    "rag_candidates": _reference_payload(references),
                    "document_type_candidates": document_type_candidates,
                    "allowed_document_types": list(COMPETITION_DOCUMENT_TYPES),
                    "document_type_definitions": {
                        "dilekce": "Başka bir özel sınıfa girmeyen genel dilekçe/başvuru; son seçenek olarak kullan.",
                        "sikayet": "Şikâyet, mağduriyet, zarar/hasar veya güvenlik sorunu bildirimi.",
                        "itiraz": "Bir karar, işlem, ceza veya değerlendirmeye karşı itiraz.",
                        "talep": "Bir hizmetin ya da idari işlemin yapılması talebi; açık izin/ruhsat talepleri hariç.",
                        "izin": "İzin, ruhsat, ön izin, geçiş izni verilmesi veya yenilenmesi talebi.",
                        "belge": "Bilgi edinme, belge/kayıt sureti veya doküman isteme.",
                    },
                    "deterministic_document_type": deterministic_analysis.document_type,
                    "deterministic_summary": deterministic_analysis.summary,
                    "deterministic_missing_fields": deterministic_analysis.missing_fields,
                },
                output_schema=schema,
                data_classification=data_classification,
                allow_automatic_redaction=(
                    data_classification is DataClassification.REDACTED
                ),
                trusted_instructions=(
                    "Belgeyi verilen RAG adayları ve belge kanıtlarıyla anla ve sınıflandır. "
                    "document_type ve general_document_type alanlarını yalnız verilen altılı "
                    "allowed_document_types listesinden seç ve ikisini aynı değer yap. "
                    "Yol bakımı, hasar veya trafik güvenliği gibi konuları evrak türü yapma; "
                    "bunları operational_category alanında belirt. Her alan için değer ile "
                    "Belgenin idari amacına göre en özel türü seç: açık izin/ruhsat başvurusu "
                    "izin, bilgi veya belge istemi belge, karar karşıtı başvuru itiraz, şikâyet "
                    "ve hasar bildirimi sikayet olmalıdır. dilekce yalnız daha özel bir tür "
                    "uygun değilse kullanılmalıdır. document_subtype alanına talep/izin gibi "
                    "genel sözcükler yerine mümkünse özgül işlem adını yaz. "
                    "birlikte belgeden birebir kısa kanıt parçası ver; açık kanıt yoksa "
                    "hem value hem evidence null olsun. Göndereni üstbilgi, hitap ve "
                    "imza bloğunu birlikte değerlendirerek seç. Özette yeni olgu ekleme. "
                    "rag_reference_ids yalnızca verilen chunk_id veya candidate_id "
                    "değerlerinden oluşmalı. document_type_candidates listesini yalnız belge "
                    "alt türüne yardımcı kanıt olarak kullan; oradaki serbest etiketi evrak "
                    "türüne kopyalama. "
                    "Sınıflandırma kanıtında en az bir mevzuat chunk_id ve bir DETSIS "
                    "candidate_id kullan; yeterli kanıt yoksa deterministik türü koru."
                ),
            )
        result = self.gateway.invoke(request)
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
            general_document_type=(
                str(payload["general_document_type"])
                if payload.get("general_document_type")
                else None
            ),
            document_subtype=(
                str(payload["document_subtype"])
                if payload.get("document_subtype")
                else None
            ),
            operational_category=(
                str(payload["operational_category"])
                if payload.get("operational_category")
                else None
            ),
            important_facts=tuple(
                str(item) for item in payload.get("important_facts", [])
            ),
            rag_reference_ids=tuple(
                str(item) for item in payload.get("rag_reference_ids", [])
            ),
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
        document_layout: DocumentLayout | None,
        data_classification: DataClassification,
        curated_requirement_rules: list[Mapping[str, Any]] | None = None,
    ) -> AdjudicationOutcome:
        if not allowed_template_ids or not allowed_unit_ids:
            raise ValueError("Adjudicator kapalı şablon ve birim adayları gerektirir.")
        verified_references = [reference for reference in references if reference.verified]
        verified_ids = {reference.chunk_id for reference in verified_references}
        curated_fields = sorted(
            {
                str(rule.get("field"))
                for rule in (curated_requirement_rules or [])
                if rule.get("field")
            }
        )
        requirement_field_schema: dict[str, Any] = {
            "type": "string",
            "maxLength": 120,
        }
        if curated_fields:
            requirement_field_schema["enum"] = curated_fields
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
                "requirements": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "field": requirement_field_schema,
                            "requirement": {"type": "string", "maxLength": 600},
                            "status": {
                                "type": "string",
                                "enum": ["present", "missing", "ambiguous", "not_applicable"],
                            },
                            "document_evidence_ids": {
                                "type": "array",
                                "items": {"type": "string", "maxLength": 120},
                                "maxItems": 20,
                            },
                            "legal_reference_ids": {
                                "type": "array",
                                "items": reference_item_schema,
                                "maxItems": min(10, len(verified_ids)),
                            },
                            "legal_evidence": {
                                "type": "string",
                                "maxLength": 500,
                            },
                            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                        },
                        "required": [
                            "field", "requirement", "status", "document_evidence_ids",
                            "legal_reference_ids", "legal_evidence", "confidence"
                        ],
                        "additionalProperties": False,
                    },
                    "maxItems": 40,
                },
                "missing_fields": {
                    "type": "array",
                    "items": {"type": "string", "maxLength": 120},
                    "maxItems": 40,
                },
                "format_violations": {
                    "type": "array",
                    "items": {"type": "string", "maxLength": 400},
                    "maxItems": 20,
                },
                "important_results": {
                    "type": "array",
                    "items": {"type": "string", "maxLength": 500},
                    "maxItems": 15,
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
                "requirements",
                "missing_fields",
                "format_violations",
                "important_results",
            ],
            "additionalProperties": False,
        }
        graph_payload = (
            graph_trace.model_dump(mode="json")
            if graph_trace is not None
            else {"strategy": "not_available", "applied": False}
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
            candidate["excerpt"] = reference.excerpt
            researcher_candidates.append(candidate)
        request = StructuredLLMRequest(
                task=LLMTask.ADJUDICATION,
                role=LegalAgentRole.ADJUDICATOR,
                input_data={
                    "researcher_candidates": researcher_candidates,
                    "requirement_catalog": _requirement_catalog_payload(
                        analysis,
                        verified_references,
                        curated_requirement_rules,
                    ),
                    "auditor_verified_reference_ids": sorted(verified_ids),
                    "analysis": {
                        "document_type": analysis.document_type,
                        "general_document_type": analysis.general_document_type,
                        "document_subtype": analysis.document_subtype,
                        "operational_category": analysis.operational_category,
                        "summary": analysis.summary,
                        "missing_fields": analysis.missing_fields,
                    },
                    "document_lines": _layout_payload(document_layout),
                    "deterministic_template_id": template_decision.template_id,
                    "deterministic_unit_id": routing.unit_id,
                    "allowed_template_ids": sorted(set(allowed_template_ids)),
                    "allowed_unit_ids": sorted(set(allowed_unit_ids)),
                    "graph_advice": graph_payload,
                },
                output_schema=schema,
                data_classification=data_classification,
                allow_automatic_redaction=(
                    data_classification is DataClassification.REDACTED
                ),
                trusted_instructions=(
                    "Researcher kapalı aday listesini ve Auditor tarafından doğrulanmış "
                    "kimlikleri "
                    "kullan. Yalnız allowlist içindeki şablon/birimi seç. Kabul edilen "
                    "referanslar Auditor listesinin alt kümesi olmalı. currentness_verified "
                    "ve legal_reliance_allowed false ise bunu kesin hukuk hükmü sayma. "
                    "Sentetik graf yalnız karar desteğidir. Çelişki veya yetersiz kanıtta "
                    "requires_human_review=true döndür. requirement_catalog başındaki "
                    "denetlenmiş atomik kuralları geniş mevzuat adaylarından önce kullan. "
                    "Denetlenmiş kurallar varsa requirements dizisindeki field değerlerini "
                    "yalnız bu kuralların field alanlarından seç; yeni veya birleşik alan adı "
                    "uydurma. Her kural için legal_reference_ids alanına aynı katalog kaydındaki "
                    "legal_reference_id değerini, legal_evidence alanına rule_text değerini "
                    "birebir kopyala. Denetlenmiş katalogdaki her kural için, present, missing, "
                    "ambiguous veya not_applicable durumlarından biriyle tam olarak bir "
                    "requirement döndür; mevcut kuralları sonuçtan atlama. "
                    "absence_is_missing=false olan bir kuralın yokluğunu kesin eksik sayma; "
                    "applicability=conditional ise uygulanabilirlik belge kanıtı yokken "
                    "missing yerine not_applicable veya ambiguous kullan. Seçilen evrak türünün zorunlu "
                    "alanlarını ve yazım/konum şartlarını mevzuat parçalarından çıkar; her "
                    "şartı legal_reference_ids ile bağla ve dayanak parçadan birebir kısa alıntıyı "
                    "legal_evidence alanına yaz. Belgede bulunan şartlar için yalnız verilen "
                    "line_id değerlerini document_evidence_ids alanında kullan; bbox koordinatlarıyla "
                    "başlık, tarih, imza ve diğer konumsal şartları değerlendir. Eksik, "
                    "belirsiz ve biçim ihlallerini açıkça bildir; önemli neticeleri özetle."
                ),
            )
        result = self.gateway.invoke(request)
        if not result.succeeded or result.output is None:
            return AdjudicationOutcome(call=result, requires_human_review=True)
        payload = result.output
        initial_validation = self._validate_payload(
            payload,
            verified_references=verified_references,
            document_layout=document_layout,
            curated_requirement_rules=curated_requirement_rules,
        )
        selected_result = result
        selected_payload = payload
        selected_validation = initial_validation
        repair_call: LLMCallResult | None = None
        repair_attempted = bool(initial_validation.server_warnings)
        repair_succeeded = False
        if repair_attempted:
            repair_request = StructuredLLMRequest(
                task=request.task,
                role=request.role,
                input_data={
                    **request.input_data,
                    "repair_context": {
                        "previous_output": payload,
                        "server_validation_errors": list(
                            initial_validation.server_warnings
                        ),
                        "invalid_requirements": list(
                            initial_validation.invalid_requirements
                        ),
                    },
                },
                output_schema=request.output_schema,
                data_classification=request.data_classification,
                allow_automatic_redaction=request.allow_automatic_redaction,
                trusted_instructions=(
                    request.trusted_instructions
                    + " Bu bir doğrulama düzeltme turudur. Önceki çıktının tamamını "
                    "sunucu hatalarına göre düzelt. Her requirement için legal_evidence "
                    "alanına yalnız cited legal_reference_ids içindeki excerpt/rule_text "
                    "değerinden birebir kısa alıntı yaz. present durumunda geçerli line_id "
                    "zorunludur; missing durumunda document_evidence_ids boş olmalıdır. "
                    "Yalnız doğrulanabilen şartları döndür."
                ),
            )
            repair_call = self.gateway.invoke(repair_request)
            if repair_call.succeeded and repair_call.output is not None:
                repaired_validation = self._validate_payload(
                    repair_call.output,
                    verified_references=verified_references,
                    document_layout=document_layout,
                    curated_requirement_rules=curated_requirement_rules,
                )
                if len(repaired_validation.server_warnings) < len(
                    initial_validation.server_warnings
                ) and len(repaired_validation.requirements) >= len(
                    initial_validation.requirements
                ):
                    selected_result = repair_call
                    selected_payload = repair_call.output
                    selected_validation = repaired_validation
                    repair_succeeded = True
        return AdjudicationOutcome(
            call=selected_result,
            selected_template_id=(
                str(selected_payload["selected_template_id"])
                if selected_payload.get("selected_template_id")
                else None
            ),
            selected_unit_id=(
                str(selected_payload["selected_unit_id"])
                if selected_payload.get("selected_unit_id")
                else None
            ),
            accepted_reference_ids=selected_validation.accepted_reference_ids,
            confidence=(
                float(selected_payload["confidence"])
                if selected_payload.get("confidence") is not None
                else None
            ),
            rationale=str(selected_payload.get("rationale", "")),
            requires_human_review=(
                bool(selected_payload.get("requires_human_review", False))
                or bool(selected_validation.unknown_reference_ids)
            ),
            unsupported_claims=selected_validation.unsupported_claims,
            requirements=selected_validation.requirements,
            missing_fields=selected_validation.grounded_missing_fields,
            format_violations=tuple(
                str(item) for item in selected_payload.get("format_violations", [])
            ),
            important_results=tuple(
                str(item) for item in selected_payload.get("important_results", [])
            ),
            repair_attempted=repair_attempted,
            repair_succeeded=repair_succeeded,
            repair_call=repair_call,
            initial_validation_warnings=initial_validation.server_warnings,
        )

    @staticmethod
    def _validate_payload(
        payload: Mapping[str, Any],
        *,
        verified_references: list[VerifiedReference],
        document_layout: DocumentLayout | None,
        curated_requirement_rules: list[Mapping[str, Any]] | None = None,
    ) -> _AdjudicationValidation:
        verified_by_id = {
            reference.chunk_id: reference for reference in verified_references
        }
        verified_ids = set(verified_by_id)
        raw_accepted_ids = tuple(
            str(item) for item in payload.get("accepted_reference_ids", [])
        )
        unknown_reference_ids = tuple(
            sorted(set(raw_accepted_ids) - verified_ids)
        )
        accepted_ids = tuple(
            item for item in raw_accepted_ids if item in verified_ids
        )
        effective_accepted_ids = set(accepted_ids)
        line_by_id = {
            line.line_id: line
            for line in (document_layout.lines if document_layout else [])
        }
        curated_by_field: dict[str, list[Mapping[str, Any]]] = {}
        for rule in curated_requirement_rules or []:
            field_name = str(rule.get("field") or "")
            if field_name:
                curated_by_field.setdefault(field_name, []).append(rule)
        server_warnings: list[str] = []
        invalid_requirements: list[Mapping[str, Any]] = []
        requirements: list[Layer1Requirement] = []

        for raw_requirement in payload.get("requirements", []):
            if not isinstance(raw_requirement, Mapping):
                server_warnings.append("Adsız şart: yapılandırılmış şart nesnesi geçersiz.")
                continue
            field_name = str(raw_requirement.get("field") or "adsız_şart")
            cited_refs = tuple(
                str(item)
                for item in raw_requirement.get("legal_reference_ids", [])
            )
            cited_lines = tuple(
                str(item)
                for item in raw_requirement.get("document_evidence_ids", [])
            )
            legal_evidence = str(raw_requirement.get("legal_evidence") or "").strip()
            reason: str | None = None
            if not cited_refs or not set(cited_refs) <= verified_ids:
                reason = "doğrulanmış mevzuat kaynağına bağlı değil"
            elif not legal_evidence:
                reason = "birebir mevzuat dayanak alıntısı içermiyor"
            elif not any(
                normalize_for_search(legal_evidence)
                in normalize_for_search(verified_by_id[reference_id].excerpt)
                for reference_id in cited_refs
            ):
                reason = "legal_evidence alıntısı cited mevzuat parçalarında bulunamadı"
            elif not set(cited_lines) <= set(line_by_id):
                reason = "bilinmeyen belge line_id değeri içeriyor"
            status = str(raw_requirement.get("status") or "")
            scoped_rules = curated_by_field.get(field_name, [])
            scoped_reference_ids = {
                str(rule.get("legal_reference_id"))
                for rule in scoped_rules
                if rule.get("legal_reference_id")
            }
            cited_scoped_rules = [
                rule
                for rule in scoped_rules
                if str(rule.get("legal_reference_id")) in cited_refs
            ]
            if (
                reason is None
                and status in {"missing", "ambiguous"}
                and scoped_reference_ids
                and not scoped_reference_ids.intersection(cited_refs)
            ):
                reason = "seçilmiş denetlenmiş alan kuralına bağlı değil"
            if (
                reason is None
                and status in {"missing", "ambiguous"}
                and cited_scoped_rules
                and not any(
                    bool(rule.get("absence_is_missing", False))
                    for rule in cited_scoped_rules
                )
            ):
                reason = "kuralın yokluğu kesin eksik üretmeye yetkili değil"
            if reason is None and status == "present" and not cited_lines:
                reason = "mevcut denilen şart belge satır kanıtı içermiyor"
            if reason is None and status == "missing" and cited_lines:
                reason = "eksik denilen şart çelişkili biçimde belge satırı içeriyor"
            if reason is not None:
                server_warnings.append(f"{field_name}: {reason}.")
                invalid_requirements.append(dict(raw_requirement))
                continue
            try:
                requirement = Layer1Requirement.model_validate(raw_requirement)
            except (TypeError, ValueError):
                server_warnings.append(f"{field_name}: kapalı şart şemasından geçmedi.")
                invalid_requirements.append(dict(raw_requirement))
                continue

            evidence_lines = [line_by_id[line_id] for line_id in cited_lines]
            if requirement.status == "present":
                document_presence_score: float | None = round(
                    sum(
                        line.confidence if line.confidence is not None else 1.0
                        for line in evidence_lines
                    )
                    / len(evidence_lines),
                    4,
                )
            elif requirement.status == "missing":
                document_presence_score = 0.0
            elif requirement.status == "ambiguous":
                document_presence_score = (
                    round(
                        sum(
                            line.confidence if line.confidence is not None else 1.0
                            for line in evidence_lines
                        )
                        / len(evidence_lines),
                        4,
                    )
                    if evidence_lines
                    else 0.5
                )
            else:
                document_presence_score = None
            coordinate_confidence = (
                round(
                    sum(
                        (line.confidence if line.confidence is not None else 1.0)
                        if line.bbox is not None
                        else 0.0
                        for line in evidence_lines
                    )
                    / len(evidence_lines),
                    4,
                )
                if evidence_lines
                else None
            )
            requirements.append(
                requirement.model_copy(
                    update={
                        "legal_support_score": 1.0,
                        "document_presence_score": document_presence_score,
                        "coordinate_confidence": coordinate_confidence,
                    }
                )
            )
            effective_accepted_ids.update(cited_refs)

        grounded_missing = {
            requirement.field
            for requirement in requirements
            if requirement.status in {"missing", "ambiguous"}
        }
        requested_missing = {
            str(item) for item in payload.get("missing_fields", [])
        }
        for field_name in sorted(requested_missing - grounded_missing):
            server_warnings.append(
                f"{field_name}: missing_fields kaydı kanıtlanmış eksik/belirsiz şarta bağlı değil."
            )
        if unknown_reference_ids:
            server_warnings.append(
                "Auditor kümesi dışında referans kimliği döndürüldü: "
                + ", ".join(unknown_reference_ids)
                + "."
            )
        model_unsupported = tuple(
            str(item) for item in payload.get("unsupported_claims", [])
        )
        return _AdjudicationValidation(
            accepted_reference_ids=tuple(sorted(effective_accepted_ids)),
            unknown_reference_ids=unknown_reference_ids,
            requirements=tuple(requirements),
            grounded_missing_fields=tuple(sorted(grounded_missing)),
            unsupported_claims=(*model_unsupported, *server_warnings),
            server_warnings=tuple(server_warnings),
            invalid_requirements=tuple(invalid_requirements),
        )
