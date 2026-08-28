from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from karayol_agent.agents import ClassificationAgent, ContentAnalysisAgent, RoutingAgent
from karayol_agent.evaluation import (
    EvaluationRecordResult,
    EvaluationReport,
    EvaluationService,
    GoldDataset,
)
from karayol_agent.schemas import (
    DocumentAnalysis,
    LegislationChunk,
    RetrievalChannelContribution,
    SearchHit,
)


ROOT = Path(__file__).resolve().parents[1]


def build_evaluator() -> EvaluationService:
    return EvaluationService(
        legislation_path=ROOT / "data" / "synthetic_legislation.json",
        units_path=ROOT / "data" / "synthetic_units.json",
    )


def _single_record_dataset(tmp_path: Path) -> Path:
    payload = json.loads(
        (ROOT / "data" / "synthetic_gold.json").read_text(encoding="utf-8")
    )
    payload["data"] = payload["data"][:1]
    path = tmp_path / "single_gold.json"
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return path


def _retrieval_hit(*, hybrid: bool = False) -> SearchHit:
    contributions = (
        [
            RetrievalChannelContribution(
                channel="lexical",
                rank=1,
                raw_score=4.25,
                rrf_contribution=1 / 61,
            ),
            RetrievalChannelContribution(
                channel="dense",
                rank=2,
                raw_score=0.87,
                rrf_contribution=1 / 62,
            ),
        ]
        if hybrid
        else []
    )
    return SearchHit(
        chunk=LegislationChunk(
            chunk_id="SENT-KRY-001",
            title="Sentetik Karayolu Evrak İş Akışı Kuralları",
            section="Yol bakım başvuruları",
            article="Kural 1",
            text="Yol bakım ve onarım başvuruları ilgili birime yönlendirilir.",
            source="data/synthetic_legislation.json",
            status="sentetik_demo_kurali",
            tags=["yol bakım"],
        ),
        score=(1 / 61 + 1 / 62) if hybrid else 4.25,
        matched_terms=["yol", "bakım"],
        fusion_method="rrf" if hybrid else None,
        channel_contributions=contributions,
    )


class AnalysisAwareRetriever:
    def __init__(self) -> None:
        self.calls: list[tuple[DocumentAnalysis, int]] = []

    def search_with_diagnostics(
        self, analysis: DocumentAnalysis, top_k: int = 5
    ) -> Any:
        self.calls.append((analysis, top_k))
        return SimpleNamespace(
            hits=[_retrieval_hit(hybrid=True)],
            diagnostics={
                "dense_status": "used",
                "fallback_used": False,
                "lexical_candidate_count": 1,
                "dense_candidate_count": 1,
                "fused_candidate_count": 1,
                "channel_top_n": 20,
                "rrf_k": 60,
            },
        )


class LegacyQueryRetriever:
    def __init__(self) -> None:
        self.calls: list[tuple[str, int]] = []

    def search(self, query: str, top_k: int = 5) -> list[SearchHit]:
        self.calls.append((query, top_k))
        return [_retrieval_hit()]


class LowSimilarityDenseRetriever:
    def search_with_diagnostics(
        self, analysis: DocumentAnalysis, top_k: int = 5
    ) -> Any:
        chunk = _retrieval_hit().chunk.model_copy(
            update={"source_kind": "synthetic"}
        )
        return SimpleNamespace(
            hits=[
                SearchHit(
                    chunk=chunk,
                    score=1 / 61,
                    channel_contributions=[
                        RetrievalChannelContribution(
                            channel="dense",
                            rank=1,
                            raw_score=-0.99,
                            rrf_contribution=1 / 61,
                        )
                    ],
                )
            ],
            diagnostics={
                "dense_status": "used",
                "fallback_used": False,
                "lexical_candidate_count": 0,
                "dense_candidate_count": 1,
                "fused_candidate_count": 1,
                "channel_top_n": 20,
                "rrf_k": 60,
            },
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


def test_ambiguous_cross_domain_signals_force_low_confidence() -> None:
    result = ClassificationAgent().run(
        "Yol yüzeyinde derin oyuk vardır ve yönlendirme tabelası yere düşmüştür."
    )

    assert result.confidence < 0.60


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


def test_default_bm25_report_keeps_baseline_mode_and_adds_lexical_trace(
    tmp_path: Path,
) -> None:
    report = build_evaluator().evaluate(_single_record_dataset(tmp_path))

    assert report.retrieval_mode == "bm25"
    assert report.results[0].retrieval_mode == "bm25"
    diagnostics = report.results[0].retrieval_diagnostics
    assert diagnostics is not None
    assert diagnostics.mode == "bm25"
    assert diagnostics.dense_status == "not_requested"
    assert diagnostics.lexical_candidate_count == len(
        report.results[0].retrieved_chunk_ids
    )
    assert all(
        trace.channels == ["lexical"]
        for trace in report.results[0].retrieval_channel_trace
    )


def test_analysis_aware_hybrid_retriever_preserves_diagnostics_and_channels(
    tmp_path: Path,
) -> None:
    dataset_path = _single_record_dataset(tmp_path)
    retriever = AnalysisAwareRetriever()
    evaluator = EvaluationService(
        legislation_path=tmp_path / "not-loaded-when-retriever-is-injected.json",
        units_path=ROOT / "data" / "synthetic_units.json",
        retriever=retriever,
        retrieval_mode="hybrid",
        retrieval_top_k=5,
    )

    report = evaluator.evaluate(dataset_path)
    output = evaluator.write(report, tmp_path / "evaluation_hybrid.json")
    payload = json.loads(output.read_text(encoding="utf-8"))

    assert report.retrieval_mode == "hybrid"
    assert len(retriever.calls) == 1
    assert isinstance(retriever.calls[0][0], DocumentAnalysis)
    assert retriever.calls[0][1] == 5
    result = report.results[0]
    assert result.retrieval_hit is True
    assert result.retrieval_diagnostics is not None
    assert result.retrieval_diagnostics.mode == "hybrid"
    assert result.retrieval_diagnostics.dense_status == "used"
    assert result.retrieval_diagnostics.dense_candidate_count == 1
    trace = result.retrieval_channel_trace[0]
    assert trace.chunk_id == "SENT-KRY-001"
    assert trace.rank == 1
    assert trace.fusion_method == "rrf"
    assert trace.channels == ["lexical", "dense"]
    assert [item.raw_score for item in trace.channel_contributions] == [4.25, 0.87]
    assert payload["retrieval_mode"] == "hybrid"
    assert payload["results"][0]["retrieval_diagnostics"]["dense_status"] == "used"
    assert payload["results"][0]["retrieval_channel_trace"][0]["channels"] == [
        "lexical",
        "dense",
    ]


def test_no_answer_slice_measures_abstention_for_low_dense_similarity(
    tmp_path: Path,
) -> None:
    payload = json.loads(
        (ROOT / "data" / "synthetic_gold.json").read_text(encoding="utf-8")
    )
    record = payload["data"][0]
    record["record_id"] = "NO-ANSWER-01"
    record["expected_reference_chunk_ids"] = []
    record["tags"] = ["sentetik", "challenge_no_answer"]
    payload["data"] = [record]
    dataset_path = tmp_path / "no_answer_gold.json"
    dataset_path.write_text(
        json.dumps(payload, ensure_ascii=False),
        encoding="utf-8",
    )
    evaluator = EvaluationService(
        legislation_path=tmp_path / "not-loaded.json",
        units_path=ROOT / "data" / "synthetic_units.json",
        retriever=LowSimilarityDenseRetriever(),
        retrieval_mode="hybrid",
        min_retrieval_score=0.20,
    )

    report = evaluator.evaluate(dataset_path)

    result = report.results[0]
    abstention = report.slices["challenge_no_answer"][
        "legal_evidence_abstention_rate"
    ]
    assert result.verified_reference_count == 0
    assert result.legal_evidence_abstained is True
    assert abstention.numerator == 1
    assert abstention.denominator == 1
    assert abstention.value == 1.0


def test_legacy_query_retriever_receives_enriched_text_and_honest_mode(
    tmp_path: Path,
) -> None:
    retriever = LegacyQueryRetriever()
    report = EvaluationService(
        legislation_path=tmp_path / "also-not-loaded.json",
        units_path=ROOT / "data" / "synthetic_units.json",
        retriever=retriever,
        retrieval_mode="bm25",
        retrieval_top_k=3,
    ).evaluate(_single_record_dataset(tmp_path))

    query, top_k = retriever.calls[0]
    assert isinstance(query, str)
    assert "yol bakim talebi" in query
    assert top_k == 3
    result = report.results[0]
    assert result.retrieval_mode == "bm25"
    assert result.retrieval_diagnostics is not None
    assert result.retrieval_diagnostics.dense_status == "not_requested"
    assert result.retrieval_channel_trace[0].channels == ["lexical"]


def test_same_gold_set_produces_separately_labeled_bm25_and_hybrid_reports(
    tmp_path: Path,
) -> None:
    dataset_path = _single_record_dataset(tmp_path)
    bm25_report = build_evaluator().evaluate(dataset_path)
    hybrid_report = EvaluationService(
        legislation_path=tmp_path / "not-needed.json",
        units_path=ROOT / "data" / "synthetic_units.json",
        retriever=AnalysisAwareRetriever(),
        retrieval_mode="hybrid",
    ).evaluate(dataset_path)

    assert bm25_report.dataset_name == hybrid_report.dataset_name
    assert bm25_report.dataset_version == hybrid_report.dataset_version
    assert bm25_report.retrieval_mode == "bm25"
    assert hybrid_report.retrieval_mode == "hybrid"
    assert {result.retrieval_mode for result in bm25_report.results} == {"bm25"}
    assert {result.retrieval_mode for result in hybrid_report.results} == {"hybrid"}


def test_old_evaluation_artifacts_receive_backward_compatible_defaults() -> None:
    payload = json.loads(
        (ROOT / "reports" / "evaluation_baseline.json").read_text(encoding="utf-8")
    )

    report = EvaluationReport.model_validate(payload)

    assert report.retrieval_mode == "bm25"
    assert all(result.retrieval_mode == "bm25" for result in report.results)
    assert all(result.retrieval_diagnostics is None for result in report.results)
    assert all(not result.retrieval_channel_trace for result in report.results)


def test_record_level_retrieval_fields_are_optional_for_legacy_callers() -> None:
    result = EvaluationRecordResult(
        record_id="legacy",
        expected_document_type="dilekce",
        actual_document_type="dilekce",
        expected_unit_id="UNIT-1",
        actual_unit_id="UNIT-1",
        actual_top3_unit_ids=["UNIT-1"],
        expected_missing_fields=[],
        actual_missing_fields=[],
        expected_template_id="template-v1",
        actual_template_id="template-v1",
        retrieved_chunk_ids=[],
        classification_correct=True,
        routing_top1_correct=True,
        routing_top3_correct=True,
        missing_fields_exact=True,
        template_correct=True,
    )

    assert result.retrieval_mode == "bm25"
    assert result.retrieval_diagnostics is None
    assert result.retrieval_channel_trace == []
