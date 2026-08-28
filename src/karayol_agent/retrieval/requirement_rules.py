from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel, Field

from karayol_agent.schemas import DocumentAnalysis, VerifiedReference
from karayol_agent.text_utils import normalize_for_search


class RequirementSource(BaseModel):
    source_id: str
    title: str
    authority: str
    source_url: str
    document_number: str | None = None
    reviewed_on: str
    currentness_verified: bool = False
    legal_reliance_allowed: bool = False
    source_kind: str = "official_legislation"


class RequirementRule(BaseModel):
    rule_id: str
    source_id: str
    article: str | None = None
    field: str
    requirement: str
    legal_evidence: str = Field(min_length=3, max_length=500)
    general_document_types: list[str] = Field(default_factory=list)
    operational_categories: list[str] = Field(default_factory=list)
    subtype_terms: list[str] = Field(default_factory=list)
    excluded_terms: list[str] = Field(default_factory=list)
    rule_kind: str = "mandatory_field"
    applicability: str = "required"
    absence_is_missing: bool = True
    expected_position: str | None = None
    severity: str = "error"

    def matches(self, analysis: DocumentAnalysis) -> bool:
        classification_values = {
            value
            for value in (
                analysis.general_document_type,
                analysis.document_type,
                analysis.operational_category,
            )
            if value
        }
        if self.operational_categories and not classification_values.intersection(
            self.operational_categories
        ):
            return False
        evidence = normalize_for_search(
            " ".join(
                value
                for value in (
                    analysis.document_subtype,
                    analysis.operational_category,
                    analysis.document_type,
                    analysis.summary,
                    analysis.retrieval_evidence_text,
                )
                if value
            )
        ).replace("_", " ").replace("-", " ")
        subtype_matched = bool(self.subtype_terms) and any(
            normalize_for_search(term).replace("_", " ").replace("-", " ")
            in evidence
            for term in self.subtype_terms
        )
        if self.subtype_terms and not subtype_matched:
            return False
        # A specific subtype is stronger evidence than a broad/DETSIS display
        # label. LLM-1 may put values such as "BAŞVURU/TALEP FORMU" in the
        # broad type field while still producing the correct legal subtype.
        if (
            self.general_document_types
            and not classification_values.intersection(self.general_document_types)
            and not subtype_matched
        ):
            return False
        return not any(
            normalize_for_search(term).replace("_", " ").replace("-", " ")
            in evidence
            for term in self.excluded_terms
        )


class RequirementRuleCatalog(BaseModel):
    schema_version: str
    sources: list[RequirementSource]
    rules: list[RequirementRule]


class RequirementRuleRepository:
    """Small reviewed corpus used before broad legislation retrieval in LLM-2."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.catalog: RequirementRuleCatalog | None = None
        self.warning: str | None = None
        if not path.is_file():
            self.warning = f"Denetlenmiş gereksinim kataloğu bulunamadı: {path}"
            return
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            catalog = RequirementRuleCatalog.model_validate(raw)
            source_ids = [source.source_id for source in catalog.sources]
            rule_ids = [rule.rule_id for rule in catalog.rules]
            if len(source_ids) != len(set(source_ids)):
                raise ValueError("yinelenen source_id")
            if len(rule_ids) != len(set(rule_ids)):
                raise ValueError("yinelenen rule_id")
            unknown_sources = {
                rule.source_id for rule in catalog.rules
            } - set(source_ids)
            if unknown_sources:
                raise ValueError(
                    "kaynağı bulunmayan kurallar: " + ", ".join(sorted(unknown_sources))
                )
            self.catalog = catalog
        except (OSError, ValueError, TypeError) as exc:
            self.warning = f"Gereksinim kataloğu yüklenemedi: {exc}"

    def select(self, analysis: DocumentAnalysis) -> list[RequirementRule]:
        if self.catalog is None:
            return []
        return [rule for rule in self.catalog.rules if rule.matches(analysis)]

    def verified_references(
        self, rules: list[RequirementRule]
    ) -> list[VerifiedReference]:
        if self.catalog is None:
            return []
        sources = {source.source_id: source for source in self.catalog.sources}
        references: list[VerifiedReference] = []
        for rule in rules:
            source = sources[rule.source_id]
            references.append(
                VerifiedReference(
                    chunk_id=f"REQ-{rule.rule_id}",
                    document_id=source.source_id,
                    title=source.title,
                    article=rule.article,
                    source=source.authority,
                    source_url=source.source_url,
                    source_kind="curated_requirement_rule",
                    corpus_mode="curated_requirements",
                    currentness_verified=source.currentness_verified,
                    legal_reliance_allowed=source.legal_reliance_allowed,
                    usage_notice=(
                        "İnsan tarafından incelenmiş atomik eksiklik kuralı; "
                        "yalnız belirtilen evrak kapsamına uygulanır."
                    ),
                    domain="document_requirements",
                    excerpt=rule.legal_evidence,
                    score=1.0,
                    verified=True,
                    verification_note=(
                        f"{source.reviewed_on} tarihinde incelenmiş resmî kaynak "
                        f"ve kapalı kural kaydı ({rule.rule_id})."
                    ),
                    evidence_channels=["curated_requirement_catalog"],
                    relevance_score=1.0,
                    relevance_accepted=True,
                    relevance_reasons=["evrak türü ve alt tür kapsamı eşleşti"],
                    relevance_profile="curated_requirement_rule",
                    relevance_basis="structured_scope_match",
                )
            )
        return references

    @staticmethod
    def payload(rules: list[RequirementRule]) -> list[dict[str, object]]:
        return [
            {
                "rule_candidate_id": f"rule:{rule.rule_id}",
                "legal_reference_id": f"REQ-{rule.rule_id}",
                "field": rule.field,
                "requirement": rule.requirement,
                "rule_text": rule.legal_evidence,
                "rule_kind": rule.rule_kind,
                "applicability": rule.applicability,
                "absence_is_missing": rule.absence_is_missing,
                "expected_position": rule.expected_position,
                "severity": rule.severity,
            }
            for rule in rules
        ]


__all__ = [
    "RequirementRule",
    "RequirementRuleCatalog",
    "RequirementRuleRepository",
    "RequirementSource",
]
