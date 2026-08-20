#!/usr/bin/env python3
"""İnsan onaylı gold kayıtlar ile model tahminlerini deterministik olarak karşılaştırır."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def ratio(numerator: int, denominator: int) -> float:
    return round(numerator / denominator, 4) if denominator else 0.0


def f1(precision: float, recall: float) -> float:
    return round(2 * precision * recall / (precision + recall), 4) if precision + recall else 0.0


def normalized(value: Any) -> str:
    return " ".join(str(value or "").casefold().split())


def evaluate(gold: list[dict[str, Any]], predictions: list[dict[str, Any]]) -> dict[str, Any]:
    by_case = {item["case_id"]: item for item in predictions}
    missing_predictions = [item["case_id"] for item in gold if item["case_id"] not in by_case]

    type_counts: Counter[str] = Counter()
    type_true_positive: Counter[str] = Counter()
    type_predicted: Counter[str] = Counter()
    expected_fields: set[tuple[str, str, str]] = set()
    predicted_fields: set[tuple[str, str, str]] = set()
    expected_missing: set[tuple[str, str]] = set()
    predicted_missing: set[tuple[str, str]] = set()
    route_top1 = 0
    route_top3 = 0

    for expected in gold:
        case_id = expected["case_id"]
        prediction = by_case.get(case_id)
        expected_type = expected["document_type"]
        type_counts[expected_type] += 1
        for name, value in expected.get("expected_fields", {}).items():
            if value is not None:
                expected_fields.add((case_id, name, normalized(value)))
        expected_missing.update((case_id, name) for name in expected.get("missing_fields", []))
        if prediction is None:
            continue

        predicted_type = prediction.get("document_type")
        type_predicted[predicted_type] += 1
        if predicted_type == expected_type:
            type_true_positive[expected_type] += 1

        fields = prediction.get("extracted_fields", {})
        if isinstance(fields, list):
            fields = {field["name"]: field.get("value") for field in fields}
        for name, value in fields.items():
            if value is not None:
                predicted_fields.add((case_id, name, normalized(value)))
        predicted_missing.update((case_id, name) for name in prediction.get("missing_fields", []))

        expected_units = set(expected.get("expected_unit_ids", []))
        predicted_units = prediction.get("routing_unit_ids", [])
        if not predicted_units and prediction.get("routing"):
            routing = prediction["routing"]
            predicted_units = [routing.get("recommended_unit_id")]
            predicted_units.extend(
                candidate.get("unit_id") for candidate in routing.get("alternatives", [])
            )
        predicted_units = [unit for unit in predicted_units if unit]
        route_top1 += int(bool(predicted_units and predicted_units[0] in expected_units))
        route_top3 += int(bool(expected_units.intersection(predicted_units[:3])))

    per_type_f1 = []
    for label in type_counts:
        precision = ratio(type_true_positive[label], type_predicted[label])
        recall = ratio(type_true_positive[label], type_counts[label])
        per_type_f1.append(f1(precision, recall))

    field_tp = len(expected_fields.intersection(predicted_fields))
    field_precision = ratio(field_tp, len(predicted_fields))
    field_recall = ratio(field_tp, len(expected_fields))
    missing_tp = len(expected_missing.intersection(predicted_missing))
    evaluated_count = len(gold)

    return {
        "schema_version": "1.0",
        "gold_count": evaluated_count,
        "prediction_count": len(predictions),
        "missing_prediction_case_ids": missing_predictions,
        "classification_macro_f1": round(sum(per_type_f1) / len(per_type_f1), 4),
        "field_exact_micro_precision": field_precision,
        "field_exact_micro_recall": field_recall,
        "field_exact_micro_f1": f1(field_precision, field_recall),
        "missing_field_recall": ratio(missing_tp, len(expected_missing)),
        "routing_top1_accuracy": ratio(route_top1, evaluated_count),
        "routing_top3_accuracy": ratio(route_top3, evaluated_count),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("predictions", type=Path, help="Tahmin JSONL dosyası")
    parser.add_argument(
        "--gold", type=Path, default=Path("data/synthetic/candidate_gold.jsonl")
    )
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--allow-unreviewed",
        action="store_true",
        help="Yalnızca geliştirme amacıyla needs_review kayıtlarını kullan",
    )
    args = parser.parse_args()

    gold = read_jsonl(args.gold)
    unreviewed = [item["case_id"] for item in gold if item.get("review_status") != "approved"]
    if unreviewed and not args.allow_unreviewed:
        parser.error(
            f"Gold dosyasında {len(unreviewed)} insan onayı bekleyen kayıt var; "
            "resmî metrik üretimi engellendi."
        )
    result = evaluate(gold, read_jsonl(args.predictions))
    payload = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload + "\n", encoding="utf-8")
    print(payload)


if __name__ == "__main__":
    main()
