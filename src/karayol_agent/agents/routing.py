from __future__ import annotations

import json
from pathlib import Path

from karayol_agent.schemas import DocumentAnalysis, RoutingRecommendation, UnitRecord
from karayol_agent.text_utils import normalize_for_search, tokenize


class RoutingAgent:
    name = "Birim Yönlendirme Ajanı"

    def __init__(self, units_path: Path) -> None:
        payload = json.loads(units_path.read_text(encoding="utf-8"))
        records = payload["data"] if isinstance(payload, dict) else payload
        self.units = [UnitRecord.model_validate(record) for record in records]
        self.organization_version = (
            str(payload.get("organization_version", "legacy-synthetic"))
            if isinstance(payload, dict)
            else "legacy-synthetic"
        )
        self._validate_catalog()

    def _validate_catalog(self) -> None:
        ids = [unit.unit_id for unit in self.units]
        if len(ids) != len(set(ids)):
            raise ValueError("Organizasyon kataloğunda yinelenen unit_id var.")
        known_ids = set(ids)
        for unit in self.units:
            if unit.parent_id and unit.parent_id not in known_ids:
                raise ValueError(
                    f"{unit.unit_id} için tanımsız parent_id: {unit.parent_id}"
                )
            visited: set[str] = set()
            current = unit
            while current.parent_id:
                if current.unit_id in visited:
                    raise ValueError("Organizasyon kataloğunda hiyerarşi döngüsü var.")
                visited.add(current.unit_id)
                current = next(item for item in self.units if item.unit_id == current.parent_id)

    def run(self, analysis: DocumentAnalysis) -> RoutingRecommendation:
        field_values = [
            str(field.value)
            for field in analysis.fields.values()
            if field.value is not None
        ]
        query = normalize_for_search(
            " ".join(
                [
                    analysis.document_type,
                    analysis.summary,
                    analysis.retrieval_evidence_text or "",
                    *analysis.keywords,
                    *field_values,
                ]
            )
        )
        query_tokens = set(tokenize(query))
        ranked: list[tuple[float, UnitRecord, list[str]]] = []
        for unit in self.units:
            if not unit.accepts_external_documents:
                continue
            keyword_matches = [
                keyword for keyword in unit.keywords if normalize_for_search(keyword) in query
            ]
            responsibility_tokens = set(tokenize(" ".join(unit.responsibilities)))
            token_overlap = query_tokens & responsibility_tokens
            jurisdiction_matches = [
                place
                for place in unit.jurisdictions
                if normalize_for_search(place) in query
            ]
            raw_score = (
                len(keyword_matches) * 4
                + len(token_overlap)
                + len(jurisdiction_matches) * 6
            )
            evidence = list(
                dict.fromkeys(
                    [f"anahtar:{item}" for item in keyword_matches]
                    + [f"sorumluluk:{item}" for item in sorted(token_overlap)]
                    + [f"yer:{item}" for item in jurisdiction_matches]
                )
            )
            ranked.append((float(raw_score), unit, evidence))

        ranked.sort(key=lambda item: (-item[0], item[1].unit_id))
        if not ranked:
            raise ValueError("Katalogda dış evrak kabul eden birim bulunamadı.")
        if ranked and ranked[0][0] < 4:
            fallback_index = next(
                (
                    index
                    for index, (_, unit, _) in enumerate(ranked)
                    if unit.unit_id == "ORKGM-EB-001"
                ),
                0,
            )
            ranked.insert(0, ranked.pop(fallback_index))
        best_score, best_unit, evidence = ranked[0]
        second_score = ranked[1][0] if len(ranked) > 1 else 0.0
        maximum = max(best_score, 1.0)
        alternatives = [
            {
                "unit_id": unit.unit_id,
                "unit_name": unit.unit_name,
                "hierarchy": unit.hierarchy,
                "score": round(score / maximum, 2),
                "evidence": alternative_evidence[:6],
            }
            for score, unit, alternative_evidence in ranked[1:4]
        ]
        normalized_score = min(0.45 + best_score * 0.08, 0.98) if best_score else 0.40
        normalized_margin = round(max(best_score - second_score, 0) / maximum, 2)
        requires_review = (
            best_score < 4
            or (second_score > 0 and normalized_margin < 0.20)
            or analysis.confidence < 0.60
            or best_unit.profile_status == "chart_only"
        )
        rationale = (
            f"Evrak içeriği organizasyon profilindeki şu kanıtlarla eşleşti: "
            f"{', '.join(evidence[:6])}."
            if evidence
            else "Belirgin alan eşleşmesi bulunamadı; evrak insan incelemesine alındı."
        )
        if requires_review:
            rationale += " Nihai havale öncesinde yetkili kullanıcı onayı gerekir."
        return RoutingRecommendation(
            unit_id=best_unit.unit_id,
            unit_name=best_unit.unit_name,
            hierarchy=best_unit.hierarchy,
            rationale=rationale,
            score=round(normalized_score, 2),
            alternatives=alternatives,
            routing_status="needs_review" if requires_review else "proposed",
            requires_human_review=requires_review,
            evidence=evidence[:8],
            decision_basis=[
                "Kapalı organizasyon hedef listesi",
                "İçerik ve sorumluluk profili eşleşmesi",
                "Düşük güven/yakın skor için insan denetimi",
            ],
            organization_version=self.organization_version,
            target_level=best_unit.unit_type,
            score_margin=normalized_margin,
        )
