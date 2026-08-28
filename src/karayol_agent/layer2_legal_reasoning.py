"""Independent, source-only Layer-2 legal content assessment.

This module adapts two research designs without exposing hidden chain-of-thought:

* LegalGraphRAG: Researcher -> Auditor -> Adjudicator with verify-and-prune.
* Search-o1: bounded search requests followed by a separate document-refinement
  pass before evidence is admitted to legal reasoning.

LLMs are untrusted proposal generators.  Only current, legally-reliable sources,
exact source quotes and known document line IDs can survive the server gates.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Any, Literal, Protocol

from pydantic import BaseModel, Field

from karayol_agent.llm.contracts import (
    DataClassification,
    FallbackAction,
    LLMCallResult,
    LLMTask,
    LegalAgentRole,
    StructuredLLMRequest,
)
from karayol_agent.retrieval.requirement_rules import (
    RequirementRule,
    RequirementRuleRepository,
)
from karayol_agent.schemas import DocumentAnalysis, DocumentLayout, VerifiedReference
from karayol_agent.text_utils import normalize_for_search, tokenize


class Layer2Gateway(Protocol):
    config: Any

    def invoke(self, request: StructuredLLMRequest) -> LLMCallResult: ...


class Layer2ToolTrace(BaseModel):
    round: int = Field(ge=1)
    requested_tool: str
    executed_tool: str
    legal_issue: str | None = None
    issue_scope: str | None = None
    query: str = ""
    returned_reference_ids: list[str] = Field(default_factory=list)
    returned_line_ids: list[str] = Field(default_factory=list)
    note: str = ""


class Layer2AgentTrace(BaseModel):
    role: Literal["researcher", "reason_in_documents", "auditor", "adjudicator"]
    status: str
    model: str
    network_attempted: bool = False
    failure_code: str | None = None
    note: str = ""


class Layer2Finding(BaseModel):
    issue: str
    document_statement: str
    applicability: Literal["applicable", "conditional", "contextual_only", "uncertain"]
    legal_relationship: Literal[
        "supports",
        "limits",
        "defines_procedure",
        "creates_obligation",
        "prohibits",
        "unclear",
    ]
    legal_assessment: str
    practical_effect: str
    risk_level: Literal["low", "medium", "high", "uncertain"]
    legal_reference_id: str
    equivalent_reference_ids: list[str] = Field(default_factory=list)
    legal_title: str
    legal_article: str | None = None
    legal_quote: str
    document_evidence_ids: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0, le=1)
    source_only_validated: bool = True


class Layer2Assessment(BaseModel):
    status: Literal["completed", "abstained", "disabled", "failed"]
    model: str = "llm-large"
    document_type: str
    operational_category: str | None = None
    summary: str
    findings: list[Layer2Finding] = Field(default_factory=list)
    important_results: list[str] = Field(default_factory=list)
    accepted_reference_ids: list[str] = Field(default_factory=list)
    rejected_reference_ids: list[str] = Field(default_factory=list)
    validation_warnings: list[str] = Field(default_factory=list)
    requires_human_review: bool = True
    source_only_policy_applied: bool = True
    tool_trace: list[Layer2ToolTrace] = Field(default_factory=list)
    agent_trace: list[Layer2AgentTrace] = Field(default_factory=list)


@dataclass(frozen=True, slots=True)
class _Candidate:
    reference: VerifiedReference
    field: str
    requirement: str
    rule_kind: str
    applicability: str
    absence_is_missing: bool
    severity: str
    research_issue: str | None = None
    research_scope: str | None = None


_TOOL_NAMES = (
    "search_curated_rules",
    "search_reliable_legislation",
    "get_document_lines",
    "get_document_layout",
    "finish_research",
)


def _object_schema(properties: Mapping[str, Any], required: Sequence[str]) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": dict(properties),
        "required": list(required),
        "additionalProperties": False,
    }


def _tool_schema() -> dict[str, Any]:
    issue = _object_schema(
        {
            "issue": {"type": "string", "maxLength": 180},
            "query": {"type": "string", "maxLength": 300},
            "document_basis": {"type": "string", "maxLength": 300},
            "scope": {
                "type": "string",
                "enum": ["general_procedure", "sector_specific", "technical"],
            },
        },
        ("issue", "query", "document_basis", "scope"),
    )
    item = _object_schema(
        {
            "tool": {"type": "string", "enum": list(_TOOL_NAMES)},
            "query": {"type": "string", "maxLength": 300},
            "reference_ids": {
                "type": "array",
                "items": {"type": "string", "maxLength": 120},
                "maxItems": 12,
            },
            "line_ids": {
                "type": "array",
                "items": {"type": "string", "maxLength": 120},
                "maxItems": 30,
            },
        },
        ("tool", "query", "reference_ids", "line_ids"),
    )
    return _object_schema(
        {
            "legal_issues": {
                "type": "array",
                "items": issue,
                "minItems": 3,
                "maxItems": 4,
            },
            "knowledge_gaps": {
                "type": "array",
                "items": {"type": "string", "maxLength": 300},
                "maxItems": 8,
            },
            "tool_calls": {"type": "array", "items": item, "maxItems": 6},
        },
        ("legal_issues", "knowledge_gaps", "tool_calls"),
    )


def _refinement_schema() -> dict[str, Any]:
    item = _object_schema(
        {
            "reference_id": {"type": "string", "maxLength": 120},
            "focused_quote": {"type": "string", "maxLength": 500},
            "scope_note": {"type": "string", "maxLength": 400},
            "document_evidence_ids": {
                "type": "array",
                "items": {"type": "string", "maxLength": 120},
                "maxItems": 20,
            },
            "keep": {"type": "boolean"},
        },
        (
            "reference_id",
            "focused_quote",
            "scope_note",
            "document_evidence_ids",
            "keep",
        ),
    )
    return _object_schema(
        {"refined_documents": {"type": "array", "items": item, "maxItems": 16}},
        ("refined_documents",),
    )


def _audit_schema() -> dict[str, Any]:
    item = _object_schema(
        {
            "reference_id": {"type": "string", "maxLength": 120},
            "applicability": {
                "type": "string",
                "enum": [
                    "applicable", "not_applicable", "conditional",
                    "contextual_only", "insufficient_evidence",
                ],
            },
            "legal_relationship": {
                "type": "string",
                "enum": [
                    "supports",
                    "limits",
                    "defines_procedure",
                    "creates_obligation",
                    "prohibits",
                    "unclear",
                ],
            },
            "legal_quote": {"type": "string", "maxLength": 500},
            "applicability_evidence_ids": {
                "type": "array",
                "items": {"type": "string", "maxLength": 120},
                "maxItems": 20,
            },
            "issue": {"type": "string", "maxLength": 300},
            "document_statement": {"type": "string", "maxLength": 500},
            "legal_analysis": {"type": "string", "maxLength": 700},
            "practical_effect": {"type": "string", "maxLength": 500},
            "risk_level": {
                "type": "string",
                "enum": ["low", "medium", "high", "uncertain"],
            },
            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        },
        (
            "reference_id",
            "applicability",
            "legal_relationship",
            "legal_quote",
            "applicability_evidence_ids",
            "issue",
            "document_statement",
            "legal_analysis",
            "practical_effect",
            "risk_level",
            "confidence",
        ),
    )
    return _object_schema(
        {"audits": {"type": "array", "items": item, "maxItems": 20}},
        ("audits",),
    )


def _adjudication_schema() -> dict[str, Any]:
    item = _object_schema(
        {
            "reference_id": {"type": "string", "maxLength": 120},
            "applicability": {
                "type": "string",
                "enum": ["applicable", "conditional", "contextual_only", "uncertain"],
            },
            "legal_relationship": {
                "type": "string",
                "enum": [
                    "supports",
                    "limits",
                    "defines_procedure",
                    "creates_obligation",
                    "prohibits",
                    "unclear",
                ],
            },
            "issue": {"type": "string", "maxLength": 300},
            "document_statement": {"type": "string", "maxLength": 500},
            "legal_assessment": {"type": "string", "maxLength": 700},
            "practical_effect": {"type": "string", "maxLength": 500},
            "risk_level": {
                "type": "string",
                "enum": ["low", "medium", "high", "uncertain"],
            },
            "document_evidence_ids": {
                "type": "array",
                "items": {"type": "string", "maxLength": 120},
                "maxItems": 20,
            },
            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        },
        (
            "reference_id", "applicability", "legal_relationship", "issue",
            "document_statement", "legal_assessment", "practical_effect",
            "risk_level", "document_evidence_ids", "confidence",
        ),
    )
    return _object_schema(
        {
            "summary": {"type": "string", "maxLength": 700},
            "findings": {"type": "array", "items": item, "maxItems": 20},
            "important_results": {
                "type": "array",
                "items": {"type": "string", "maxLength": 500},
                "maxItems": 12,
            },
            "requires_human_review": {"type": "boolean"},
        },
        ("summary", "findings", "important_results", "requires_human_review"),
    )


class Layer2LegalReasoning:
    """Bounded agentic legal assessment with fail-closed source grounding."""

    def __init__(
        self,
        gateway: Layer2Gateway,
        requirement_rules: RequirementRuleRepository,
        *,
        enabled: bool = True,
        max_search_rounds: int = 4,
        legal_search: Callable[[str, DocumentAnalysis], Sequence[VerifiedReference]] | None = None,
    ) -> None:
        self.gateway = gateway
        self.requirement_rules = requirement_rules
        self.enabled = enabled
        self.max_search_rounds = max(1, min(int(max_search_rounds), 4))
        self.legal_search = legal_search

    def run(
        self,
        *,
        analysis: DocumentAnalysis,
        text: str,
        layout: DocumentLayout | None,
        references: Sequence[VerifiedReference],
        data_classification: DataClassification,
        progress: Callable[[str, str], None] | None = None,
    ) -> Layer2Assessment:
        def emit(agent: str, message: str) -> None:
            if progress is not None:
                progress(agent, message)

        model = str(getattr(self.gateway.config, "model", "llm-large"))
        base = dict(
            model=model,
            document_type=analysis.document_type,
            operational_category=analysis.operational_category,
        )
        if not self.enabled:
            return Layer2Assessment(
                status="disabled", summary="Katman-2 yapılandırmayla kapalı.", **base
            )

        lines = {line.line_id: line for line in (layout.lines if layout else [])}
        rules = self.requirement_rules.select(analysis)
        candidates = self._build_candidates(rules, references)
        reliable = {
            key: candidate
            for key, candidate in candidates.items()
            if self._source_usable(candidate.reference)
        }
        rejected = sorted(set(candidates) - set(reliable))
        if not reliable and self.legal_search is None:
            return Layer2Assessment(
                status="abstained",
                summary=(
                    "Metni ve kaynak izi doğrulanmış bir mevzuat kaynağı bulunmadığı için "
                    "Katman-2 değerlendirmeden kaçındı."
                ),
                rejected_reference_ids=rejected,
                validation_warnings=["Model önbilgisi hukuki kaynak yerine kullanılmadı."],
                **base,
            )

        tool_trace: list[Layer2ToolTrace] = []
        agent_trace: list[Layer2AgentTrace] = []
        plan_warnings: list[str] = []
        # Katman 2 eksiklik/form denetçisi değildir. Katman 1'in atomik
        # zorunlu alan ve ek kuralları otomatik içerik bulgusuna dönüştürülmez.
        selected_ids: list[str] = []
        prior_results: list[dict[str, Any]] = []
        executed_legal_queries: set[str] = set()
        legal_query_count = 0
        planned_issue_calls: list[dict[str, Any]] = []
        refined: dict[str, dict[str, Any]] = {}
        equivalent_groups: dict[str, list[str]] = {}
        emit("Katman 2 Araştırmacı", "Hukuki meseleler çıkarılıyor.")
        for round_number in range(1, self.max_search_rounds + 1):
            call = self._invoke(
                task=LLMTask.EVIDENCE_AUDIT,
                role=LegalAgentRole.RESEARCHER,
                schema=_tool_schema(),
                classification=data_classification,
                input_data={
                    "document": self._document_payload(analysis, text),
                    "available_tools": list(_TOOL_NAMES),
                    "prior_tool_results": prior_results,
                    "round": round_number,
                    "max_rounds": self.max_search_rounds,
                },
                instructions=(
                    "DECOMPOSITION POLICY: Split the document into exactly 3 or 4 distinct "
                    "legal issues. Produce one concise legislation query per issue using only "
                    "facts visible in the document and copy a short, distinct document_basis "
                    "for every issue. Include at least one general application, "
                    "procedure, or right issue and at least one sector-specific issue. If the "
                    "document contains a technical event, make it a separate issue. Do not "
                    "repeat an issue with synonyms and do not paste the whole document into one "
                    "broad query. Set legal_issues accordingly. "
                    "Search-o1 araştırmacısısın. Ön bilgiyle hukuk sonucu üretme. "
                    "Belgedeki maddi olayları, iddiaları, talepleri ve hukuki meseleleri araştır. "
                    "Adres, imza, gönderen, tarih veya ek var/yok kontrolü Katman 1'e aittir; "
                    "bunlar için bulgu üretme. Yalnız kapalı araçlardan hedefli arama iste; "
                    "nihai değerlendirme veya mevzuat adı uydurma."
                ),
            )
            agent_trace.append(self._agent_trace("researcher", call, model, round_number))
            emit(
                "Katman 2 Araştırmacı",
                f"Arama turu {round_number} tamamlandı; araç planı oluşturuldu.",
            )
            output = call.output if call.succeeded and call.output else {}
            calls = output.get("tool_calls", []) if isinstance(output, Mapping) else []
            if not isinstance(calls, list):
                calls = []
            calls = list(calls)
            issue_calls: list[dict[str, Any]] = []
            legal_issues = output.get("legal_issues", []) if isinstance(output, Mapping) else []
            if round_number == 1 and isinstance(legal_issues, list):
                validated_issues, plan_errors = self._issue_plan(legal_issues)
                if legal_issues and plan_errors:
                    emit(
                        "Katman 2 Araştırmacı",
                        "Sorgu planında tekrar veya tür eksikliği bulundu; plan düzeltiliyor.",
                    )
                    repair_call = self._invoke(
                        task=LLMTask.EVIDENCE_AUDIT,
                        role=LegalAgentRole.RESEARCHER,
                        schema=_tool_schema(),
                        classification=data_classification,
                        input_data={
                            "document": self._document_payload(analysis, text),
                            "rejected_plan": legal_issues,
                            "validation_errors": plan_errors,
                        },
                        instructions=(
                            "Yalnız sorgu planını düzelt. Üç veya dört farklı evrak dayanağı "
                            "kullan; bir general_procedure ve en az bir sector_specific veya "
                            "technical mesele üret. Tekrarlı sorguları eşanlamlılarla yeniden "
                            "yazma, gerçekten farklı bir mesele seç. Mevzuat veya madde uydurma."
                        ),
                    )
                    agent_trace.append(
                        self._agent_trace("researcher", repair_call, model, round_number)
                    )
                    repair_output = (
                        repair_call.output
                        if repair_call.succeeded and repair_call.output
                        else {}
                    )
                    validated_issues, plan_errors = self._issue_plan(
                        repair_output.get("legal_issues", [])
                        if isinstance(repair_output, Mapping)
                        else []
                    )
                plan_warnings.extend(plan_errors)
                if not plan_errors:
                    planned_issue_calls = [
                        {
                            "tool": "search_reliable_legislation",
                            "legal_issue": issue["issue"],
                            "issue_scope": issue["scope"],
                            "document_basis": issue["document_basis"],
                            "query": issue["query"],
                            "reference_ids": [],
                            "line_ids": [],
                        }
                        for issue in validated_issues
                    ]
            # Modelin tool_calls şeması mesele alanı taşımadığından, sorguyu aynı
            # yanıttaki legal_issues kaydıyla deterministik olarak etiketle. Bu
            # etiket daha sonra farklı meselelerden kaynak seçimini korur.
            if isinstance(legal_issues, list):
                enriched_calls: list[Any] = []
                for raw_call in calls:
                    if not isinstance(raw_call, Mapping):
                        enriched_calls.append(raw_call)
                        continue
                    enriched = dict(raw_call)
                    if enriched.get("tool") == "search_reliable_legislation":
                        call_tokens = set(
                            tokenize(normalize_for_search(str(enriched.get("query") or "")))
                        )
                        matches: list[tuple[int, Mapping[str, Any]]] = []
                        for raw_issue in legal_issues:
                            if not isinstance(raw_issue, Mapping):
                                continue
                            issue_tokens = set(
                                tokenize(normalize_for_search(str(raw_issue.get("query") or "")))
                            )
                            matches.append((len(call_tokens & issue_tokens), raw_issue))
                        if matches:
                            _, matched = max(matches, key=lambda item: item[0])
                            enriched["legal_issue"] = str(matched.get("issue") or "")
                            enriched["issue_scope"] = str(matched.get("scope") or "")
                    enriched_calls.append(enriched)
                calls = enriched_calls
            if planned_issue_calls and round_number <= len(planned_issue_calls):
                # One distinct legal issue is searched per round. This permits
                # early stopping once Reason-in-Documents has enough evidence.
                issue_calls = [planned_issue_calls[round_number - 1]]
                calls = issue_calls
            # Katman 2'nin ana mevzuat araması model tercihine bırakılamaz. Model
            # yanlışlıkla yalnız biçim/eksiklik araçlarına yönelse bile her turda
            # belgenin maddi özetiyle gerçek mevzuat retriever'ı çalıştırılır.
            if not any(
                isinstance(item, Mapping)
                and item.get("tool") == "search_reliable_legislation"
                for item in calls
            ):
                gaps = output.get("knowledge_gaps", []) if isinstance(output, Mapping) else []
                gap = next(
                    (str(item).strip() for item in gaps if str(item).strip()),
                    "",
                )
                legal_query = self._content_search_query(analysis, text, gap)
                calls.insert(
                    0,
                    {
                        "tool": "search_reliable_legislation",
                        "query": legal_query,
                        "reference_ids": [],
                        "line_ids": [],
                    },
                )
            bounded_calls: list[Mapping[str, Any]] = []
            for item in calls:
                if not isinstance(item, Mapping):
                    continue
                if item.get("tool") == "search_reliable_legislation":
                    query_key = normalize_for_search(str(item.get("query") or "").strip())
                    if (
                        not query_key
                        or query_key in executed_legal_queries
                        or legal_query_count >= 4
                    ):
                        continue
                    executed_legal_queries.add(query_key)
                    legal_query_count += 1
                bounded_calls.append(item)
                if len(bounded_calls) >= 6:
                    break
            calls = bounded_calls
            round_results: list[dict[str, Any]] = []
            finish = False
            for raw in calls:
                if not isinstance(raw, Mapping):
                    continue
                result, trace = self._execute_tool(
                    round_number=round_number,
                    raw=raw,
                    candidates=reliable,
                    lines=lines,
                    analysis=analysis,
                )
                tool_trace.append(trace)
                if trace.executed_tool == "search_reliable_legislation":
                    emit(
                        "Mevzuat Arama Aracı",
                        f"{trace.query[:140]} · {len(trace.returned_reference_ids)} aday kaynak bulundu.",
                    )
                round_results.append(result)
                for reference_id in result.get("reference_ids", []):
                    if (
                        reference_id in reliable
                        and reliable[reference_id].rule_kind == "general_article"
                        and reference_id not in selected_ids
                    ):
                        selected_ids.append(reference_id)
                finish = finish or raw.get("tool") == "finish_research"
            prior_results.extend(round_results)
            candidate_pool = {
                reference_id: reliable[reference_id]
                for reference_id in selected_ids
                if reference_id in reliable
            }
            current_selected, equivalent_groups = self._deduplicate_candidates(
                candidate_pool
            )
            pending_refinement = {
                reference_id: candidate
                for reference_id, candidate in current_selected.items()
                if reference_id not in refined
            }
            if pending_refinement:
                emit(
                    "Reason-in-Documents",
                    f"Tur {round_number}: {len(pending_refinement)} yeni kaynak evrakla karşılaştırılıyor.",
                )
                refined_round, refine_call = self._refine_documents(
                    analysis,
                    text,
                    lines,
                    pending_refinement,
                    data_classification,
                )
                agent_trace.append(
                    self._agent_trace(
                        "reason_in_documents", refine_call, model, round_number
                    )
                )
                refined.update(refined_round)
                emit(
                    "Reason-in-Documents",
                    f"Tur {round_number}: toplam {len(refined)} farklı kaynak belgeyle eşleşti.",
                )
            if len(refined) >= 4 and round_number >= 3:
                emit(
                    "Katman 2 Araştırmacı",
                    "Dört farklı kaynak eşleşti; kalan arama turları çalıştırılmadan duruldu.",
                )
                break
            if finish or not calls:
                break

        candidate_pool = {
            reference_id: reliable[reference_id]
            for reference_id in selected_ids
            if reference_id in reliable
        }
        selected, equivalent_groups = self._deduplicate_candidates(candidate_pool)
        if not selected:
            return Layer2Assessment(
                status="abstained",
                summary="Araştırmacı güvenilir bir kaynak adayı seçemedi.",
                rejected_reference_ids=rejected,
                validation_warnings=plan_warnings,
                tool_trace=tool_trace,
                agent_trace=agent_trace,
                **base,
            )

        if not refined:
            return Layer2Assessment(
                status="abstained",
                summary="Reason-in-Documents aşaması doğrulanabilir kaynak alıntısı üretemedi.",
                rejected_reference_ids=sorted(set(rejected) | set(selected)),
                validation_warnings=[
                    *plan_warnings,
                    "Kaynak dışı bilgi nihai aşamaya geçirilmedi.",
                ],
                tool_trace=tool_trace,
                agent_trace=agent_trace,
                **base,
            )

        emit("Katman 2 Auditor", "Kaynakların uygulanabilirliği denetleniyor.")
        audits, audit_warnings, audit_call = self._audit(
            analysis, text, lines, selected, refined, data_classification
        )
        agent_trace.append(self._agent_trace("auditor", audit_call, model))
        emit(
            "Katman 2 Auditor",
            f"{len(audits)} kaynak-evrak ilişkisi kabul edildi.",
        )
        if not audits:
            return Layer2Assessment(
                status="abstained",
                summary="Auditor uygulanabilir ve kaynakla doğrulanmış hüküm kabul etmedi.",
                rejected_reference_ids=sorted(set(rejected) | set(selected)),
                validation_warnings=audit_warnings,
                tool_trace=tool_trace,
                agent_trace=agent_trace,
                **base,
            )

        emit("Katman 2 Adjudicator", "Doğrulanan dayanaklar nihai bulgulara dönüştürülüyor.")
        assessment, adjudication_call = self._adjudicate(
            analysis,
            lines,
            selected,
            audits,
            equivalent_groups,
            data_classification,
            base,
        )
        agent_trace.append(self._agent_trace("adjudicator", adjudication_call, model))
        emit(
            "Katman 2 Adjudicator",
            f"Katman 2 tamamlandı; {len(assessment.findings)} kaynaklı bulgu üretildi.",
        )
        assessment.tool_trace = tool_trace
        assessment.agent_trace = agent_trace
        assessment.rejected_reference_ids = sorted(
            set(rejected) | (set(selected) - set(assessment.accepted_reference_ids))
        )
        assessment.validation_warnings = [
            *plan_warnings,
            *audit_warnings,
            *assessment.validation_warnings,
        ]
        return assessment

    def _build_candidates(
        self,
        rules: Sequence[RequirementRule],
        references: Sequence[VerifiedReference],
    ) -> dict[str, _Candidate]:
        refs = {reference.chunk_id: reference for reference in references if reference.verified}
        result: dict[str, _Candidate] = {}
        for rule in rules:
            reference_id = f"REQ-{rule.rule_id}"
            reference = refs.get(reference_id)
            if reference is None:
                generated = self.requirement_rules.verified_references([rule])
                reference = generated[0] if generated else None
            if reference is None:
                continue
            result[reference_id] = _Candidate(
                reference=reference,
                field=rule.field,
                requirement=rule.requirement,
                rule_kind=rule.rule_kind,
                applicability=rule.applicability,
                absence_is_missing=rule.absence_is_missing,
                severity=rule.severity,
            )
        for reference in references:
            if reference.chunk_id in result or not reference.verified:
                continue
            result[reference.chunk_id] = _Candidate(
                reference=reference,
                field="icerik_degerlendirmesi",
                requirement=f"{reference.title} {reference.article or ''}".strip(),
                rule_kind="general_article",
                applicability="requires_audit",
                absence_is_missing=False,
                severity="warning",
            )
        return result

    @staticmethod
    def _source_usable(reference: VerifiedReference) -> bool:
        return bool(
            reference.verified
            and reference.excerpt.strip()
        )

    def _execute_tool(
        self,
        *,
        round_number: int,
        raw: Mapping[str, Any],
        candidates: dict[str, _Candidate],
        lines: Mapping[str, Any],
        analysis: DocumentAnalysis,
    ) -> tuple[dict[str, Any], Layer2ToolTrace]:
        requested = str(raw.get("tool") or "")
        tool = requested if requested in _TOOL_NAMES else "finish_research"
        query = str(raw.get("query") or "")[:300]
        legal_issue = str(raw.get("legal_issue") or "").strip()[:180] or None
        issue_scope = str(raw.get("issue_scope") or "").strip()[:40] or None
        reference_ids: list[str] = []
        line_ids: list[str] = []
        note = ""
        if tool == "search_curated_rules":
            reference_ids = [
                key for key, item in candidates.items() if item.rule_kind != "general_article"
            ][:16]
            note = "Evrak kapsamıyla deterministik eşleşen incelenmiş kurallar döndürüldü."
        elif tool == "search_reliable_legislation":
            if self.legal_search is not None and query.strip():
                for search_query in self._legal_query_variants(query):
                    for reference in self.legal_search(search_query, analysis):
                        if reference.chunk_id in candidates or not self._source_usable(reference):
                            continue
                        candidates[reference.chunk_id] = _Candidate(
                            reference=reference,
                            field="icerik_degerlendirmesi",
                            requirement=f"{reference.title} {reference.article or ''}".strip(),
                            rule_kind="general_article",
                            applicability="requires_audit",
                            absence_is_missing=False,
                            severity="warning",
                            research_issue=legal_issue,
                            research_scope=issue_scope,
                        )
            query_terms = {
                token
                for variant in self._legal_query_variants(query)
                for token in tokenize(normalize_for_search(variant))
            }
            ranked = sorted(
                (
                    pair
                    for pair in candidates.items()
                    if pair[1].rule_kind == "general_article"
                ),
                key=lambda pair: -len(
                    query_terms
                    & set(
                        tokenize(
                            normalize_for_search(
                                f"{pair[1].reference.title} {pair[1].reference.article or ''} "
                                f"{pair[1].reference.excerpt}"
                            )
                        )
                    )
                ),
            )
            # Four independent issue searches x four candidates keeps the
            # downstream evidence envelope within the 16-source refinement cap.
            reference_ids = [key for key, _ in ranked[:6]]
            for reference_id in reference_ids:
                candidate = candidates[reference_id]
                if legal_issue and candidate.research_issue is None:
                    candidates[reference_id] = replace(
                        candidate,
                        research_issue=legal_issue,
                        research_scope=issue_scope,
                    )
            note = (
                "Ana mevzuat vektörü arandı; yalnız güncel ve hukuki kullanıma "
                "açık kaynaklar önceliklendirildi; snapshot kaynakları yalnız bağlam "
                "etiketiyle döndürüldü."
            )
        elif tool in {"get_document_lines", "get_document_layout"}:
            requested_ids = [str(item) for item in raw.get("line_ids", [])]
            line_ids = [line_id for line_id in requested_ids if line_id in lines][:30]
            if not line_ids:
                query_terms = set(tokenize(normalize_for_search(query)))
                ranked_lines = sorted(
                    lines.values(),
                    key=lambda line: -len(
                        query_terms & set(tokenize(normalize_for_search(line.text)))
                    ),
                )
                line_ids = [line.line_id for line in ranked_lines[:20]]
            note = (
                "Koordinatlar istek üzerine döndürüldü."
                if tool == "get_document_layout"
                else "Yalnız satır metni ve kimliği döndürüldü."
            )
        else:
            note = "Araştırma döngüsü sonlandırıldı."
        result: dict[str, Any] = {
            "tool": tool,
            "reference_ids": reference_ids,
            "line_ids": line_ids,
            "references": [self._candidate_payload(candidates[key]) for key in reference_ids],
            "lines": [self._line_payload(lines[key], include_bbox=tool == "get_document_layout") for key in line_ids],
            "document_type": analysis.document_type,
        }
        return result, Layer2ToolTrace(
            round=round_number,
            requested_tool=requested,
            executed_tool=tool,
            legal_issue=legal_issue,
            issue_scope=issue_scope,
            query=query,
            returned_reference_ids=reference_ids,
            returned_line_ids=line_ids,
            note=note,
        )

    @staticmethod
    def _legal_query_variants(query: str) -> list[str]:
        """Bridge document language to corpus terminology without naming laws.

        This expands operational synonyms only; it never injects an article,
        obligation, result, or legal conclusion.
        """

        variants = [query]
        normalized = normalize_for_search(query)
        additions: list[str] = []
        if "kiralik" in normalized or "kiralık" in normalized:
            additions.append("sözleşmeli taşıt")
        if "ozmal" in normalized or "özmal" in normalized:
            additions.append("özmal sözleşmeli taşıt kullanım oranı")
        if "tasit kart" in normalized or "taşıt kart" in normalized:
            additions.append(
                "yetki belgesi eki taşıt belgesine kayıt taşıt kartı düzenlenir"
            )
        if additions:
            expanded = " ".join([query, *additions])[:300]
            if normalize_for_search(expanded) != normalized:
                variants.append(expanded)
        return variants

    def _refine_documents(
        self,
        analysis: DocumentAnalysis,
        text: str,
        lines: Mapping[str, Any],
        candidates: Mapping[str, _Candidate],
        classification: DataClassification,
    ) -> tuple[dict[str, dict[str, Any]], LLMCallResult]:
        call = self._invoke(
            task=LLMTask.EVIDENCE_AUDIT,
            role=LegalAgentRole.RESEARCHER,
            schema=_refinement_schema(),
            classification=classification,
            input_data={
                "document": self._document_payload(analysis, text),
                "document_lines": [self._line_payload(line) for line in lines.values()],
                "candidate_sources": [self._candidate_payload(item) for item in candidates.values()],
            },
            instructions=(
                "Search-o1 Reason-in-Documents modülüsün. Her aday için ayrı bir kayıt "
                "üret; adayı sessizce atlama. Her aday için yalnız verilen "
                "kaynak metninden birebir focused_quote seç ve belgedeki somut iddia, talep "
                "veya olaya bağla. Yalnız adres/imza/tarih/gönderen/ek var-yok gibi biçimsel "
                "eksiklik kontrolüne yarayan adayları keep=false yap. Evrakla maddi kapsam "
                "bağı yoksa keep=false yap. Ön bilgiden mevzuat, koşul veya sonuç ekleme."
            ),
        )
        refined: dict[str, dict[str, Any]] = {}
        output = call.output if call.succeeded and call.output else {}
        for item in output.get("refined_documents", []) if isinstance(output, Mapping) else []:
            if not isinstance(item, Mapping) or not item.get("keep"):
                continue
            reference_id = str(item.get("reference_id") or "")
            candidate = candidates.get(reference_id)
            quote = str(item.get("focused_quote") or "").strip()
            evidence_ids = [
                str(value)
                for value in item.get("document_evidence_ids", [])
                if str(value) in lines
            ]
            if (
                candidate is None
                or candidate.rule_kind != "general_article"
                or not quote
                or normalize_for_search(quote)
                not in normalize_for_search(candidate.reference.excerpt)
            ):
                continue
            refined[reference_id] = {
                "reference_id": reference_id,
                "focused_quote": quote,
                "scope_note": str(item.get("scope_note") or "")[:400],
                "document_evidence_ids": evidence_ids,
            }
        target_count = min(6, len(candidates))
        if len(refined) < target_count:
            # A structured LLM may correctly identify a source yet alter one
            # punctuation mark or omit an otherwise retrieved issue candidate.
            # Never relax the exact-quote gate; construct only the evidence
            # envelope from trusted inputs and leave applicability to Auditor.
            covered_issues = {
                candidates[key].research_issue
                for key in refined
                if key in candidates and candidates[key].research_issue
            }
            ordered_candidates = sorted(
                candidates.items(),
                key=lambda pair: (
                    pair[1].research_issue in covered_issues
                    if pair[1].research_issue
                    else True,
                    pair[1].research_issue is None,
                    -pair[1].reference.score,
                ),
            )
            for reference_id, candidate in ordered_candidates:
                if len(refined) >= target_count:
                    break
                if reference_id in refined:
                    continue
                if candidate.rule_kind != "general_article":
                    continue
                source_terms = {
                    token
                    for token in tokenize(
                        normalize_for_search(
                            f"{candidate.reference.title} {candidate.reference.excerpt}"
                        )
                    )
                    if len(token) >= 4
                }
                ranked_lines = sorted(
                    lines.values(),
                    key=lambda line: -len(
                        source_terms
                        & {
                            token
                            for token in tokenize(normalize_for_search(line.text))
                            if len(token) >= 4
                        }
                    ),
                )
                evidence_ids = [
                    line.line_id
                    for line in ranked_lines[:4]
                    if line.text.strip()
                ]
                excerpt = candidate.reference.excerpt.strip()
                if not excerpt or not evidence_ids:
                    continue
                refined[reference_id] = {
                    "reference_id": reference_id,
                    "focused_quote": excerpt[:500],
                    "scope_note": (
                        "Sunucu tarafından kaynak metninden birebir alınan ve Auditor "
                        "uygulanabilirlik denetimine gönderilen aday."
                    ),
                    "document_evidence_ids": evidence_ids,
                }
                if candidate.research_issue:
                    covered_issues.add(candidate.research_issue)
        return refined, call

    def _audit(
        self,
        analysis: DocumentAnalysis,
        text: str,
        lines: Mapping[str, Any],
        candidates: Mapping[str, _Candidate],
        refined: Mapping[str, Mapping[str, Any]],
        classification: DataClassification,
    ) -> tuple[dict[str, dict[str, Any]], list[str], LLMCallResult]:
        call = self._invoke(
            task=LLMTask.EVIDENCE_AUDIT,
            role=LegalAgentRole.AUDITOR,
            schema=_audit_schema(),
            classification=classification,
            input_data={
                "document": self._document_payload(analysis, text),
                "document_lines": [self._line_payload(line) for line in lines.values()],
                "refined_sources": list(refined.values()),
                "source_contracts": [
                    self._candidate_payload(candidates[key]) for key in refined
                ],
            },
            instructions=(
                "Görevin nihai hukuki karar vermek değil, kaynak ile evrak içeriği arasındaki "
                "açıklanabilir bağın türünü belirlemektir. Kaynak ve evrak aynı işlem, hak, "
                "yükümlülük veya usulü açıkça konu ediyorsa applicable seç ve supports, limits, "
                "defines_procedure, creates_obligation veya prohibits ilişkilerinden en uygununu "
                "kullan. Unclear yalnız görünür metinlerden hiçbir açıklanabilir bağ kurulamıyorsa "
                "seçilsin; nihai uyuşmazlığın ispatlanamaması tek başına unclear nedeni değildir. "
                "Biçimsel alan veya "
                "eksiklik denetimi yapma. document_statement belge satırlarının sadık özeti; "
                "legal_analysis ise yalnız exact quote ile belge arasındaki ilişki olsun. "
                "Her refined_source için mutlaka bir audit kaydı üret; sessizce kaynak atlama. "
                "Aynı evraktaki farklı genel, sektörel ve teknik meseleleri ayrı değerlendir. "
                "Kanıt yoksa insufficient_evidence/unclear seç; önbilgi kullanma."
            ),
        )
        accepted: dict[str, dict[str, Any]] = {}
        warnings: list[str] = []
        output = call.output if call.succeeded and call.output else {}
        for item in output.get("audits", []) if isinstance(output, Mapping) else []:
            if not isinstance(item, Mapping):
                continue
            reference_id = str(item.get("reference_id") or "")
            candidate = candidates.get(reference_id)
            if reference_id not in refined or candidate is None:
                warnings.append(f"{reference_id or 'adsız'}: Researcher aday kümesi dışında.")
                continue
            quote = str(item.get("legal_quote") or "").strip()
            if not quote or normalize_for_search(quote) not in normalize_for_search(candidate.reference.excerpt):
                warnings.append(f"{reference_id}: birebir kaynak alıntısı doğrulanamadı.")
                continue
            app_ids = [str(value) for value in item.get("applicability_evidence_ids", [])]
            if not set(app_ids) <= set(lines):
                warnings.append(f"{reference_id}: bilinmeyen belge line_id değeri içeriyor.")
                continue
            applicability = str(item.get("applicability") or "")
            relationship = str(item.get("legal_relationship") or "")
            if applicability == "not_applicable":
                continue
            if applicability in {"applicable", "conditional", "contextual_only"} and not app_ids:
                warnings.append(f"{reference_id}: uygulanabilirlik belge kanıtına bağlı değil.")
                continue
            normalized_item = dict(item)
            if applicability == "contextual_only":
                applicability = "applicable"
                normalized_item["applicability"] = applicability
            if applicability == "insufficient_evidence":
                continue
            accepted[reference_id] = {
                **normalized_item,
                "applicability_evidence_ids": app_ids,
            }
        if not accepted:
            # Bu katman kaynak keşfini görünür kılar; Auditor hukuki ilişkiyi
            # kesinleştiremedi diye gerçekten dönen kaynakları yok etmez. Burada
            # yeni hukuk yorumu üretilmez, yalnız exact source + document lines
            # retrieval bağı "uncertain/unclear" olarak aktarılır.
            for reference_id, refined_item in list(refined.items())[:16]:
                candidate = candidates.get(reference_id)
                if candidate is None or candidate.rule_kind != "general_article":
                    continue
                quote = str(refined_item.get("focused_quote") or "").strip()
                if not quote or normalize_for_search(quote) not in normalize_for_search(
                    candidate.reference.excerpt
                ):
                    continue
                evidence_ids = [
                    str(value)
                    for value in refined_item.get("document_evidence_ids", [])
                    if str(value) in lines
                ]
                if not evidence_ids:
                    continue
                document_statement = " ".join(
                    lines[line_id].text.strip() for line_id in evidence_ids
                )[:500]
                accepted[reference_id] = {
                    "reference_id": reference_id,
                    "applicability": "uncertain",
                    "legal_relationship": "unclear",
                    "legal_quote": quote,
                    "applicability_evidence_ids": evidence_ids,
                    "issue": (
                        f"{candidate.reference.title} "
                        f"{candidate.reference.article or ''} ile içerik ilişkisi"
                    )[:300],
                    "document_statement": document_statement,
                    "legal_analysis": (
                        "Bu kaynak parçası evrak içeriği için vektör aramasında bulundu; "
                        "Auditor hukuki ilişkiyi kesinleştiremedi."
                    ),
                    "practical_effect": (
                        "Kaynak metni doğrudan inceleme bağlamı olarak gösterilmiştir."
                    ),
                    "risk_level": "uncertain",
                    "confidence": min(max(float(candidate.reference.score), 0.0), 1.0),
                }
        return accepted, warnings, call

    def _adjudicate(
        self,
        analysis: DocumentAnalysis,
        lines: Mapping[str, Any],
        candidates: Mapping[str, _Candidate],
        audits: Mapping[str, Mapping[str, Any]],
        equivalent_groups: Mapping[str, Sequence[str]],
        classification: DataClassification,
        base: Mapping[str, Any],
    ) -> tuple[Layer2Assessment, LLMCallResult]:
        call = self._invoke(
            task=LLMTask.ADJUDICATION,
            role=LegalAgentRole.ADJUDICATOR,
            schema=_adjudication_schema(),
            classification=classification,
            input_data={
                "verified_audits": list(audits.values()),
                "source_contracts": [self._candidate_payload(candidates[key]) for key in audits],
            },
            instructions=(
                "Yalnız Auditor tarafından doğrulanan içerik-mevzuat bağlarını sentezle. "
                "Uygulanabilirlik ve hukuki ilişki değerlerini değiştirme; eksik/mevcut alan "
                "kontrolü, yeni hukuk kuralı veya kaynak ekleme. Her sonuç belgedeki iddia/talep, "
                "uygulanan hüküm, hukuki anlam ve pratik etkiyi açıkça ayırsın."
            ),
        )
        warnings: list[str] = []
        findings: list[Layer2Finding] = []
        output = call.output if call.succeeded and call.output else {}
        for item in output.get("findings", []) if isinstance(output, Mapping) else []:
            if not isinstance(item, Mapping):
                continue
            reference_id = str(item.get("reference_id") or "")
            audit = audits.get(reference_id)
            candidate = candidates.get(reference_id)
            if audit is None or candidate is None:
                warnings.append(f"{reference_id or 'adsız'}: Auditor kümesi dışında.")
                continue
            applicability = str(item.get("applicability") or "")
            relationship = str(item.get("legal_relationship") or "")
            if applicability != str(audit.get("applicability")):
                warnings.append(f"{reference_id}: Adjudicator uygulanabilirlik kararını değiştirdi.")
                continue
            if relationship != str(audit.get("legal_relationship")):
                warnings.append(f"{reference_id}: Adjudicator hukuki ilişkiyi değiştirdi.")
                continue
            evidence_ids = [str(value) for value in item.get("document_evidence_ids", [])]
            allowed_lines = set(audit.get("applicability_evidence_ids", []))
            if not set(evidence_ids) <= allowed_lines or not set(evidence_ids) <= set(lines):
                warnings.append(f"{reference_id}: doğrulanmamış belge kanıtı kullandı.")
                continue
            issue_text = str(item.get("issue") or audit.get("issue") or "")
            assessment_text = str(
                item.get("legal_assessment") or audit.get("legal_analysis") or ""
            )
            contradiction_text = f"{issue_text} {assessment_text}".casefold()
            if any(
                marker in contradiction_text
                for marker in (
                    "maddi bağı yok",
                    "doğrudan bağı yok",
                    "ilişkili değildir",
                    "ilişkisi bulunmamaktadır",
                )
            ):
                continue
            findings.append(
                Layer2Finding(
                    issue=(issue_text or "Hukuki mesele")[:300],
                    document_statement=str(item.get("document_statement") or audit.get("document_statement") or "")[:500],
                    applicability=applicability,  # type: ignore[arg-type]
                    legal_relationship=relationship,  # type: ignore[arg-type]
                    legal_assessment=assessment_text[:700],
                    practical_effect=str(item.get("practical_effect") or audit.get("practical_effect") or "")[:500],
                    risk_level=str(item.get("risk_level") or audit.get("risk_level") or "uncertain"),  # type: ignore[arg-type]
                    legal_reference_id=reference_id,
                    equivalent_reference_ids=list(
                        equivalent_groups.get(reference_id, [reference_id])
                    ),
                    legal_title=candidate.reference.title,
                    legal_article=candidate.reference.article,
                    legal_quote=str(audit.get("legal_quote") or ""),
                    document_evidence_ids=evidence_ids,
                    confidence=float(item.get("confidence") or 0.0),
                )
            )
        if not findings:
            # Katman 2 bir karar kapısı değil, kaynak-bağlam görünümüdür. Adjudicator
            # sentez üretmese bile Auditor'ın exact-quote ve line-id kapılarından
            # geçmiş ilişkilerini doğrudan, ek yorum katmadan görünür tut.
            for reference_id, audit in audits.items():
                candidate = candidates[reference_id]
                applicability = str(audit.get("applicability") or "applicable")
                if applicability not in {
                    "applicable", "conditional", "contextual_only", "uncertain"
                }:
                    applicability = "uncertain"
                relationship = str(audit.get("legal_relationship") or "unclear")
                if relationship not in {
                    "supports", "limits", "defines_procedure", "creates_obligation",
                    "prohibits", "unclear",
                }:
                    relationship = "unclear"
                findings.append(
                    Layer2Finding(
                        issue=str(audit.get("issue") or "Kaynakla ilişkili hukuki mesele")[:300],
                        document_statement=str(audit.get("document_statement") or "")[:500],
                        applicability=applicability,  # type: ignore[arg-type]
                        legal_relationship=relationship,  # type: ignore[arg-type]
                        legal_assessment=str(audit.get("legal_analysis") or "")[:700],
                        practical_effect=str(audit.get("practical_effect") or "")[:500],
                        risk_level=str(audit.get("risk_level") or "uncertain"),  # type: ignore[arg-type]
                        legal_reference_id=reference_id,
                        equivalent_reference_ids=list(
                            equivalent_groups.get(reference_id, [reference_id])
                        ),
                        legal_title=candidate.reference.title,
                        legal_article=candidate.reference.article,
                        legal_quote=str(audit.get("legal_quote") or ""),
                        document_evidence_ids=list(
                            audit.get("applicability_evidence_ids", [])
                        ),
                        confidence=float(audit.get("confidence") or 0.0),
                    )
                )
        findings = self._limit_findings(findings)
        status: Literal["completed", "abstained"] = "completed" if findings else "abstained"
        summary = str(output.get("summary") or "")[:700] if isinstance(output, Mapping) else ""
        if findings and not summary:
            summary = "Evrak içeriği bulunan mevzuat parçalarıyla ilişkilendirildi."
        elif not findings:
            summary = "Adjudicator kaynak kapılarından geçen bir içerik değerlendirmesi üretmedi."
        assessment = Layer2Assessment(
            status=status,
            summary=summary,
            findings=findings,
            important_results=[str(value)[:500] for value in output.get("important_results", [])]
            if isinstance(output, Mapping)
            else [],
            accepted_reference_ids=sorted(
                {
                    reference_id
                    for item in findings
                    for reference_id in (
                        item.equivalent_reference_ids or [item.legal_reference_id]
                    )
                }
            ),
            validation_warnings=warnings,
            requires_human_review=(
                bool(output.get("requires_human_review", True))
                if isinstance(output, Mapping)
                else True
            ),
            **base,
        )
        return assessment, call

    def _invoke(
        self,
        *,
        task: LLMTask,
        role: LegalAgentRole,
        schema: Mapping[str, Any],
        classification: DataClassification,
        input_data: Mapping[str, Any],
        instructions: str,
    ) -> LLMCallResult:
        return self.gateway.invoke(
            StructuredLLMRequest(
                task=task,
                role=role,
                input_data=input_data,
                output_schema=schema,
                data_classification=classification,
                allow_automatic_redaction=classification is DataClassification.REDACTED,
                fallback_action=FallbackAction.ABSTAIN,
                trusted_instructions=(
                    "KAYNAK-ZORUNLU POLİTİKA: Model önbilgisi, ezberlenmiş mevzuat veya "
                    "kaynak adaylarında bulunmayan hiçbir bilgi kullanılamaz. Kaynak yoksa "
                    "sonuç üretme. " + instructions
                ),
            )
        )

    @staticmethod
    def _agent_trace(
        role: Literal["researcher", "reason_in_documents", "auditor", "adjudicator"],
        call: LLMCallResult,
        model: str,
        round_number: int | None = None,
    ) -> Layer2AgentTrace:
        failure = call.failure
        suffix = f" (arama turu {round_number})" if round_number else ""
        return Layer2AgentTrace(
            role=role,
            status=call.status.value,
            model=model,
            network_attempted=call.network_attempted,
            failure_code=failure.code if failure else None,
            note=((failure.message if failure else "Kapalı JSON şeması doğrulandı.") + suffix),
        )

    @staticmethod
    def _document_payload(analysis: DocumentAnalysis, text: str) -> dict[str, Any]:
        bounded = text if len(text) <= 24_000 else f"{text[:16000]}\n...\n{text[-8000:]}"
        return {
            "document_type": analysis.document_type,
            "operational_category": analysis.operational_category,
            "document_subtype": analysis.document_subtype,
            "summary": analysis.summary,
            "text": bounded,
        }

    @staticmethod
    def _content_search_query(
        analysis: DocumentAnalysis, text: str, knowledge_gap: str = ""
    ) -> str:
        """Build a content query without trusting the often header-only LLM summary."""

        source = analysis.retrieval_evidence_text or text
        compact = " ".join(source.split())
        marker = re.search(r"\bkonu\s*:", compact, flags=re.IGNORECASE)
        if marker is not None:
            compact = compact[marker.end() :]
        # Put the classified task and the document's own subject/body first.
        # The model-proposed gap is only a tail hint and cannot displace them.
        query = " ".join(
            value
            for value in (
                (analysis.operational_category or "").replace("_", " "),
                (analysis.document_subtype or "").replace("_", " "),
                compact[:700],
                knowledge_gap,
            )
            if value
        )
        return query[:300]

    @staticmethod
    def _issue_plan(
        raw_issues: Any,
    ) -> tuple[list[dict[str, str]], list[str]]:
        """Validate issue diversity without hard-coding laws or query text."""

        issues: list[dict[str, str]] = []
        errors: list[str] = []
        if not isinstance(raw_issues, list):
            return [], ["Hukuki mesele planı bir liste değil."]
        for raw in raw_issues[:4]:
            if not isinstance(raw, Mapping):
                continue
            issue = str(raw.get("issue") or "").strip()[:180]
            query = str(raw.get("query") or "").strip()[:300]
            basis = str(raw.get("document_basis") or "").strip()[:300]
            scope = str(raw.get("scope") or "").strip()
            if not issue or not query or not basis:
                errors.append("Her mesele ad, sorgu ve evrak dayanağı içermelidir.")
                continue
            if scope not in {"general_procedure", "sector_specific", "technical"}:
                errors.append(f"Geçersiz mesele türü: {scope or 'boş'}.")
                continue
            query_tokens = {
                token for token in tokenize(normalize_for_search(query)) if len(token) >= 3
            }
            basis_tokens = {
                token for token in tokenize(normalize_for_search(basis)) if len(token) >= 3
            }
            duplicate = False
            for existing in issues:
                existing_query = {
                    token
                    for token in tokenize(normalize_for_search(existing["query"]))
                    if len(token) >= 3
                }
                existing_basis = {
                    token
                    for token in tokenize(normalize_for_search(existing["document_basis"]))
                    if len(token) >= 3
                }
                query_union = query_tokens | existing_query
                basis_union = basis_tokens | existing_basis
                query_similarity = (
                    len(query_tokens & existing_query) / len(query_union)
                    if query_union
                    else 1.0
                )
                basis_similarity = (
                    len(basis_tokens & existing_basis) / len(basis_union)
                    if basis_union
                    else 1.0
                )
                if query_similarity >= 0.72 or basis_similarity >= 0.82:
                    duplicate = True
                    break
            if duplicate:
                errors.append(f"Tekrarlı hukuki mesele elendi: {issue}.")
                continue
            issues.append(
                {
                    "issue": issue,
                    "query": query,
                    "document_basis": basis,
                    "scope": scope,
                }
            )
        scopes = {item["scope"] for item in issues}
        if len(issues) < 3:
            errors.append("En az üç farklı hukuki mesele gerekir.")
        if "general_procedure" not in scopes:
            errors.append("Bir genel hak/usul meselesi eksik.")
        if not scopes & {"sector_specific", "technical"}:
            errors.append("En az bir özel veya teknik mesele eksik.")
        return issues, errors

    @staticmethod
    def _canonical_reference_keys(reference: VerifiedReference) -> tuple[str, ...]:
        """Build stable cross-corpus keys for the same legislation article."""

        title = normalize_for_search(reference.title)
        title = re.sub(r"\b(?:ocak|subat|mart|nisan|mayis|haziran|temmuz|agustos|eylul|ekim|kasim|aralik|revize|revision|20\d{2})\b", " ", title)
        title = " ".join(title.split())
        article = " ".join(normalize_for_search(reference.article or "").split())
        excerpt = " ".join(normalize_for_search(reference.excerpt).split())
        keys = [f"title-article:{title}|{article}"] if title and article else []
        if len(excerpt) >= 80:
            keys.append(f"excerpt:{excerpt[:360]}")
        if not keys:
            keys.append(f"reference:{reference.chunk_id}")
        return tuple(keys)

    @classmethod
    def _deduplicate_candidates(
        cls,
        candidates: Mapping[str, _Candidate],
    ) -> tuple[dict[str, _Candidate], dict[str, list[str]]]:
        owners_by_key: dict[str, str] = {}
        deduplicated: dict[str, _Candidate] = {}
        groups: dict[str, list[str]] = {}
        for reference_id, candidate in candidates.items():
            keys = cls._canonical_reference_keys(candidate.reference)
            owner = next((owners_by_key[key] for key in keys if key in owners_by_key), None)
            if owner is None:
                owner = reference_id
                deduplicated[owner] = candidate
                groups[owner] = [reference_id]
            elif reference_id not in groups[owner]:
                groups[owner].append(reference_id)
            for key in keys:
                owners_by_key[key] = owner
        return deduplicated, groups

    @staticmethod
    def _limit_findings(findings: Sequence[Layer2Finding]) -> list[Layer2Finding]:
        """Keep at most four strong, non-repetitive legal findings."""

        ranked = sorted(
            findings,
            key=lambda item: (
                item.applicability == "uncertain",
                item.legal_relationship == "unclear",
                -item.confidence,
            ),
        )
        selected: list[Layer2Finding] = []
        for finding in ranked:
            finding_tokens = {
                token
                for token in tokenize(normalize_for_search(finding.issue))
                if len(token) >= 3
            }
            repeated = False
            for existing in selected:
                existing_tokens = {
                    token
                    for token in tokenize(normalize_for_search(existing.issue))
                    if len(token) >= 3
                }
                union = finding_tokens | existing_tokens
                similarity = (
                    len(finding_tokens & existing_tokens) / len(union)
                    if union
                    else 1.0
                )
                if similarity >= 0.78:
                    repeated = True
                    break
            if repeated:
                continue
            selected.append(finding)
            if len(selected) == 4:
                break
        return selected

    @staticmethod
    def _candidate_payload(candidate: _Candidate) -> dict[str, Any]:
        reference = candidate.reference
        payload: dict[str, Any] = {
            "reference_id": reference.chunk_id,
            "title": reference.title,
            "article": reference.article,
            "source": reference.source,
            "source_url": reference.source_url,
            "quote_source_text": reference.excerpt,
            "rule_kind": candidate.rule_kind,
            "research_issue": candidate.research_issue,
            "research_scope": candidate.research_scope,
        }
        if candidate.rule_kind != "general_article":
            payload.update(
                {
                    "field": candidate.field,
                    "requirement": candidate.requirement,
                    "applicability": candidate.applicability,
                    "absence_is_missing": candidate.absence_is_missing,
                    "severity": candidate.severity,
                }
            )
        return payload

    @staticmethod
    def _line_payload(line: Any, *, include_bbox: bool = False) -> dict[str, Any]:
        result: dict[str, Any] = {
            "line_id": line.line_id,
            "page": line.page,
            "text": line.text,
            "confidence": line.confidence,
        }
        if include_bbox:
            result["bbox"] = line.bbox.model_dump(mode="json") if line.bbox else None
        return result


__all__ = [
    "Layer2Assessment",
    "Layer2Finding",
    "Layer2LegalReasoning",
]
