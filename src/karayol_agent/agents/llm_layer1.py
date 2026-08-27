"""KATMAN 1 — LLM1 (RAG destekli sınıflandırma) ve LLM2 (eksik veri tespiti).

Bu iki ajan, emekliye ayrılan ``LLMDocumentUnderstandingAgent``'ın yerini alır
ve tek sorumluluk ilkesiyle ikiye ayrılır:

* ``LLMClassificationAgent`` (LLM1) yalnız evrak türünü, yapılandırılabilir
  kapalı bir katalogdan (``DocumentTypeCatalog``) seçer.
* ``LLMRequiredDataAgent`` (LLM2) seçilen türe göre hangi verilerin eksik
  olduğunu, hem mevzuat vektör veritabanından gelen doğrulanmış "zorunludur"
  kanıtlarıyla hem de (varsa) OCR yerleşim/koordinat analizinden gelen boş
  alan adaylarıyla birlikte değerlendirir.

Her iki ajan da mevcut ``StructuredLLMGateway`` sözleşmesini kullanır ve
deterministik taban her zaman korunur; LLM yalnız ek/tamamlayıcı bilgi sağlar.
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
from karayol_agent.schemas import ClassificationResult, VerifiedReference
from karayol_agent.text_utils import normalize_for_search, tokenize, truncate

from .llm_roles import StructuredGateway, _head_and_tail


@dataclass(frozen=True, slots=True)
class DocumentTypeEntry:
    type_id: str
    display_name: str
    definition: str
    example_phrases: tuple[str, ...] = ()


class DocumentTypeCatalog:
    """Configurable, RAG-searchable evrak türü kataloğu.

    Kullanıcının ileride sağlayacağı gerçek tür listesi bu JSON dosyasının
    içeriğini değiştirerek eklenir; kod tarafında değişiklik gerekmez.
    """

    def __init__(self, entries: Sequence[DocumentTypeEntry]) -> None:
        if not entries:
            raise ValueError("Evrak türü kataloğu boş olamaz.")
        ids = [entry.type_id for entry in entries]
        if len(ids) != len(set(ids)):
            raise ValueError("Evrak türü kataloğunda yinelenen type_id var.")
        self.entries = tuple(entries)

    @classmethod
    def load(cls, path: Path) -> "DocumentTypeCatalog":
        payload = json.loads(path.read_text(encoding="utf-8"))
        raw_entries = payload.get("entries", []) if isinstance(payload, dict) else payload
        entries = [
            DocumentTypeEntry(
                type_id=str(item["type_id"]),
                display_name=str(item["display_name"]),
                definition=str(item["definition"]),
                example_phrases=tuple(
                    str(phrase) for phrase in item.get("example_phrases", [])
                ),
            )
            for item in raw_entries
        ]
        return cls(entries)

    @property
    def type_ids(self) -> tuple[str, ...]:
        return tuple(entry.type_id for entry in self.entries)

    def ranked_for(self, text: str) -> list[DocumentTypeEntry]:
        """Return every catalog entry, most lexically relevant first.

        The catalog is small by design (one entry per evrak türü), so this
        is informational ordering for the LLM prompt, not a filter — the
        model still chooses from the full closed ``type_ids`` set.
        """

        query_tokens = set(tokenize(text))
        scored: list[tuple[int, DocumentTypeEntry]] = []
        for entry in self.entries:
            haystack = " ".join(
                [entry.display_name, entry.definition, *entry.example_phrases]
            )
            overlap = len(query_tokens & set(tokenize(haystack)))
            scored.append((overlap, entry))
        scored.sort(key=lambda item: (-item[0], item[1].type_id))
        return [entry for _, entry in scored]


@dataclass(frozen=True, slots=True)
class ClassificationOutcome:
    call: LLMCallResult
    document_type: str | None = None
    confidence: float | None = None
    evidence_span: str | None = None


class LLMClassificationAgent:
    """LLM1: kapalı evrak türü kataloğundan RAG destekli seçim yapar."""

    name = "LLM Sınıflandırma Ajanı (LLM1)"

    def __init__(self, gateway: StructuredGateway, catalog: DocumentTypeCatalog) -> None:
        self.gateway = gateway
        self.catalog = catalog

    def run(
        self,
        *,
        text: str,
        deterministic_classification: ClassificationResult,
        data_classification: DataClassification,
    ) -> ClassificationOutcome:
        ranked = self.catalog.ranked_for(text)
        schema = {
            "type": "object",
            "properties": {
                "document_type": {
                    "type": "string",
                    "enum": list(self.catalog.type_ids),
                },
                "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                "evidence_span": {"type": ["string", "null"], "maxLength": 400},
            },
            "required": ["document_type", "confidence", "evidence_span"],
            "additionalProperties": False,
        }
        result = self.gateway.invoke(
            StructuredLLMRequest(
                task=LLMTask.CLASSIFICATION,
                role=LegalAgentRole.RESEARCHER,
                input_data={
                    "document_text": _head_and_tail(text),
                    "deterministic_operational_profile": (
                        deterministic_classification.document_type
                    ),
                    "deterministic_confidence": deterministic_classification.confidence,
                    "candidate_types": [
                        {
                            "type_id": entry.type_id,
                            "display_name": entry.display_name,
                            "definition": entry.definition,
                        }
                        for entry in ranked
                    ],
                },
                output_schema=schema,
                data_classification=data_classification,
                allow_automatic_redaction=False,
                trusted_instructions=(
                    "Kapalı evrak türü listesinden yalnız bir tanesini seç. "
                    "evidence_span, belgeden birebir alınmış kısa bir kanıt "
                    "parçası olmalı; açık kanıt yoksa null döndür. Tür seçimini "
                    "candidate_types içindeki tanımlarla gerekçelendir."
                ),
            )
        )
        if not result.succeeded or result.output is None:
            return ClassificationOutcome(call=result)
        payload = result.output
        return ClassificationOutcome(
            call=result,
            document_type=str(payload["document_type"]),
            confidence=float(payload["confidence"]),
            evidence_span=payload["evidence_span"],
        )


@dataclass(frozen=True, slots=True)
class LayoutGapCandidate:
    """Deterministik olarak tespit edilmiş, muhtemelen boş bırakılmış alan.

    OCR kelime/koordinat verisinden üretilir (bkz. ``agents.layout``);
    LLM2'ye ham koordinat yerine önceden süzülmüş, insan-okunur bir aday
    olarak verilir.
    """

    candidate_id: str
    nearby_label: str
    region_description: str


@dataclass(frozen=True, slots=True)
class RequiredDataOutcome:
    call: LLMCallResult
    missing_data_points: tuple[str, ...] = ()
    confidence: float | None = None


class LLMRequiredDataAgent:
    """LLM2: vektör-DB kanıtı + yerleşim-farkındalıklı eksik veri tespiti."""

    name = "LLM Eksik Veri Ajanı (LLM2)"

    def __init__(self, gateway: StructuredGateway) -> None:
        self.gateway = gateway

    def run(
        self,
        *,
        text: str,
        document_type: str,
        static_missing_fields: Sequence[str],
        requirement_references: Sequence[VerifiedReference],
        layout_gap_candidates: Sequence[LayoutGapCandidate] = (),
        data_classification: DataClassification,
    ) -> RequiredDataOutcome:
        verified_requirements = [
            reference for reference in requirement_references if reference.verified
        ]
        verified_ids = {reference.chunk_id for reference in verified_requirements}
        candidate_ids = {candidate.candidate_id for candidate in layout_gap_candidates}
        item_schema: dict[str, Any] = {
            "type": "object",
            "properties": {
                "description": {"type": "string", "maxLength": 200},
                "evidence_chunk_id": {
                    "type": ["string", "null"],
                    **({"enum": sorted(verified_ids) + [None]} if verified_ids else {}),
                },
                "layout_candidate_id": {
                    "type": ["string", "null"],
                    **(
                        {"enum": sorted(candidate_ids) + [None]}
                        if candidate_ids
                        else {}
                    ),
                },
            },
            "required": ["description", "evidence_chunk_id", "layout_candidate_id"],
            "additionalProperties": False,
        }
        schema = {
            "type": "object",
            "properties": {
                "missing_data_points": {
                    "type": "array",
                    "items": item_schema,
                    "maxItems": 10,
                },
                "confidence": {"type": "number", "minimum": 0, "maximum": 1},
            },
            "required": ["missing_data_points", "confidence"],
            "additionalProperties": False,
        }
        result = self.gateway.invoke(
            StructuredLLMRequest(
                task=LLMTask.EXTRACTION,
                role=LegalAgentRole.RESEARCHER,
                input_data={
                    "document_text": _head_and_tail(text),
                    "document_type": document_type,
                    "already_known_missing_fields": list(static_missing_fields),
                    "requirement_evidence": [
                        {
                            "chunk_id": reference.chunk_id,
                            "title": reference.title,
                            "article": reference.article,
                            "excerpt": truncate(reference.excerpt, 500),
                        }
                        for reference in verified_requirements
                    ],
                    "layout_gap_candidates": [
                        {
                            "candidate_id": candidate.candidate_id,
                            "nearby_label": candidate.nearby_label,
                            "region_description": candidate.region_description,
                        }
                        for candidate in layout_gap_candidates
                    ],
                },
                output_schema=schema,
                data_classification=data_classification,
                allow_automatic_redaction=False,
                trusted_instructions=(
                    "requirement_evidence yalnız doğrulanmış mevzuat kanıtıdır; "
                    "her eksik veri adayı için mümkünse evidence_chunk_id veya "
                    "layout_candidate_id ile gerekçelendir, ikisi de yoksa her "
                    "ikisini de null bırak. already_known_missing_fields "
                    "listesindeki alanları tekrar etme, yalnız YENİ ve kanıta "
                    "dayalı adaylar öner."
                ),
            )
        )
        if not result.succeeded or result.output is None:
            return RequiredDataOutcome(call=result)
        payload = result.output
        descriptions: list[str] = []
        for item in payload["missing_data_points"]:
            evidence_id = item["evidence_chunk_id"]
            layout_id = item["layout_candidate_id"]
            if evidence_id is not None and evidence_id not in verified_ids:
                continue
            if layout_id is not None and layout_id not in candidate_ids:
                continue
            description = str(item["description"]).strip()
            if description:
                descriptions.append(description)
        return RequiredDataOutcome(
            call=result,
            missing_data_points=tuple(dict.fromkeys(descriptions)),
            confidence=float(payload["confidence"]),
        )


__all__ = [
    "ClassificationOutcome",
    "DocumentTypeCatalog",
    "DocumentTypeEntry",
    "LayoutGapCandidate",
    "LLMClassificationAgent",
    "LLMRequiredDataAgent",
    "RequiredDataOutcome",
]
