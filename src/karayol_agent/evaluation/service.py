from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

from karayol_agent.agents import (
    ClassificationAgent,
    ContentAnalysisAgent,
    LegislationResearchAgent,
    RoutingAgent,
    SourceVerificationAgent,
    TemplateSelectionAgent,
)
from karayol_agent.evaluation.models import (
    EvaluationMetric,
    EvaluationRecordResult,
    EvaluationReport,
    GoldDataset,
)
from karayol_agent.retrieval import BM25Index, LegislationRepository


class EvaluationError(RuntimeError):
    pass


class EvaluationService:
    """Aynı gold set üzerinde tekrarlanabilir çevrimdışı MVP ölçümü yapar."""

    def __init__(
        self,
        *,
        legislation_path: Path,
        units_path: Path,
        retrieval_top_k: int = 5,
        low_confidence_threshold: float = 0.60,
    ) -> None:
        chunks = LegislationRepository(
            legislation_path, trusted_synthetic=True
        ).load()
        self.classifier = ClassificationAgent()
        self.analyzer = ContentAnalysisAgent()
        self.researcher = LegislationResearchAgent(
            BM25Index(chunks), top_k=retrieval_top_k
        )
        self.verifier = SourceVerificationAgent()
        self.template_selector = TemplateSelectionAgent(low_confidence_threshold)
        self.router = RoutingAgent(units_path)

    def evaluate(self, dataset_path: Path) -> EvaluationReport:
        dataset = self._load_dataset(dataset_path)
        results: list[EvaluationRecordResult] = []
        confusion: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
        missing_tp = missing_fp = missing_fn = 0
        reciprocal_ranks: list[float] = []

        for gold in dataset.data:
            classification = self.classifier.run(gold.text)
            analysis = self.analyzer.run(gold.text, classification)
            hits = self.researcher.run(analysis)
            references = self.verifier.run(hits, analysis)
            template = self.template_selector.run(analysis, references)
            routing = self.router.run(analysis)

            top3_units = [routing.unit_id, *[str(item["unit_id"]) for item in routing.alternatives]]
            retrieved_ids = [hit.chunk.chunk_id for hit in hits]
            expected_missing = set(gold.expected_missing_fields)
            actual_missing = set(analysis.missing_fields)
            missing_tp += len(expected_missing & actual_missing)
            missing_fp += len(actual_missing - expected_missing)
            missing_fn += len(expected_missing - actual_missing)

            retrieval_hit: bool | None = None
            if gold.expected_reference_chunk_ids:
                expected_chunks = set(gold.expected_reference_chunk_ids)
                retrieval_hit = any(chunk_id in expected_chunks for chunk_id in retrieved_ids)
                rank = next(
                    (
                        index
                        for index, chunk_id in enumerate(retrieved_ids, start=1)
                        if chunk_id in expected_chunks
                    ),
                    None,
                )
                reciprocal_ranks.append(1 / rank if rank else 0.0)

            confusion[gold.expected_document_type][classification.document_type] += 1
            results.append(
                EvaluationRecordResult(
                    record_id=gold.record_id,
                    tags=gold.tags,
                    expected_document_type=gold.expected_document_type,
                    actual_document_type=classification.document_type,
                    expected_unit_id=gold.expected_unit_id,
                    actual_unit_id=routing.unit_id,
                    actual_top3_unit_ids=top3_units,
                    expected_missing_fields=sorted(expected_missing),
                    actual_missing_fields=sorted(actual_missing),
                    expected_template_id=gold.expected_template_id,
                    actual_template_id=template.template_id,
                    retrieved_chunk_ids=retrieved_ids,
                    classification_correct=(
                        classification.document_type == gold.expected_document_type
                    ),
                    routing_top1_correct=routing.unit_id == gold.expected_unit_id,
                    routing_top3_correct=gold.expected_unit_id in top3_units,
                    missing_fields_exact=expected_missing == actual_missing,
                    template_correct=template.template_id == gold.expected_template_id,
                    retrieval_hit=retrieval_hit,
                )
            )

        precision = self._ratio(missing_tp, missing_tp + missing_fp)
        recall = self._ratio(missing_tp, missing_tp + missing_fn)
        f1 = self._ratio(2 * precision * recall, precision + recall)
        metrics = self._metric_bundle(results)
        standard_results = [
            result for result in results if "challenge_paraphrase" not in result.tags
        ]
        challenge_results = [
            result for result in results if "challenge_paraphrase" in result.tags
        ]
        return EvaluationReport(
            dataset_name=dataset.dataset_name,
            dataset_version=dataset.version,
            total_records=len(dataset.data),
            successful_records=len(results),
            metrics=metrics,
            slices={
                "standard": self._metric_bundle(standard_results),
                "challenge_paraphrase": self._metric_bundle(challenge_results),
            },
            missing_field_precision=round(precision, 4),
            missing_field_recall=round(recall, 4),
            missing_field_f1=round(f1, 4),
            retrieval_mrr=round(
                sum(reciprocal_ranks) / len(reciprocal_ranks)
                if reciprocal_ranks
                else 0.0,
                4,
            ),
            classification_confusion={
                expected: dict(sorted(actual.items()))
                for expected, actual in sorted(confusion.items())
            },
            results=results,
        )

    @staticmethod
    def write(report: EvaluationReport, output_path: Path) -> Path:
        output_path = output_path.resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return output_path

    @staticmethod
    def _load_dataset(path: Path) -> GoldDataset:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            return GoldDataset.model_validate(payload)
        except Exception as exc:
            raise EvaluationError(f"Gold değerlendirme veri seti okunamadı: {exc}") from exc

    @staticmethod
    def _metric(
        records: list[EvaluationRecordResult], attribute: str
    ) -> EvaluationMetric:
        denominator = len(records)
        numerator = sum(bool(getattr(record, attribute)) for record in records)
        return EvaluationMetric(
            value=round(numerator / denominator, 4) if denominator else 0.0,
            numerator=numerator,
            denominator=denominator,
        )

    @classmethod
    def _metric_bundle(
        cls, records: list[EvaluationRecordResult]
    ) -> dict[str, EvaluationMetric]:
        retrieval_records = [record for record in records if record.retrieval_hit is not None]
        return {
            "classification_accuracy": cls._metric(records, "classification_correct"),
            "routing_top1_accuracy": cls._metric(records, "routing_top1_correct"),
            "routing_top3_accuracy": cls._metric(records, "routing_top3_correct"),
            "missing_fields_exact_match": cls._metric(records, "missing_fields_exact"),
            "template_accuracy": cls._metric(records, "template_correct"),
            "retrieval_recall_at_5": cls._metric(retrieval_records, "retrieval_hit"),
        }

    @staticmethod
    def _ratio(numerator: float, denominator: float) -> float:
        return numerator / denominator if denominator else 0.0
