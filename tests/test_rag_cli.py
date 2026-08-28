from __future__ import annotations

import json
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

import karayol_agent.cli as cli_module


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_build_competition_snapshot_parser_exposes_safe_defaults() -> None:
    arguments = cli_module.build_parser().parse_args(
        ["build-competition-snapshot", "--acknowledge-not-current"]
    )

    assert arguments.command == "build-competition-snapshot"
    assert arguments.acknowledge_not_current is True
    assert arguments.output == Path("data/processed/competition_snapshot.json")
    assert arguments.max_chars == 1800


def test_snapshot_index_parser_accepts_explicit_cuda_device() -> None:
    arguments = cli_module.build_parser().parse_args(
        [
            "index-snapshot-vectors",
            "--acknowledge-not-current",
            "--device",
            "cuda:0",
        ]
    )

    assert arguments.device == "cuda:0"


def test_build_competition_snapshot_parser_rejects_non_positive_max_chars() -> None:
    with pytest.raises(SystemExit):
        cli_module.build_parser().parse_args(
            [
                "build-competition-snapshot",
                "--acknowledge-not-current",
                "--max-chars",
                "0",
            ]
        )


def test_build_competition_snapshot_requires_acknowledgement_before_ocr(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def fail_if_called(*args: object, **kwargs: object) -> object:
        raise AssertionError("OCR hazırlama güvenlik kabulünden önce başlamamalı")

    monkeypatch.setattr(
        cli_module,
        "build_core_ocr_candidate_payloads",
        fail_if_called,
    )

    result = cli_module.main(["build-competition-snapshot"])

    assert result == 2
    error = json.loads(capsys.readouterr().err)
    assert error["error_type"] == "RagConfigurationError"
    assert "--acknowledge-not-current" in error["error"]


def test_build_competition_snapshot_writes_two_ocr_outputs_and_exact_eight_inputs(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    observed: dict[str, object] = {}
    usage_notice = "Bu snapshot güncel hukuk kaynağı değildir."
    payloads = [
        {
            "document_id": "official-writing-regulation",
            "data": [{"chunk_id": "REG-1"}],
        },
        {
            "document_id": "official-writing-guide",
            "data": [{"chunk_id": "GUIDE-1"}],
        },
    ]

    def fake_ocr_builder(project_root: Path, *, max_chars: int) -> list[dict[str, object]]:
        observed["ocr_project_root"] = project_root
        observed["max_chars"] = max_chars
        return payloads

    class FakeSnapshotBuilder:
        def __init__(self, *, project_root: Path) -> None:
            observed["builder_project_root"] = project_root

        def build(
            self,
            document_outputs: object,
            output_path: Path,
            *,
            acknowledge_not_current: bool,
        ) -> Path:
            observed["document_outputs"] = list(document_outputs)  # type: ignore[arg-type]
            observed["output_path"] = output_path
            observed["acknowledge_not_current"] = acknowledge_not_current
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(
                json.dumps(
                    {
                        "document_count": 8,
                        "chunk_count": 2500,
                        "source_chunk_count": 2507,
                        "exact_duplicate_rows_consolidated": 7,
                        "usage_notice": usage_notice,
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            return output_path

    monkeypatch.setattr(
        cli_module,
        "settings",
        replace(
            cli_module.settings,
            project_root=tmp_path,
            data_dir=tmp_path / "data",
        ),
    )
    monkeypatch.setattr(
        cli_module,
        "build_core_ocr_candidate_payloads",
        fake_ocr_builder,
    )
    monkeypatch.setattr(
        cli_module,
        "CompetitionSnapshotCorpusBuilder",
        FakeSnapshotBuilder,
    )

    result = cli_module.main(
        [
            "build-competition-snapshot",
            "--acknowledge-not-current",
            "--max-chars",
            "777",
            "--output",
            "data/processed/custom-snapshot.json",
        ]
    )

    assert result == 0
    assert observed["ocr_project_root"] == tmp_path.resolve()
    assert observed["max_chars"] == 777
    assert observed["builder_project_root"] == tmp_path.resolve()
    assert observed["acknowledge_not_current"] is True
    quarantine_dir = tmp_path / "data" / "processed" / "stage3_quarantine"
    assert observed["document_outputs"] == [
        *(quarantine_dir / name for name in cli_module._COMPETITION_SNAPSHOT_TEXT_LAYER_OUTPUTS),
        quarantine_dir / "official-writing-guide.json",
        quarantine_dir / "official-writing-regulation.json",
    ]
    assert observed["output_path"] == (
        tmp_path / "data" / "processed" / "custom-snapshot.json"
    ).resolve()
    assert json.loads(
        (quarantine_dir / "official-writing-guide.json").read_text(encoding="utf-8")
    ) == payloads[1]
    assert json.loads(
        (quarantine_dir / "official-writing-regulation.json").read_text(
            encoding="utf-8"
        )
    ) == payloads[0]
    summary = json.loads(capsys.readouterr().out)
    assert summary == {
        "corpus": str(observed["output_path"]),
        "document_count": 8,
        "chunk_count": 2500,
        "source_chunk_count": 2507,
        "exact_duplicate_rows_consolidated": 7,
        "usage_notice": usage_notice,
    }


def test_index_snapshot_vectors_parser_exposes_isolated_safe_defaults() -> None:
    arguments = cli_module.build_parser().parse_args(
        ["index-snapshot-vectors", "--acknowledge-not-current"]
    )

    assert arguments.command == "index-snapshot-vectors"
    assert arguments.acknowledge_not_current is True
    assert arguments.corpus == Path("data/processed/competition_snapshot.json")
    assert arguments.qdrant_url is None
    assert arguments.qdrant_path is None
    assert arguments.collection == "competition_snapshot_chunks_v1"
    assert arguments.report_output == Path(
        "reports/competition_snapshot_index_2026-08-24.json"
    )


def test_index_snapshot_vectors_parser_rejects_url_and_path_together() -> None:
    with pytest.raises(SystemExit):
        cli_module.build_parser().parse_args(
            [
                "index-snapshot-vectors",
                "--acknowledge-not-current",
                "--qdrant-url",
                "http://localhost:6333",
                "--qdrant-path",
                "runtime/qdrant",
            ]
        )


@pytest.mark.parametrize(
    ("arguments", "expected_error"),
    [
        (["index-snapshot-vectors"], "--acknowledge-not-current"),
        (
            [
                "index-snapshot-vectors",
                "--acknowledge-not-current",
                "--collection",
                "legal_chunks_v1",
            ],
            "public koleksiyon adı",
        ),
    ],
)
def test_index_snapshot_vectors_rejects_unsafe_request_before_repository(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    arguments: list[str],
    expected_error: str,
) -> None:
    class FailRepository:
        def __init__(self, *args: object, **kwargs: object) -> None:
            raise AssertionError("Güvenlik doğrulamasından önce corpus okunmamalı")

    monkeypatch.setattr(cli_module, "LegislationRepository", FailRepository)

    result = cli_module.main(arguments)

    assert result == 2
    error = json.loads(capsys.readouterr().err)
    assert error["error_type"] == "RagConfigurationError"
    assert expected_error in error["error"]


@dataclass(frozen=True)
class _SnapshotReport:
    chunk_count: int = 3
    indexed_count: int = 3
    batch_count: int = 2
    collection_name: str = "competition_snapshot_chunks_v1"
    embedding_model: str = "jinaai/jina-embeddings-v3"
    embedding_dimension: int = 1024
    embedding_model_revision: str | None = "weights"
    embedding_code_revision: str | None = "code"
    embedding_task: str = "retrieval.passage"
    index_version: str = "1.0"
    corpus_fingerprint: str = "a" * 64
    corpus_mode: str = "competition_snapshot"
    currentness_verified: bool = False
    legal_reliance_allowed: bool = False
    usage_notice: str | None = cli_module.COMPETITION_SNAPSHOT_NOTICE


@pytest.mark.parametrize("target", ["default_path", "explicit_path", "explicit_url"])
def test_index_snapshot_vectors_wires_separate_runtime_writes_report_and_closes(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    target: str,
) -> None:
    observed: dict[str, object] = {}

    class FakeRepository:
        def __init__(self, path: Path, *, corpus_mode: object) -> None:
            observed["corpus_path"] = path
            observed["repository_corpus_mode"] = corpus_mode

        def load_with_binding(self) -> tuple[list[str], str]:
            return ["chunk-a", "chunk-b", "chunk-c"], "snapshot-binding"

    class FakeStore:
        def __init__(self, storage_mode: str) -> None:
            self.storage_mode = storage_mode
            self.closed = False

        def close(self) -> None:
            self.closed = True

    class FakeIndexingService:
        def index(self, chunks: list[str]) -> _SnapshotReport:
            observed["chunks"] = chunks
            return _SnapshotReport()

    store: FakeStore | None = None

    def fake_runtime(settings: object, *, corpus_binding: object) -> SimpleNamespace:
        nonlocal store
        observed["runtime_settings"] = settings
        observed["corpus_binding"] = corpus_binding
        store = FakeStore(
            "embedded_local"
            if getattr(settings, "qdrant_path") is not None
            else "server"
        )

        def indexing_service(*, batch_size: int) -> FakeIndexingService:
            observed["batch_size"] = batch_size
            return FakeIndexingService()

        return SimpleNamespace(
            qdrant_store=store,
            indexing_service=indexing_service,
        )

    configured = replace(
        cli_module.settings,
        project_root=tmp_path,
        data_dir=tmp_path / "data",
        runtime_dir=tmp_path / "runtime",
        qdrant_url=None,
        qdrant_path=None,
    )
    monkeypatch.setattr(cli_module, "settings", configured)
    monkeypatch.setattr(cli_module, "LegislationRepository", FakeRepository)
    monkeypatch.setattr(cli_module, "build_retrieval_runtime", fake_runtime)

    target_arguments: list[str] = []
    if target == "explicit_path":
        target_arguments = ["--qdrant-path", "runtime/custom-snapshot-qdrant"]
    elif target == "explicit_url":
        target_arguments = ["--qdrant-url", "http://qdrant.test:6333"]
    report_output = tmp_path / "reports" / f"{target}.json"

    result = cli_module.main(
        [
            "index-snapshot-vectors",
            "--acknowledge-not-current",
            *target_arguments,
            "--batch-size",
            "2",
            "--local-files-only",
            "--report-output",
            str(report_output),
        ]
    )

    assert result == 0
    assert observed["corpus_path"] == (
        tmp_path / "data" / "processed" / "competition_snapshot.json"
    ).resolve()
    assert observed["repository_corpus_mode"] == cli_module.CorpusMode.COMPETITION_SNAPSHOT
    assert observed["corpus_binding"] == "snapshot-binding"
    assert observed["chunks"] == ["chunk-a", "chunk-b", "chunk-c"]
    assert observed["batch_size"] == 2
    runtime_settings = observed["runtime_settings"]
    assert getattr(runtime_settings, "corpus_mode") == "competition_snapshot"
    assert getattr(runtime_settings, "qdrant_collection") == (
        "competition_snapshot_chunks_v1"
    )
    assert getattr(runtime_settings, "embedding_local_files_only") is True
    if target == "explicit_url":
        assert getattr(runtime_settings, "qdrant_url") == "http://qdrant.test:6333"
        assert getattr(runtime_settings, "qdrant_path") is None
        expected_storage_mode = "server"
        expected_storage_path = None
    else:
        assert getattr(runtime_settings, "qdrant_url") is None
        expected_path_name = (
            "custom-snapshot-qdrant"
            if target == "explicit_path"
            else "qdrant-competition-snapshot"
        )
        expected_path = (tmp_path / "runtime" / expected_path_name).resolve()
        assert getattr(runtime_settings, "qdrant_path") == expected_path
        expected_storage_mode = "embedded_local"
        expected_storage_path = f"runtime/{expected_path_name}"
    assert store is not None and store.closed is True

    artifact = json.loads(report_output.read_text(encoding="utf-8"))
    assert artifact["corpus"] == "data/processed/competition_snapshot.json"
    assert artifact["corpus_mode"] == "competition_snapshot"
    assert artifact["currentness_verified"] is False
    assert artifact["legal_reliance_allowed"] is False
    assert artifact["usage_notice"] == cli_module.COMPETITION_SNAPSHOT_NOTICE
    assert artifact["storage_mode"] == expected_storage_mode
    assert artifact["qdrant_path"] == expected_storage_path
    output = json.loads(capsys.readouterr().out)
    assert output["report"] == str(report_output.resolve())
    assert output["indexed_count"] == 3


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
    assert arguments.qdrant_url == "http://localhost:6333"
    assert arguments.qdrant_path is None
    assert arguments.collection == "legal_chunks_v2"
    assert arguments.batch_size == 8
    assert arguments.local_files_only is True


def test_index_vectors_parser_exposes_embedded_path() -> None:
    arguments = cli_module.build_parser().parse_args(
        [
            "index-vectors",
            "--qdrant-path",
            "runtime/qdrant-local",
        ]
    )

    assert arguments.qdrant_url is None
    assert arguments.qdrant_path == Path("runtime/qdrant-local")


def test_index_vectors_parser_rejects_url_and_path_together() -> None:
    with pytest.raises(SystemExit):
        cli_module.build_parser().parse_args(
            [
                "index-vectors",
                "--qdrant-url",
                "http://localhost:6333",
                "--qdrant-path",
                "runtime/qdrant-local",
            ]
        )


def test_index_vectors_parser_rejects_non_positive_batch_size() -> None:
    with pytest.raises(SystemExit):
        cli_module.build_parser().parse_args(
            ["index-vectors", "--batch-size", "0"]
        )


def test_index_vectors_fails_closed_without_any_qdrant_target(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        cli_module,
        "settings",
        replace(cli_module.settings, qdrant_url=None, qdrant_path=None),
    )

    result = cli_module.main(["index-vectors"])

    assert result == 2
    error = json.loads(capsys.readouterr().err)
    assert error["error_type"] == "RagConfigurationError"
    assert "--qdrant-url/QDRANT_URL" in error["error"]
    assert "--qdrant-path/KARAYOL_QDRANT_PATH" in error["error"]


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


@pytest.mark.parametrize(
    "target_source",
    ["explicit_url", "explicit_path", "settings_url", "settings_path"],
)
def test_index_vectors_wires_repository_runtime_and_json_report(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    target_source: str,
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

    qdrant_path = tmp_path / "persistent-qdrant"
    target_arguments: list[str] = []
    configured_settings = replace(
        cli_module.settings,
        qdrant_url=None,
        qdrant_path=None,
    )
    if target_source == "explicit_url":
        configured_settings = replace(
            configured_settings,
            qdrant_path=tmp_path / "ignored-settings-path",
        )
        target_arguments = ["--qdrant-url", "http://qdrant.test:6333"]
    elif target_source == "explicit_path":
        configured_settings = replace(
            configured_settings,
            qdrant_url="http://ignored-settings.test:6333",
        )
        target_arguments = ["--qdrant-path", str(qdrant_path)]
    elif target_source == "settings_url":
        configured_settings = replace(
            configured_settings,
            qdrant_url="http://qdrant.test:6333",
        )
    else:
        configured_settings = replace(
            configured_settings,
            qdrant_path=qdrant_path,
        )
    monkeypatch.setattr(cli_module, "settings", configured_settings)

    result = cli_module.main(
        [
            "index-vectors",
            "--corpus",
            str(corpus_path),
            *target_arguments,
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
    if target_source.endswith("url"):
        assert getattr(configured, "qdrant_url") == "http://qdrant.test:6333"
        assert getattr(configured, "qdrant_path") is None
    else:
        assert getattr(configured, "qdrant_url") is None
        assert getattr(configured, "qdrant_path") == qdrant_path.resolve()
    payload = json.loads(capsys.readouterr().out)
    assert payload["indexed_count"] == 2
    assert payload["embedding_task"] == "retrieval.passage"
    assert payload["corpus_fingerprint"] == "f" * 64
