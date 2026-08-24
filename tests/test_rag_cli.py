from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

import karayol_agent.cli as cli_module


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_benchmark_retrieval_parser_exposes_isolated_runtime_options() -> None:
    arguments = cli_module.build_parser().parse_args(
        [
            "benchmark-retrieval",
            "--qdrant-path",
            "runtime/benchmark-qdrant",
            "--batch-size",
            "4",
            "--local-files-only",
        ]
    )

    assert arguments.command == "benchmark-retrieval"
    assert arguments.qdrant_path == Path("runtime/benchmark-qdrant")
    assert arguments.batch_size == 4
    assert arguments.local_files_only is True


def test_build_synthetic_graph_cli_writes_non_production_graph(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    output = tmp_path / "graph.json"

    result = cli_module.main(
        [
            "build-synthetic-graph",
            "--dataset",
            str(PROJECT_ROOT / "data" / "synthetic_gold.json"),
            "--legislation",
            str(PROJECT_ROOT / "data" / "synthetic_legislation.json"),
            "--units",
            str(PROJECT_ROOT / "data" / "synthetic_units.json"),
            "--output",
            str(output),
        ]
    )

    assert result == 0
    summary = json.loads(capsys.readouterr().out)
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert summary["benchmark_only"] is True
    assert summary["production_legal_evidence"] is False
    assert payload["node_counts"]["MevzuatKurali"] == 7


def test_retrieval_comparison_summary_reports_separate_costs_and_portable_paths(
    tmp_path: Path,
) -> None:
    def report(mode: str, recall: float, mrr: float) -> SimpleNamespace:
        return SimpleNamespace(
            retrieval_mode=mode,
            generated_at=datetime(2026, 8, 24, tzinfo=timezone.utc),
            dataset_name="gold",
            dataset_version="1.0",
            total_records=2,
            results=[
                SimpleNamespace(
                    record_id=f"REC-{index}",
                    retrieval_diagnostics=SimpleNamespace(
                        dense_status="used",
                        fallback_used=False,
                    ),
                )
                for index in range(2)
            ],
            metrics={
                "retrieval_recall_at_5": SimpleNamespace(value=recall),
            },
            retrieval_mrr=mrr,
        )

    summary = cli_module._retrieval_comparison_summary(
        bm25_report=report("bm25", 0.5, 0.25),
        hybrid_report=report("hybrid", 1.0, 0.75),
        index_report={"chunk_count": 7},
        dense_query_count=2,
        dense_query_seconds=0.02,
        bm25_report_path=tmp_path / "reports" / "bm25.json",
        hybrid_report_path=tmp_path / "reports" / "hybrid.json",
        reranked_report=report("hybrid", 0.75, 0.50),
        reranked_report_path=tmp_path / "reports" / "reranked.json",
        reranker_metadata={"model": "test/reranker"},
        reranked_dense_query_count=2,
        reranked_dense_query_seconds=0.04,
        project_root=tmp_path,
    )

    assert summary["schema_version"] == "1.2"
    assert summary["benchmark_only"] is True
    assert summary["hybrid_minus_bm25"]["retrieval_recall_at_5"] == 0.5
    assert summary["hybrid_minus_bm25"]["retrieval_mrr"] == 0.5
    assert summary["hybrid_jina_qdrant"]["average_dense_query_ms"] == 10.0
    assert summary["bm25"]["report"] == "reports/bm25.json"
    assert summary["hybrid_jina_qdrant"]["dense_query_count"] == 2
    assert summary["hybrid_jina_qdrant"]["dense_success_count"] == 2
    assert summary["hybrid_jina_qdrant"]["dense_error_count"] == 0
    assert summary["hybrid_jina_qdrant"]["dense_fallback_count"] == 0
    reranked = summary["hybrid_jina_qdrant_reranked"]
    assert reranked["report"] == "reports/reranked.json"
    assert reranked["additional_dense_query_count"] == 2
    assert reranked["average_additional_dense_query_ms"] == 20.0


def test_retrieval_comparison_rejects_dense_fallback_as_hybrid_report(
    tmp_path: Path,
) -> None:
    def report(mode: str, *, dense_status: str, fallback_used: bool) -> SimpleNamespace:
        return SimpleNamespace(
            retrieval_mode=mode,
            generated_at=datetime(2026, 8, 24, tzinfo=timezone.utc),
            dataset_name="gold",
            dataset_version="1.0",
            total_records=1,
            metrics={
                "retrieval_recall_at_5": SimpleNamespace(value=1.0),
            },
            retrieval_mrr=1.0,
            results=[
                SimpleNamespace(
                    record_id="FAIL-1",
                    retrieval_diagnostics=SimpleNamespace(
                        dense_status=dense_status,
                        fallback_used=fallback_used,
                    ),
                )
            ],
        )

    with pytest.raises(
        cli_module.SyntheticBenchmarkError,
        match="BM25 fallback sonucu hibrit benchmark olarak yazılmadı",
    ):
        cli_module._retrieval_comparison_summary(
            bm25_report=report(
                "bm25",
                dense_status="not_requested",
                fallback_used=False,
            ),
            hybrid_report=report(
                "hybrid",
                dense_status="error",
                fallback_used=True,
            ),
            index_report={"chunk_count": 7},
            dense_query_count=1,
            dense_query_seconds=0.01,
            bm25_report_path=tmp_path / "bm25.json",
            hybrid_report_path=tmp_path / "hybrid.json",
            project_root=tmp_path,
        )


def test_index_vectors_parser_exposes_safe_operational_options() -> None:
    arguments = cli_module.build_parser().parse_args(
        [
            "index-vectors",
            "--corpus",
            "active.json",
            "--qdrant-url",
            "http://localhost:6333",
            "--collection",
            "legal_chunks_v2",
            "--batch-size",
            "8",
            "--local-files-only",
        ]
    )

    assert arguments.command == "index-vectors"
    assert arguments.corpus == Path("active.json")
    assert arguments.collection == "legal_chunks_v2"
    assert arguments.batch_size == 8
    assert arguments.local_files_only is True


def test_index_vectors_parser_rejects_non_positive_batch_size() -> None:
    with pytest.raises(SystemExit):
        cli_module.build_parser().parse_args(
            ["index-vectors", "--batch-size", "0"]
        )


def test_index_vectors_rejects_unapproved_corpus_before_model_or_qdrant(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    corpus_path = tmp_path / "unapproved.json"
    corpus_path.write_text(
        json.dumps(
            [
                {
                    "chunk_id": "UNAPPROVED-1",
                    "title": "İnceleme Bekleyen Kural",
                    "section": "Madde 1",
                    "text": "Henüz doğrulanmamış metin.",
                    "source": "pending.pdf",
                }
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    result = cli_module.main(
        [
            "index-vectors",
            "--corpus",
            str(corpus_path),
            "--qdrant-url",
            "http://localhost:6333",
        ]
    )

    assert result == 2
    error = json.loads(capsys.readouterr().err)
    assert error["error_type"] == "RepositoryApprovalError"


def test_index_vectors_rejects_empty_active_corpus(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    corpus_path = tmp_path / "empty.json"
    corpus_path.write_text('{"data": []}', encoding="utf-8")

    result = cli_module.main(
        [
            "index-vectors",
            "--corpus",
            str(corpus_path),
            "--qdrant-url",
            "http://localhost:6333",
        ]
    )

    assert result == 2
    error = json.loads(capsys.readouterr().err)
    assert error["error_type"] == "RepositoryApprovalError"
    assert "schema_version=2.0" in error["error"]


@dataclass(frozen=True)
class _Report:
    chunk_count: int = 2
    indexed_count: int = 2
    batch_count: int = 1
    collection_name: str = "legal_chunks_v2"
    embedding_model: str = "jinaai/jina-embeddings-v3"
    embedding_dimension: int = 1024
    embedding_model_revision: str | None = "weights"
    embedding_code_revision: str | None = "code"
    embedding_task: str = "retrieval.passage"
    index_version: str = "2.0"
    corpus_fingerprint: str = "f" * 64


def test_index_vectors_wires_repository_runtime_and_json_report(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    corpus_path = tmp_path / "approved.json"
    corpus_path.write_text("[]", encoding="utf-8")
    observed: dict[str, object] = {}

    class FakeRepository:
        def __init__(self, path: Path) -> None:
            observed["corpus"] = path

        def load_with_binding(self) -> tuple[list[str], str]:
            return ["chunk-a", "chunk-b"], "exact-corpus-binding"

    class FakeIndexingService:
        def index(self, chunks: list[str]) -> _Report:
            observed["chunks"] = chunks
            return _Report()

    def fake_runtime(
        settings: object,
        *,
        corpus_binding: object,
    ) -> SimpleNamespace:
        observed["settings"] = settings
        observed["corpus_binding"] = corpus_binding
        return SimpleNamespace(
            indexing_service=lambda *, batch_size: (
                observed.update({"batch_size": batch_size})
                or FakeIndexingService()
            )
        )

    monkeypatch.setattr(cli_module, "LegislationRepository", FakeRepository)
    monkeypatch.setattr(cli_module, "build_retrieval_runtime", fake_runtime)

    result = cli_module.main(
        [
            "index-vectors",
            "--corpus",
            str(corpus_path),
            "--qdrant-url",
            "http://qdrant.test:6333",
            "--collection",
            "legal_chunks_v2",
            "--batch-size",
            "2",
            "--local-files-only",
        ]
    )

    assert result == 0
    assert observed["corpus"] == corpus_path.resolve()
    assert observed["chunks"] == ["chunk-a", "chunk-b"]
    assert observed["batch_size"] == 2
    assert observed["corpus_binding"] == "exact-corpus-binding"
    configured = observed["settings"]
    assert getattr(configured, "qdrant_collection") == "legal_chunks_v2"
    assert getattr(configured, "embedding_local_files_only") is True
    payload = json.loads(capsys.readouterr().out)
    assert payload["indexed_count"] == 2
    assert payload["embedding_task"] == "retrieval.passage"
    assert payload["corpus_fingerprint"] == "f" * 64
