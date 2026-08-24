from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Mapping, Sequence
from inspect import Parameter, signature
from pathlib import Path
from typing import Any

from pydantic import ValidationError

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
    EvaluationRetrievalHitTrace,
    GoldDataset,
)
from karayol_agent.retrieval import BM25Index, LegislationRepository
from karayol_agent.retrieval.runtime import build_analysis_query
from karayol_agent.schemas import DocumentAnalysis, RetrievalDiagnostics, SearchHit


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
        min_retrieval_score: float = 0.20,
        low_confidence_threshold: float = 0.60,
        retriever: Any | None = None,
        retrieval_mode: str = "bm25",
    ) -> None:
        normalized_mode = retrieval_mode.strip().casefold()
        if normalized_mode not in {"bm25", "hybrid"}:
            raise ValueError("retrieval_mode yalnızca 'bm25' veya 'hybrid' olabilir.")
        if retriever is None and normalized_mode != "bm25":
            raise ValueError(
                "hybrid evaluation için açık bir retriever enjekte edilmelidir."
            )

        self.classifier = ClassificationAgent()
        self.analyzer = ContentAnalysisAgent()
        self.retrieval_top_k = retrieval_top_k
        self.retrieval_mode = normalized_mode
        self.retriever = retriever
        if retriever is None:
            chunks = LegislationRepository(
                legislation_path, trusted_synthetic=True
            ).load()
            self.researcher: LegislationResearchAgent | None = (
                LegislationResearchAgent(
                    BM25Index(chunks), top_k=retrieval_top_k
                )
            )
        else:
            # An injected retriever owns its corpus/backends. In particular, a
            # production analysis-aware hybrid retriever already contains its
            # lexical index and should not trigger a second repository load.
            self.researcher = None
        self.verifier = SourceVerificationAgent(
            min_retrieval_score=min_retrieval_score
        )
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
            hits, raw_retrieval_diagnostics = self._retrieve(analysis)
            retrieval_diagnostics = self._normalize_retrieval_diagnostics(
                raw_retrieval_diagnostics,
                hits,
            )
            retrieval_channel_trace = self._channel_trace(hits)
            references = self.verifier.run(hits, analysis)
            template = self.template_selector.run(analysis, references)
            routing = self.router.run(analysis)

            top3_units = [
                routing.unit_id,
                *[str(item["unit_id"]) for item in routing.alternatives],
            ]
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
                    verified_reference_count=sum(
                        reference.verified for reference in references
                    ),
                    legal_evidence_abstained=not any(
                        reference.verified for reference in references
                    ),
                    retrieval_mode=self.retrieval_mode,
                    retrieval_diagnostics=retrieval_diagnostics,
                    retrieval_channel_trace=retrieval_channel_trace,
                )
            )

        precision = self._ratio(missing_tp, missing_tp + missing_fp)
        recall = self._ratio(missing_tp, missing_tp + missing_fn)
        f1 = self._ratio(2 * precision * recall, precision + recall)
        metrics = self._metric_bundle(results)
        standard_results = [
            result
            for result in results
            if "challenge_paraphrase" not in result.tags
            and "challenge_no_answer" not in result.tags
        ]
        challenge_results = [
            result for result in results if "challenge_paraphrase" in result.tags
        ]
        no_answer_results = [
            result for result in results if "challenge_no_answer" in result.tags
        ]
        return EvaluationReport(
            retrieval_mode=self.retrieval_mode,
            dataset_name=dataset.dataset_name,
            dataset_version=dataset.version,
            total_records=len(dataset.data),
            successful_records=len(results),
            metrics=metrics,
            slices={
                "standard": self._metric_bundle(standard_results),
                "challenge_paraphrase": self._metric_bundle(challenge_results),
                "challenge_no_answer": {
                    "legal_evidence_abstention_rate": self._metric(
                        no_answer_results,
                        "legal_evidence_abstained",
                    )
                },
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

    def _retrieve(
        self, analysis: DocumentAnalysis
    ) -> tuple[list[SearchHit], Any | None]:
        if self.retriever is None:
            if self.researcher is None:  # pragma: no cover - constructor invariant
                raise EvaluationError("Varsayılan BM25 researcher oluşturulamadı.")
            # Keep the existing baseline path byte-for-byte equivalent at the
            # call boundary: LegislationResearchAgent still builds the query and
            # invokes the same BM25Index with the same top-k value.
            return list(self.researcher.run(analysis)), None

        diagnostic_search = getattr(
            self.retriever, "search_with_diagnostics", None
        )
        search = diagnostic_search if callable(diagnostic_search) else getattr(
            self.retriever, "search", None
        )
        if callable(search):
            argument: DocumentAnalysis | str
            analysis_aware = getattr(self.retriever, "analysis_aware", None)
            if (
                bool(analysis_aware)
                if analysis_aware is not None
                else self._method_uses_analysis(search)
            ):
                argument = analysis
            else:
                argument = build_analysis_query(analysis)
            response = search(argument, top_k=self.retrieval_top_k)
            return self._unpack_retrieval_response(response)

        run = getattr(self.retriever, "run", None)
        if callable(run):
            return self._coerce_hits(run(analysis)), None
        raise EvaluationError(
            "Enjekte edilen retriever search/search_with_diagnostics/run "
            "işlemlerinden birini sağlamalıdır."
        )

    @staticmethod
    def _method_uses_analysis(method: Any) -> bool:
        marker = getattr(method, "analysis_aware", None)
        if marker is not None:
            return bool(marker)
        try:
            parameters = [
                parameter
                for parameter in signature(method).parameters.values()
                if parameter.kind
                in {Parameter.POSITIONAL_ONLY, Parameter.POSITIONAL_OR_KEYWORD}
            ]
        except (TypeError, ValueError):
            return False
        if not parameters:
            return False
        first = parameters[0]
        if first.name in {"analysis", "document_analysis"}:
            return True
        annotation = first.annotation
        return "DocumentAnalysis" in str(annotation)

    @classmethod
    def _unpack_retrieval_response(
        cls, response: Any
    ) -> tuple[list[SearchHit], Any | None]:
        if hasattr(response, "hits"):
            hits = getattr(response, "hits")
            diagnostics = getattr(response, "diagnostics", None)
        else:
            hits = response
            diagnostics = None
        return cls._coerce_hits(hits), diagnostics

    @staticmethod
    def _coerce_hits(hits: Any) -> list[SearchHit]:
        if isinstance(hits, SearchHit):
            values: Sequence[Any] = [hits]
        elif isinstance(hits, Sequence) and not isinstance(
            hits, (str, bytes, bytearray)
        ):
            values = hits
        else:
            try:
                values = list(hits)
            except TypeError as exc:
                raise EvaluationError(
                    "Retriever sonucu SearchHit dizisi olmalıdır."
                ) from exc
        try:
            return [
                hit if isinstance(hit, SearchHit) else SearchHit.model_validate(hit)
                for hit in values
            ]
        except (ValidationError, TypeError) as exc:
            raise EvaluationError(
                f"Retriever geçersiz SearchHit döndürdü: {exc}"
            ) from exc

    def _normalize_retrieval_diagnostics(
        self,
        raw: Any | None,
        hits: list[SearchHit],
    ) -> RetrievalDiagnostics:
        if raw is None:
            unique_count = len({hit.chunk.chunk_id for hit in hits})
            if self.retrieval_mode == "bm25":
                return RetrievalDiagnostics(
                    mode="bm25",
                    dense_status="not_requested",
                    lexical_candidate_count=len(hits),
                    dense_candidate_count=0,
                    fused_candidate_count=unique_count,
                )
            return RetrievalDiagnostics(
                mode=self.retrieval_mode,
                dense_status="not_reported",
                warning="Enjekte edilen retriever tanılama bilgisi sağlamadı.",
                lexical_candidate_count=self._channel_hit_count(hits, "lexical"),
                dense_candidate_count=self._channel_hit_count(hits, "dense"),
                fused_candidate_count=unique_count,
            )

        if isinstance(raw, Mapping):
            payload = dict(raw)
        elif hasattr(raw, "model_dump"):
            payload = raw.model_dump(mode="python")
        else:
            payload = {
                field_name: getattr(raw, field_name)
                for field_name in RetrievalDiagnostics.model_fields
                if hasattr(raw, field_name)
            }
        payload["mode"] = self.retrieval_mode
        try:
            return RetrievalDiagnostics.model_validate(payload)
        except ValidationError as exc:
            raise EvaluationError(
                f"Retriever diagnostics şeması doğrulanamadı: {exc}"
            ) from exc

    def _channel_trace(
        self, hits: list[SearchHit]
    ) -> list[EvaluationRetrievalHitTrace]:
        trace: list[EvaluationRetrievalHitTrace] = []
        for rank, hit in enumerate(hits, start=1):
            channels = list(
                dict.fromkeys(
                    contribution.channel
                    for contribution in hit.channel_contributions
                )
            )
            if not channels and self.retrieval_mode == "bm25":
                channels = ["lexical"]
            trace.append(
                EvaluationRetrievalHitTrace(
                    rank=rank,
                    chunk_id=hit.chunk.chunk_id,
                    score=hit.score,
                    fusion_method=hit.fusion_method,
                    matched_terms=list(hit.matched_terms),
                    channels=channels,
                    channel_contributions=list(hit.channel_contributions),
                )
            )
        return trace

    @staticmethod
    def _channel_hit_count(hits: list[SearchHit], channel: str) -> int:
        return sum(
            any(
                contribution.channel == channel
                for contribution in hit.channel_contributions
            )
            for hit in hits
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
