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

    def run(self, analysis: DocumentAnalysis) -> RoutingRecommendation:
        query = normalize_for_search(
            " ".join(
                [analysis.document_type, analysis.summary, *analysis.keywords]
            )
        )
        query_tokens = set(tokenize(query))
        ranked: list[tuple[float, UnitRecord, list[str]]] = []
        for unit in self.units:
            keyword_matches = [
                keyword for keyword in unit.keywords if normalize_for_search(keyword) in query
            ]
            responsibility_tokens = set(tokenize(" ".join(unit.responsibilities)))
            token_overlap = query_tokens & responsibility_tokens
            raw_score = len(keyword_matches) * 3 + len(token_overlap)
            evidence = list(dict.fromkeys(keyword_matches + sorted(token_overlap)))
            ranked.append((float(raw_score), unit, evidence))

        ranked.sort(key=lambda item: (-item[0], item[1].unit_id))
        if ranked and ranked[0][0] == 0:
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
        maximum = max(best_score, 1.0)
        alternatives = [
            {
                "unit_id": unit.unit_id,
                "unit_name": unit.unit_name,
                "score": round(score / maximum, 2),
            }
            for score, unit, _ in ranked[1:3]
        ]
        normalized_score = min(0.45 + best_score * 0.08, 0.98) if best_score else 0.40
        rationale = (
            f"Evrak içeriği birimin sorumluluklarıyla eşleşti: {', '.join(evidence[:6])}."
            if evidence
            else "Belirgin alan eşleşmesi bulunamadığı için genel evrak birimi önerildi."
        )
        return RoutingRecommendation(
            unit_id=best_unit.unit_id,
            unit_name=best_unit.unit_name,
            hierarchy=best_unit.hierarchy,
            rationale=rationale,
            score=round(normalized_score, 2),
            alternatives=alternatives,
        )
