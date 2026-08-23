from __future__ import annotations

import json
from pathlib import Path

from karayol_agent.agents import ClassificationAgent, ContentAnalysisAgent, RoutingAgent
from karayol_agent.evaluation import EvaluationService, GoldDataset


ROOT = Path(__file__).resolve().parents[1]


def build_evaluator() -> EvaluationService:
    return EvaluationService(
        legislation_path=ROOT / "data" / "synthetic_legislation.json",
        units_path=ROOT / "data" / "synthetic_units.json",
    )


def test_classifier_uses_token_boundaries_for_short_keywords() -> None:
    result = ClassificationAgent().run(
        "Gönderen: Selin Örnek\nKonu: Asfalt çatlakları\n"
        "Yol yüzeyinde asfalt çatlakları vardır."
    )

    assert result.document_type == "yol_bakim_talebi"
    assert "sel" not in result.matched_keywords


def test_generic_request_phrase_does_not_override_specific_road_type() -> None:
    result = ClassificationAgent().run(
        "Konu: Yol bakım ihtiyacı\n"
        "Asfalt ve yol bakım çalışması yapılmasını talep ediyorum."
    )

    assert result.document_type == "yol_bakim_talebi"


def test_routing_without_evidence_uses_general_application_unit() -> None:
    classification = ClassificationAgent().run("Konu: Tanımsız işlem\nİçerik açıklaması.")
    analysis = ContentAnalysisAgent().run("Konu: Tanımsız işlem\nİçerik açıklaması.", classification)
    result = RoutingAgent(ROOT / "data" / "synthetic_units.json").run(analysis)

    assert result.unit_id == "ORKGM-EB-001"


def test_gold_dataset_has_balanced_baseline_and_challenge_records() -> None:
    payload = json.loads(
        (ROOT / "data" / "synthetic_gold.json").read_text(encoding="utf-8")
    )
    dataset = GoldDataset.model_validate(payload)

    assert len(dataset.data) == 48
    assert sum("challenge_paraphrase" in record.tags for record in dataset.data) == 8
    assert all("sentetik" in record.tags for record in dataset.data)


def test_evaluation_service_reports_all_core_metrics(tmp_path: Path) -> None:
    evaluator = build_evaluator()
    report = evaluator.evaluate(ROOT / "data" / "synthetic_gold.json")
    output = evaluator.write(report, tmp_path / "evaluation.json")

    assert report.total_records == 48
    assert report.successful_records == 48
    assert report.metrics["classification_accuracy"].value >= 0.80
    assert report.metrics["routing_top3_accuracy"].value >= report.metrics[
        "routing_top1_accuracy"
    ].value
    assert report.metrics["missing_fields_exact_match"].value == 1.0
    assert report.metrics["retrieval_recall_at_5"].denominator == 36
    assert report.slices["standard"]["classification_accuracy"].value == 1.0
    assert report.slices["challenge_paraphrase"]["classification_accuracy"].denominator == 8
    assert output.exists()
