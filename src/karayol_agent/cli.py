from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, replace
from pathlib import Path

from karayol_agent.config import settings
from karayol_agent.curation import CurationError, LegislationManifestService
from karayol_agent.documents import ExtractionError
from karayol_agent.evaluation import (
    EvaluationError,
    EvaluationService,
    SyntheticBenchmarkError,
    build_synthetic_hybrid_benchmark,
)
from karayol_agent.graph import EvidenceGraphBuilder, GraphBuildError
from karayol_agent.ingestion import (
    CompetitionSnapshotCorpusBuilder,
    IngestionError,
    LegislationIngestionService,
    OcrCandidateIngestionError,
    SnapshotBuildError,
    StructureNotFoundError,
    build_core_ocr_candidate_payloads,
)
from karayol_agent.orchestrator import (
    ProcessNotFoundError,
    ProcessValidationError,
    build_orchestrator,
)
from karayol_agent.retrieval.embeddings import (
    EmbeddingUnavailableError,
    EmbeddingValidationError,
    JinaEmbeddingProvider,
)
from karayol_agent.retrieval.contracts import (
    COMPETITION_SNAPSHOT_NOTICE,
    CorpusMode,
)
from karayol_agent.retrieval.qdrant_store import (
    DEFAULT_COLLECTION_NAME,
    DEFAULT_COMPETITION_SNAPSHOT_COLLECTION_NAME,
    QdrantUnavailable,
    SchemaMismatch,
)
from karayol_agent.retrieval.repository import (
    LegislationRepository,
    RepositoryApprovalError,
)
from karayol_agent.retrieval.reranker import (
    JinaRerankerProvider,
    RerankerUnavailableError,
    RerankerValidationError,
    RerankingRetriever,
)
from karayol_agent.retrieval.runtime import (
    RuntimeContractError,
    build_retrieval_runtime,
)
from karayol_agent.retrieval.vector_indexing import VectorIndexingError


class RagConfigurationError(RuntimeError):
    """Bir RAG komutunun zorunlu güvenlik/çalışma ayarı bulunamadığında."""


_COMPETITION_SNAPSHOT_TEXT_LAYER_OUTPUTS = (
    "law-2918.json",
    "law-4925.json",
    "uab-road-expropriation-regulation.json",
    "uab-road-infrastructure-safety-regulation.json",
    "uab-road-traffic-regulation.json",
    "uab-road-transport-regulation.json",
)
_COMPETITION_SNAPSHOT_OCR_DOCUMENT_IDS = (
    "official-writing-guide",
    "official-writing-regulation",
)


def _positive_int(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("pozitif bir tam sayı bekleniyor") from exc
    if parsed < 1:
        raise argparse.ArgumentTypeError("değer en az 1 olmalıdır")
    return parsed


def _non_empty(value: str) -> str:
    stripped = value.strip()
    if not stripped:
        raise argparse.ArgumentTypeError("boş değer kullanılamaz")
    return stripped


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="karayol-agent",
        description="Karayolu evrak akıllı ajan sistemi MVP",
    )
    subcommands = parser.add_subparsers(dest="command", required=True)

    process = subcommands.add_parser("process", help="Bir metin veya PDF evrakı işle")
    source = process.add_mutually_exclusive_group(required=True)
    source.add_argument("--file", type=Path)
    source.add_argument("--text")
    process.add_argument("--compile-pdf", action="store_true")

    show = subcommands.add_parser("status", help="Süreç durumunu göster")
    show.add_argument("document_id")

    provide = subcommands.add_parser("provide", help="Eksik alanları tamamla")
    provide.add_argument("document_id")
    provide.add_argument(
        "--field",
        action="append",
        default=[],
        metavar="ANAHTAR=DEGER",
        help="Birden fazla kez kullanılabilir",
    )
    provide.add_argument("--compile-pdf", action="store_true")

    approve = subcommands.add_parser("approve", help="Eksiksiz taslağı onayla")
    approve.add_argument("document_id")
    approve.add_argument("--by", required=True, dest="approved_by")

    ingest = subcommands.add_parser(
        "ingest", help="Bir mevzuat PDF'sini kalite kontrolünden geçirip yapısal parçala"
    )
    ingest.add_argument("--file", type=Path, required=True)
    ingest.add_argument("--title", required=True)
    ingest.add_argument(
        "--source-status",
        default="kamuya_acik_insan_dogrulamasi_gerekir",
    )
    ingest.add_argument("--output", type=Path, required=True)
    ingest.add_argument("--allow-low-quality", action="store_true")
    ingest.add_argument("--document-id")
    ingest.add_argument("--source-url")
    ingest.add_argument("--document-type", default="unknown")
    ingest.add_argument("--domain", default="unknown")
    ingest.add_argument("--subdomain", default="unknown")
    ingest.add_argument("--validity-status", default="needs_verification")

    curate = subcommands.add_parser(
        "curate-legislation",
        help="DETSİS mevzuat kayıtlarını yerel PDF arşiviyle eşleştirip inceleme manifesti üret",
    )
    curate.add_argument(
        "--records",
        type=Path,
        help="DETSİS mevzuatlar.json dosyası (varsayılan: proje veri kaynağı)",
    )
    curate.add_argument(
        "--archive",
        type=Path,
        help="Kimlikle başlayan PDF'lerin bulunduğu arşiv kökü",
    )
    curate.add_argument(
        "--output",
        type=Path,
        help="Üretilecek JSON manifesti",
    )
    curate.add_argument(
        "--review-csv",
        type=Path,
        help="İnsan doğrulaması için üretilecek CSV dosyası",
    )
    curate.add_argument(
        "--inspect-pdfs",
        action="store_true",
        help="Tüm PDF'lerin metin katmanını denetle ve OCR kuyruğunu belirle",
    )

    curate_core = subcommands.add_parser(
        "curate-core-inventory",
        help="Depodaki çekirdek mevzuat envanterini doğrulayıp inceleme manifesti üret",
    )
    curate_core.add_argument("--inventory", type=Path)
    curate_core.add_argument("--output", type=Path)
    curate_core.add_argument("--review-csv", type=Path)

    apply_review = subcommands.add_parser(
        "apply-legislation-review",
        help="İnsan inceleme CSV'sini doğrulayıp yeni mevzuat manifestine uygula",
    )
    apply_review.add_argument("--manifest", type=Path, required=True)
    apply_review.add_argument("--review-csv", type=Path, required=True)
    apply_review.add_argument("--output", type=Path, required=True)

    ingest_manifest = subcommands.add_parser(
        "ingest-approved-manifest",
        help="Yalnız aktif RAG için onaylanmış manifest kayıtlarını parçala",
    )
    ingest_manifest.add_argument("--manifest", type=Path, required=True)
    ingest_manifest.add_argument("--output-dir", type=Path, required=True)
    ingest_manifest.add_argument(
        "--corpus-output",
        type=Path,
        help="Onaylı tekil çıktıları birleştiren aktif corpus JSON dosyası",
    )

    ingest_quarantine = subcommands.add_parser(
        "ingest-manifest-quarantine",
        help="İnceleme bekleyen manifesti aktif onay vermeden toplu yapısal parçala",
    )
    ingest_quarantine.add_argument("--manifest", type=Path, required=True)
    ingest_quarantine.add_argument("--output-dir", type=Path, required=True)
    ingest_quarantine.add_argument("--report-output", type=Path)

    build_snapshot = subcommands.add_parser(
        "build-competition-snapshot",
        help=(
            "Sabitlenmiş sekiz yerel belgeyi, güncellik iddiası taşımayan "
            "yarışma snapshot korpusunda birleştir"
        ),
    )
    build_snapshot.add_argument(
        "--acknowledge-not-current",
        action="store_true",
        help=(
            "Korpusun mevzuat güncelliği/yürürlüğü doğrulanmış bir hukuk "
            "kaynağı olmadığını açıkça kabul et"
        ),
    )
    build_snapshot.add_argument(
        "--output",
        type=Path,
        default=Path("data/processed/competition_snapshot.json"),
        help="Üretilecek snapshot corpus JSON dosyası",
    )
    build_snapshot.add_argument(
        "--max-chars",
        type=_positive_int,
        default=1800,
        help="OCR adayları için azami chunk karakter sayısı",
    )

    index_snapshot = subcommands.add_parser(
        "index-snapshot-vectors",
        help=(
            "Güncellik iddiası taşımayan yarışma snapshot'ını Jina v3 ile "
            "ayrı ve kalıcı Qdrant koleksiyonuna indeksle"
        ),
    )
    index_snapshot.add_argument(
        "--acknowledge-not-current",
        action="store_true",
        help=(
            "Snapshot'ın güncel/yürürlükte hukuk kaynağı olmadığını açıkça "
            "kabul et"
        ),
    )
    index_snapshot.add_argument(
        "--corpus",
        type=Path,
        default=Path("data/processed/competition_snapshot.json"),
        help="İndekslenecek competition_snapshot corpus JSON dosyası",
    )
    snapshot_qdrant_target = index_snapshot.add_mutually_exclusive_group()
    snapshot_qdrant_target.add_argument(
        "--qdrant-url",
        type=_non_empty,
        help="Uzak Qdrant URL'si",
    )
    snapshot_qdrant_target.add_argument(
        "--qdrant-path",
        type=Path,
        help=(
            "Kalıcı gömülü Qdrant dizini (varsayılan: "
            "runtime/qdrant-competition-snapshot)"
        ),
    )
    index_snapshot.add_argument(
        "--collection",
        type=_non_empty,
        default=DEFAULT_COMPETITION_SNAPSHOT_COLLECTION_NAME,
        help="Ayrı snapshot koleksiyonu",
    )
    index_snapshot.add_argument("--batch-size", type=_positive_int)
    index_snapshot.add_argument(
        "--device",
        type=_non_empty,
        help="Embedding aygıtı: cpu, cuda veya cuda:N",
    )
    index_snapshot.add_argument(
        "--local-files-only",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Jina modelini yalnız yerel Hugging Face önbelleğinden yükle",
    )
    index_snapshot.add_argument(
        "--report-output",
        type=Path,
        default=Path("reports/competition_snapshot_index_2026-08-24.json"),
        help="İndeksleme kanıt raporu JSON dosyası",
    )

    evaluate = subcommands.add_parser(
        "evaluate",
        help="Sentetik gold veri setinde sınıflandırma, yönlendirme ve RAG ölçümü yap",
    )
    evaluate.add_argument("--dataset", type=Path, help="Gold veri seti JSON dosyası")
    evaluate.add_argument("--output", type=Path, help="Değerlendirme raporu JSON dosyası")

    benchmark = subcommands.add_parser(
        "benchmark-retrieval",
        help=(
            "Dondurulmuş sentetik gold sette BM25 ile gerçek yerel "
            "Jina/Qdrant hibrit retrieval'ı karşılaştır"
        ),
    )
    benchmark.add_argument("--dataset", type=Path)
    benchmark.add_argument("--legislation", type=Path)
    benchmark.add_argument("--units", type=Path)
    benchmark.add_argument("--bm25-output", type=Path)
    benchmark.add_argument("--hybrid-output", type=Path)
    benchmark.add_argument("--summary-output", type=Path)
    benchmark.add_argument(
        "--qdrant-path",
        type=Path,
        help="Verilmezse Qdrant yalnız bellek içinde çalışır",
    )
    benchmark.add_argument("--batch-size", type=_positive_int)
    benchmark.add_argument(
        "--with-reranker",
        action="store_true",
        help="Pinli çok dilli Jina reranker ablation'ını da çalıştır",
    )
    benchmark.add_argument("--reranked-output", type=Path)
    benchmark.add_argument(
        "--local-files-only",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Pinli Jina modelini yalnız yerel Hugging Face önbelleğinden yükle",
    )

    build_graph = subcommands.add_parser(
        "build-synthetic-graph",
        help=(
            "Dondurulmuş sentetik gold setten kanıt izli küçük "
            "mevzuat-birim-şablon grafı üret"
        ),
    )
    build_graph.add_argument("--dataset", type=Path)
    build_graph.add_argument("--legislation", type=Path)
    build_graph.add_argument("--units", type=Path)
    build_graph.add_argument("--output", type=Path)

    index_vectors = subcommands.add_parser(
        "index-vectors",
        help="Onaylı kamu mevzuatı parçalarını Jina v3 ile Qdrant'a indeksle",
    )
    index_vectors.add_argument(
        "--corpus",
        type=Path,
        help="Onaylı aktif corpus JSON (varsayılan: yapılandırılmış aktif corpus)",
    )
    qdrant_target = index_vectors.add_mutually_exclusive_group()
    qdrant_target.add_argument(
        "--qdrant-url",
        type=_non_empty,
        help="Qdrant URL; verilmezse QDRANT_URL kullanılır",
    )
    qdrant_target.add_argument(
        "--qdrant-path",
        type=Path,
        help=(
            "Kalıcı gömülü Qdrant dizini; verilmezse "
            "KARAYOL_QDRANT_PATH kullanılır"
        ),
    )
    index_vectors.add_argument(
        "--collection",
        type=_non_empty,
        help="Sürümlü koleksiyon adı; verilmezse KARAYOL_QDRANT_COLLECTION kullanılır",
    )
    index_vectors.add_argument("--batch-size", type=_positive_int)
    index_vectors.add_argument(
        "--device",
        type=_non_empty,
        help="Embedding aygıtı: cpu, cuda veya cuda:N",
    )
    index_vectors.add_argument(
        "--local-files-only",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Jina modelini yalnız yerel Hugging Face önbelleğinden yükle",
    )
    return parser


def _parse_fields(values: list[str]) -> dict[str, str]:
    result: dict[str, str] = {}
    for value in values:
        if "=" not in value:
            raise SystemExit(f"Geçersiz --field değeri: {value!r}; ANAHTAR=DEGER bekleniyor.")
        key, field_value = value.split("=", 1)
        result[key.strip()] = field_value.strip()
    return result


def _retrieval_metric_values(report: object) -> dict[str, float]:
    metrics = getattr(report, "metrics")
    return {
        name: float(metric.value)
        for name, metric in metrics.items()
    } | {"retrieval_mrr": float(getattr(report, "retrieval_mrr"))}


def _portable_artifact_path(path: Path, project_root: Path | None) -> str:
    """Keep persisted reports portable and free of workstation/user paths."""

    if not path.is_absolute():
        return path.as_posix()
    if project_root is not None:
        try:
            return path.resolve().relative_to(project_root.resolve()).as_posix()
        except ValueError:
            pass
    return path.name


def _strict_dense_benchmark_health(
    report: object,
    *,
    label: str,
) -> dict[str, int]:
    """Require a real dense result for every benchmark record before writing."""

    results = getattr(report, "results", None)
    total_records = getattr(report, "total_records", None)
    if not isinstance(results, list) or total_records != len(results) or not results:
        raise SyntheticBenchmarkError(
            f"{label} raporu eksik/tutarsız sonuç listesi taşıyor; rapor yazılmadı."
        )

    success_count = 0
    fallback_count = 0
    failed_records: list[str] = []
    for position, result in enumerate(results):
        diagnostics = getattr(result, "retrieval_diagnostics", None)
        if isinstance(diagnostics, dict):
            dense_status = diagnostics.get("dense_status")
            fallback_used = diagnostics.get("fallback_used") is True
        else:
            dense_status = getattr(diagnostics, "dense_status", None)
            fallback_used = getattr(diagnostics, "fallback_used", None) is True
        if fallback_used:
            fallback_count += 1
        if dense_status == "used" and not fallback_used:
            success_count += 1
            continue
        record_id = getattr(result, "record_id", None)
        failed_records.append(str(record_id or f"sonuç[{position}]"))

    error_count = len(results) - success_count
    if error_count:
        preview = ", ".join(failed_records[:5])
        suffix = f" (+{error_count - 5})" if error_count > 5 else ""
        raise SyntheticBenchmarkError(
            f"{label} dense kanalı tüm kayıtlarda kullanılamadı: "
            f"başarılı={success_count}/{len(results)}, hata={error_count}, "
            f"fallback={fallback_count}; kayıtlar={preview}{suffix}. "
            "BM25 fallback sonucu hibrit benchmark olarak yazılmadı."
        )
    return {
        "dense_success_count": success_count,
        "dense_error_count": error_count,
        "dense_fallback_count": fallback_count,
    }


def _retrieval_comparison_summary(
    *,
    bm25_report: object,
    hybrid_report: object,
    index_report: dict[str, object],
    dense_query_count: int,
    dense_query_seconds: float,
    bm25_report_path: Path,
    hybrid_report_path: Path,
    reranked_report: object | None = None,
    reranked_report_path: Path | None = None,
    reranker_metadata: dict[str, object] | None = None,
    reranked_dense_query_count: int = 0,
    reranked_dense_query_seconds: float = 0.0,
    project_root: Path | None = None,
) -> dict[str, object]:
    hybrid_health = _strict_dense_benchmark_health(
        hybrid_report,
        label="Hybrid Jina/Qdrant benchmark",
    )
    if dense_query_count != hybrid_health["dense_success_count"]:
        raise SyntheticBenchmarkError(
            "Hybrid Jina/Qdrant benchmark dense çağrı sayısı başarılı kayıt "
            "sayısıyla eşleşmiyor; rapor yazılmadı."
        )
    bm25_metrics = _retrieval_metric_values(bm25_report)
    hybrid_metrics = _retrieval_metric_values(hybrid_report)
    deltas = {
        name: round(hybrid_metrics[name] - bm25_metrics[name], 4)
        for name in sorted(bm25_metrics.keys() & hybrid_metrics.keys())
    }
    summary: dict[str, object] = {
        "schema_version": "1.2",
        "generated_at": getattr(hybrid_report, "generated_at").isoformat(),
        "dataset_name": getattr(hybrid_report, "dataset_name"),
        "dataset_version": getattr(hybrid_report, "dataset_version"),
        "total_records": getattr(hybrid_report, "total_records"),
        "benchmark_only": True,
        "production_legal_evidence": False,
        "bm25": {
            "report": _portable_artifact_path(bm25_report_path, project_root),
            "metrics": bm25_metrics,
        },
        "hybrid_jina_qdrant": {
            "report": _portable_artifact_path(hybrid_report_path, project_root),
            "metrics": hybrid_metrics,
            "index": index_report,
            "dense_query_count": dense_query_count,
            **hybrid_health,
            "dense_query_seconds": round(dense_query_seconds, 6),
            "average_dense_query_ms": round(
                dense_query_seconds * 1000 / dense_query_count,
                3,
            )
            if dense_query_count
            else 0.0,
        },
        "hybrid_minus_bm25": deltas,
    }
    if reranked_report is not None:
        if reranked_report_path is None or reranker_metadata is None:
            raise ValueError("Reranked rapor için yol ve metadata birlikte gereklidir.")
        reranked_health = _strict_dense_benchmark_health(
            reranked_report,
            label="Reranked Jina/Qdrant benchmark",
        )
        if reranked_dense_query_count != reranked_health["dense_success_count"]:
            raise SyntheticBenchmarkError(
                "Reranked benchmark ek dense çağrı sayısı başarılı kayıt sayısıyla "
                "eşleşmiyor; rapor yazılmadı."
            )
        reranked_metrics = _retrieval_metric_values(reranked_report)
        summary["hybrid_jina_qdrant_reranked"] = {
            "report": _portable_artifact_path(reranked_report_path, project_root),
            "metrics": reranked_metrics,
            "reranker": reranker_metadata,
            "additional_dense_query_count": reranked_dense_query_count,
            "additional_dense_success_count": reranked_health[
                "dense_success_count"
            ],
            "additional_dense_error_count": reranked_health["dense_error_count"],
            "additional_dense_fallback_count": reranked_health[
                "dense_fallback_count"
            ],
            "additional_dense_query_seconds": round(
                reranked_dense_query_seconds,
                6,
            ),
            "average_additional_dense_query_ms": round(
                reranked_dense_query_seconds * 1000 / reranked_dense_query_count,
                3,
            )
            if reranked_dense_query_count
            else 0.0,
        }
        summary["reranked_minus_hybrid"] = {
            name: round(reranked_metrics[name] - hybrid_metrics[name], 4)
            for name in sorted(reranked_metrics.keys() & hybrid_metrics.keys())
        }
    return summary


def main(argv: list[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)

    try:
        return _run(arguments)
    except (
        ExtractionError,
        ProcessNotFoundError,
        ProcessValidationError,
        StructureNotFoundError,
        IngestionError,
        OcrCandidateIngestionError,
        SnapshotBuildError,
        CurationError,
        EvaluationError,
        SyntheticBenchmarkError,
        GraphBuildError,
        EmbeddingUnavailableError,
        EmbeddingValidationError,
        QdrantUnavailable,
        SchemaMismatch,
        RepositoryApprovalError,
        RerankerUnavailableError,
        RerankerValidationError,
        RuntimeContractError,
        VectorIndexingError,
        RagConfigurationError,
        OSError,
    ) as exc:
        print(
            json.dumps(
                {"error": str(exc), "error_type": type(exc).__name__},
                ensure_ascii=False,
            ),
            file=sys.stderr,
        )
        return 2


def _run(arguments: argparse.Namespace) -> int:
    if arguments.command == "process":
        orchestrator = build_orchestrator()
        if arguments.file:
            state = orchestrator.process_file(
                arguments.file.resolve(), compile_pdf=arguments.compile_pdf
            )
        else:
            state = orchestrator.process_text(
                arguments.text, compile_pdf=arguments.compile_pdf
            )
    elif arguments.command == "status":
        orchestrator = build_orchestrator()
        state = orchestrator.get(arguments.document_id)
    elif arguments.command == "provide":
        orchestrator = build_orchestrator()
        state = orchestrator.provide_information(
            arguments.document_id,
            _parse_fields(arguments.field),
            compile_pdf=arguments.compile_pdf,
        )
    elif arguments.command == "approve":
        orchestrator = build_orchestrator()
        state = orchestrator.approve(arguments.document_id, arguments.approved_by)
    elif arguments.command == "ingest":
        report = LegislationIngestionService().ingest_pdf(
            arguments.file.resolve(),
            title=arguments.title,
            source_status=arguments.source_status,
            output_path=arguments.output.resolve(),
            allow_low_quality=arguments.allow_low_quality,
            document_id=arguments.document_id,
            source_url=arguments.source_url,
            document_type=arguments.document_type,
            domain=arguments.domain,
            subdomain=arguments.subdomain,
            validity_status=arguments.validity_status,
        )
        print(json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2))
        return 2 if report.quality.requires_ocr and not arguments.allow_low_quality else 0
    elif arguments.command == "curate-legislation":
        source_root = settings.project_root / "veri_kaynaklari" / "karayolu"
        records_path = arguments.records or source_root / "detsis" / "mevzuatlar.json"
        archive_root = arguments.archive or (
            settings.project_root
            / "Ulaştırma ve Altyapı Bakanlığı"
            / "Ulaştırma ve Altyapı Bakanlığı"
        )
        output_path = arguments.output or (
            settings.data_dir / "manifests" / "uab_legislation_manifest.json"
        )
        service = LegislationManifestService(project_root=settings.project_root)
        manifest = service.build(
            records_path,
            archive_root,
            inspect_pdfs=arguments.inspect_pdfs,
        )
        json_path, review_path = service.write(
            manifest,
            output_path,
            review_csv_path=arguments.review_csv,
        )
        print(
            json.dumps(
                {
                    "manifest": str(json_path),
                    "review_csv": str(review_path),
                    "summary": manifest.summary.model_dump(mode="json"),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0
    elif arguments.command == "curate-core-inventory":
        inventory_path = arguments.inventory or (
            settings.data_dir / "manifests" / "core_legislation_sources.json"
        )
        output_path = arguments.output or (
            settings.data_dir / "manifests" / "core_legislation_manifest.json"
        )
        service = LegislationManifestService(project_root=settings.project_root)
        manifest = service.build_core_inventory(inventory_path)
        json_path, review_path = service.write(
            manifest,
            output_path,
            review_csv_path=arguments.review_csv,
        )
        print(
            json.dumps(
                {
                    "manifest": str(json_path),
                    "review_csv": str(review_path),
                    "summary": manifest.summary.model_dump(mode="json"),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0
    elif arguments.command == "apply-legislation-review":
        service = LegislationManifestService(project_root=settings.project_root)
        manifest = service.load(arguments.manifest)
        reviewed_manifest = service.apply_review_csv(manifest, arguments.review_csv)
        json_path, review_path = service.write(reviewed_manifest, arguments.output)
        print(
            json.dumps(
                {
                    "manifest": str(json_path),
                    "review_csv": str(review_path),
                    "summary": reviewed_manifest.summary.model_dump(mode="json"),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0
    elif arguments.command == "ingest-approved-manifest":
        curation_service = LegislationManifestService(
            project_root=settings.project_root
        )
        manifest = curation_service.load(arguments.manifest)
        reports = LegislationIngestionService().ingest_approved_manifest(
            manifest,
            project_root=settings.project_root,
            output_dir=arguments.output_dir,
            corpus_output_path=arguments.corpus_output,
        )
        print(
            json.dumps(
                {
                    "approved_document_count": len(reports),
                    "chunk_count": sum(report.chunk_count for report in reports),
                    "outputs": [report.output_file for report in reports],
                    "corpus_output": (
                        str(arguments.corpus_output.resolve())
                        if arguments.corpus_output
                        else None
                    ),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0
    elif arguments.command == "ingest-manifest-quarantine":
        curation_service = LegislationManifestService(
            project_root=settings.project_root
        )
        manifest = curation_service.load(arguments.manifest)
        reports = LegislationIngestionService().ingest_manifest_quarantine(
            manifest,
            project_root=settings.project_root,
            output_dir=arguments.output_dir,
        )
        result = {
            "document_count": len(reports),
            "chunked_document_count": sum(report.chunk_count > 0 for report in reports),
            "ocr_queue_count": sum(report.quality.requires_ocr for report in reports),
            "chunk_count": sum(report.chunk_count for report in reports),
            "approved_document_count": sum(
                report.approved_for_active_rag for report in reports
            ),
            "reports": [report.model_dump(mode="json") for report in reports],
        }
        if arguments.report_output:
            report_path = arguments.report_output.resolve()
            report_path.parent.mkdir(parents=True, exist_ok=True)
            report_path.write_text(
                json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            result["report_output"] = str(report_path)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    elif arguments.command == "build-competition-snapshot":
        if arguments.acknowledge_not_current is not True:
            raise RagConfigurationError(
                "Snapshot üretimi için --acknowledge-not-current zorunludur; "
                "bu korpus mevzuatın güncelliğini/yürürlüğünü doğrulamaz."
            )

        project_root = settings.project_root.resolve()
        payloads = build_core_ocr_candidate_payloads(
            project_root,
            max_chars=arguments.max_chars,
        )
        payload_by_document_id: dict[str, dict[str, object]] = {}
        for payload in payloads:
            if not isinstance(payload, dict):
                raise RagConfigurationError(
                    "OCR hazırlayıcı JSON nesnesi olmayan bir çıktı üretti."
                )
            document_id = payload.get("document_id")
            if not isinstance(document_id, str) or not document_id.strip():
                raise RagConfigurationError(
                    "OCR hazırlayıcı document_id içermeyen bir çıktı üretti."
                )
            if document_id in payload_by_document_id:
                raise RagConfigurationError(
                    f"OCR hazırlayıcı yinelenen belge üretti: {document_id}"
                )
            payload_by_document_id[document_id] = payload

        expected_ocr_ids = set(_COMPETITION_SNAPSHOT_OCR_DOCUMENT_IDS)
        if set(payload_by_document_id) != expected_ocr_ids:
            raise RagConfigurationError(
                "Snapshot tam olarak sabitlenmiş iki OCR belgesini bekliyor; "
                f"beklenen={sorted(expected_ocr_ids)}, "
                f"gelen={sorted(payload_by_document_id)}."
            )

        quarantine_dir = project_root / "data" / "processed" / "stage3_quarantine"
        quarantine_dir.mkdir(parents=True, exist_ok=True)
        ocr_outputs: list[Path] = []
        for document_id in _COMPETITION_SNAPSHOT_OCR_DOCUMENT_IDS:
            output = quarantine_dir / f"{document_id}.json"
            output.write_text(
                json.dumps(
                    payload_by_document_id[document_id],
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                )
                + "\n",
                encoding="utf-8",
            )
            ocr_outputs.append(output)

        document_outputs = [
            *(quarantine_dir / name for name in _COMPETITION_SNAPSHOT_TEXT_LAYER_OUTPUTS),
            *ocr_outputs,
        ]
        output_argument = arguments.output
        output_path = (
            output_argument.resolve()
            if output_argument.is_absolute()
            else (project_root / output_argument).resolve()
        )
        corpus_path = CompetitionSnapshotCorpusBuilder(
            project_root=project_root
        ).build(
            document_outputs,
            output_path,
            acknowledge_not_current=True,
        )
        corpus = json.loads(corpus_path.read_text(encoding="utf-8"))
        print(
            json.dumps(
                {
                    "corpus": str(corpus_path),
                    "document_count": corpus["document_count"],
                    "chunk_count": corpus["chunk_count"],
                    "source_chunk_count": corpus["source_chunk_count"],
                    "exact_duplicate_rows_consolidated": corpus[
                        "exact_duplicate_rows_consolidated"
                    ],
                    "usage_notice": corpus["usage_notice"],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0
    elif arguments.command == "index-snapshot-vectors":
        if arguments.acknowledge_not_current is not True:
            raise RagConfigurationError(
                "Snapshot vektör indeksleme için --acknowledge-not-current "
                "zorunludur; bu indeks mevzuatın güncelliğini/yürürlüğünü "
                "doğrulamaz."
            )
        if arguments.collection == DEFAULT_COLLECTION_NAME:
            raise RagConfigurationError(
                "Yarışma snapshot'ı public koleksiyon adı "
                f"{DEFAULT_COLLECTION_NAME!r} ile indekslenemez; "
                f"{DEFAULT_COMPETITION_SNAPSHOT_COLLECTION_NAME!r} kullanın."
            )

        project_root = settings.project_root.resolve()
        corpus_path = (
            arguments.corpus.resolve()
            if arguments.corpus.is_absolute()
            else (project_root / arguments.corpus).resolve()
        )
        qdrant_url = (
            arguments.qdrant_url.strip()
            if arguments.qdrant_url is not None
            else None
        )
        raw_qdrant_path = arguments.qdrant_path
        if qdrant_url is None and raw_qdrant_path is None:
            raw_qdrant_path = Path("runtime/qdrant-competition-snapshot")
        qdrant_path = (
            None
            if raw_qdrant_path is None
            else (
                raw_qdrant_path.resolve()
                if raw_qdrant_path.is_absolute()
                else (project_root / raw_qdrant_path).resolve()
            )
        )
        report_output = (
            arguments.report_output.resolve()
            if arguments.report_output.is_absolute()
            else (project_root / arguments.report_output).resolve()
        )

        chunks, corpus_binding = LegislationRepository(
            corpus_path,
            corpus_mode=CorpusMode.COMPETITION_SNAPSHOT,
        ).load_with_binding()
        if not chunks:
            raise RagConfigurationError(
                "Yarışma snapshot korpusu boş; Qdrant indeksi oluşturulmadı."
            )

        snapshot_settings = replace(
            settings,
            corpus_mode=CorpusMode.COMPETITION_SNAPSHOT.value,
            competition_snapshot_path=corpus_path,
            qdrant_url=qdrant_url,
            qdrant_path=qdrant_path,
            qdrant_collection=arguments.collection,
            embedding_batch_size=(
                arguments.batch_size or settings.embedding_batch_size
            ),
            embedding_device=arguments.device or settings.embedding_device,
            embedding_local_files_only=(
                settings.embedding_local_files_only
                if arguments.local_files_only is None
                else arguments.local_files_only
            ),
        )
        runtime = build_retrieval_runtime(
            snapshot_settings,
            corpus_binding=corpus_binding,
        )
        try:
            report = runtime.indexing_service(
                batch_size=snapshot_settings.embedding_batch_size
            ).index(chunks)
            if (
                report.corpus_mode != CorpusMode.COMPETITION_SNAPSHOT.value
                or report.currentness_verified is not False
                or report.legal_reliance_allowed is not False
                or report.usage_notice != COMPETITION_SNAPSHOT_NOTICE
            ):
                raise VectorIndexingError(
                    "Snapshot indeks raporu güncellik/hukuki kullanım güvenlik "
                    "sözleşmesini taşımıyor; rapor yazılmadı."
                )
            report_payload = {
                **asdict(report),
                "corpus": _portable_artifact_path(corpus_path, project_root),
                "storage_mode": runtime.qdrant_store.storage_mode,
                "qdrant_path": (
                    _portable_artifact_path(qdrant_path, project_root)
                    if qdrant_path is not None
                    else None
                ),
                "qdrant_url": qdrant_url,
                "currentness_verified": False,
                "legal_reliance_allowed": False,
                "usage_notice": COMPETITION_SNAPSHOT_NOTICE,
            }
            report_output.parent.mkdir(parents=True, exist_ok=True)
            report_output.write_text(
                json.dumps(report_payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        finally:
            runtime.qdrant_store.close()

        print(
            json.dumps(
                {
                    "report": str(report_output),
                    **report_payload,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0
    elif arguments.command == "evaluate":
        dataset_path = arguments.dataset or settings.data_dir / "synthetic_gold.json"
        output_path = arguments.output or (
            settings.project_root / "reports" / "evaluation_baseline.json"
        )
        evaluator = EvaluationService(
            legislation_path=settings.data_dir / "synthetic_legislation.json",
            units_path=settings.data_dir / "synthetic_units.json",
            retrieval_top_k=settings.retrieval_top_k,
            min_retrieval_score=settings.min_retrieval_score,
            low_confidence_threshold=settings.low_confidence_threshold,
        )
        report = evaluator.evaluate(dataset_path)
        report_path = evaluator.write(report, output_path)
        print(
            json.dumps(
                {
                    "report": str(report_path),
                    "dataset": report.dataset_name,
                    "retrieval_mode": report.retrieval_mode,
                    "records": report.total_records,
                    "metrics": {
                        name: metric.model_dump(mode="json")
                        for name, metric in report.metrics.items()
                    },
                    "missing_field_precision": report.missing_field_precision,
                    "missing_field_recall": report.missing_field_recall,
                    "missing_field_f1": report.missing_field_f1,
                    "retrieval_mrr": report.retrieval_mrr,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0
    elif arguments.command == "build-synthetic-graph":
        dataset_path = (
            arguments.dataset or settings.data_dir / "synthetic_gold.json"
        ).resolve()
        legislation_path = (
            arguments.legislation
            or settings.data_dir / "synthetic_legislation.json"
        ).resolve()
        units_path = (
            arguments.units or settings.data_dir / "synthetic_units.json"
        ).resolve()
        output_path = (
            arguments.output
            or settings.project_root / "reports" / "synthetic_evidence_graph.json"
        ).resolve()
        builder = EvidenceGraphBuilder()
        graph = builder.build(
            dataset_path=dataset_path,
            legislation_path=legislation_path,
            units_path=units_path,
        )
        builder.write(graph, output_path)
        print(
            json.dumps(
                {
                    "output": str(output_path),
                    "graph_id": graph.graph_id,
                    "benchmark_only": graph.benchmark_only,
                    "production_legal_evidence": graph.production_legal_evidence,
                    "node_counts": graph.node_counts,
                    "edge_counts": graph.edge_counts,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0
    elif arguments.command == "benchmark-retrieval":
        dataset_path = (
            arguments.dataset or settings.data_dir / "synthetic_gold.json"
        ).resolve()
        legislation_path = (
            arguments.legislation
            or settings.data_dir / "synthetic_legislation.json"
        ).resolve()
        units_path = (
            arguments.units or settings.data_dir / "synthetic_units.json"
        ).resolve()
        bm25_output = (
            arguments.bm25_output
            or settings.project_root / "reports" / "evaluation_bm25_comparison.json"
        ).resolve()
        hybrid_output = (
            arguments.hybrid_output
            or settings.project_root
            / "reports"
            / "evaluation_hybrid_jina_qdrant.json"
        ).resolve()
        summary_output = (
            arguments.summary_output
            or settings.project_root
            / "reports"
            / "evaluation_retrieval_comparison.json"
        ).resolve()
        reranked_output = (
            arguments.reranked_output
            or settings.project_root
            / "reports"
            / "evaluation_hybrid_jina_qdrant_reranked.json"
        ).resolve()

        bm25_evaluator = EvaluationService(
            legislation_path=legislation_path,
            units_path=units_path,
            retrieval_top_k=settings.retrieval_top_k,
            min_retrieval_score=settings.min_retrieval_score,
            low_confidence_threshold=settings.low_confidence_threshold,
        )
        bm25_report = bm25_evaluator.evaluate(dataset_path)

        provider = JinaEmbeddingProvider(
            model_name=settings.embedding_model,
            dimension=settings.embedding_dimension,
            backend=settings.embedding_backend,
            model_revision=settings.embedding_revision,
            code_revision=settings.embedding_code_revision,
            local_files_only=(
                settings.embedding_local_files_only
                if arguments.local_files_only is None
                else arguments.local_files_only
            ),
            batch_size=arguments.batch_size or settings.embedding_batch_size,
        )
        runtime = build_synthetic_hybrid_benchmark(
            legislation_path=legislation_path,
            embedding_provider=provider,
            qdrant_path=arguments.qdrant_path,
            channel_top_n=settings.hybrid_candidate_top_k,
            rrf_k=settings.rrf_k,
        )
        try:
            hybrid_evaluator = EvaluationService(
                legislation_path=legislation_path,
                units_path=units_path,
                retrieval_top_k=settings.retrieval_top_k,
                min_retrieval_score=settings.min_retrieval_score,
                low_confidence_threshold=settings.low_confidence_threshold,
                retriever=runtime.retriever,
                retrieval_mode="hybrid",
            )
            hybrid_report = hybrid_evaluator.evaluate(dataset_path)
            hybrid_dense_query_count = runtime.dense_retriever.query_count
            hybrid_dense_query_seconds = runtime.dense_retriever.query_seconds
            reranked_report: object | None = None
            reranker_metadata: dict[str, object] | None = None
            reranked_dense_query_count = 0
            reranked_dense_query_seconds = 0.0
            reranked_evaluator: EvaluationService | None = None
            if arguments.with_reranker:
                reranker = JinaRerankerProvider(
                    model_name=settings.reranker_model,
                    revision=settings.reranker_revision,
                    code_revision=settings.reranker_code_revision,
                    local_files_only=(
                        settings.embedding_local_files_only
                        if arguments.local_files_only is None
                        else arguments.local_files_only
                    ),
                    batch_size=settings.reranker_batch_size,
                    device="cpu",
                    use_flash_attn=False,
                )
                reranked_retriever = RerankingRetriever(
                    runtime.retriever,
                    reranker,
                    candidate_top_k=settings.reranker_candidate_top_k,
                )
                reranked_evaluator = EvaluationService(
                    legislation_path=legislation_path,
                    units_path=units_path,
                    retrieval_top_k=settings.retrieval_top_k,
                    min_retrieval_score=settings.min_retrieval_score,
                    low_confidence_threshold=settings.low_confidence_threshold,
                    retriever=reranked_retriever,
                    retrieval_mode="hybrid",
                )
                reranked_report = reranked_evaluator.evaluate(dataset_path)
                reranked_dense_query_count = (
                    runtime.dense_retriever.query_count - hybrid_dense_query_count
                )
                reranked_dense_query_seconds = (
                    runtime.dense_retriever.query_seconds - hybrid_dense_query_seconds
                )
                reranker_metadata = {
                    "model": reranker.model_name,
                    "revision": reranker.revision,
                    "code_revision": reranker.code_revision,
                    "candidate_top_k": settings.reranker_candidate_top_k,
                    "batch_size": settings.reranker_batch_size,
                    "score_calls": reranker.score_calls,
                    "score_seconds": round(reranker.score_seconds, 6),
                    "average_score_call_ms": round(
                        reranker.score_seconds * 1000 / reranker.score_calls,
                        3,
                    )
                    if reranker.score_calls
                    else 0.0,
                }
            summary = _retrieval_comparison_summary(
                bm25_report=bm25_report,
                hybrid_report=hybrid_report,
                index_report=asdict(runtime.index_report),
                dense_query_count=hybrid_dense_query_count,
                dense_query_seconds=hybrid_dense_query_seconds,
                bm25_report_path=bm25_output,
                hybrid_report_path=hybrid_output,
                reranked_report=reranked_report,
                reranked_report_path=(
                    reranked_output if reranked_report is not None else None
                ),
                reranker_metadata=reranker_metadata,
                reranked_dense_query_count=reranked_dense_query_count,
                reranked_dense_query_seconds=reranked_dense_query_seconds,
                project_root=settings.project_root,
            )
            # Health validation in the summary is intentionally completed before
            # any benchmark report is persisted. A dense failure must not leave
            # a BM25 fallback artifact labelled as Jina/Qdrant hybrid.
            bm25_evaluator.write(bm25_report, bm25_output)
            hybrid_evaluator.write(hybrid_report, hybrid_output)
            if reranked_report is not None and reranked_evaluator is not None:
                reranked_evaluator.write(reranked_report, reranked_output)
        finally:
            runtime.dense_retriever.close()

        summary_output.parent.mkdir(parents=True, exist_ok=True)
        summary_output.write_text(
            json.dumps(summary, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(json.dumps({"summary": str(summary_output), **summary}, ensure_ascii=False, indent=2))
        return 0
    elif arguments.command == "index-vectors":
        qdrant_url = arguments.qdrant_url
        qdrant_path = arguments.qdrant_path
        if qdrant_url is None and qdrant_path is None:
            qdrant_url = settings.qdrant_url
            qdrant_path = settings.qdrant_path
        if qdrant_url is None and qdrant_path is None:
            raise RagConfigurationError(
                "Qdrant hedefi zorunludur: --qdrant-url/QDRANT_URL veya "
                "--qdrant-path/KARAYOL_QDRANT_PATH verin."
            )
        if qdrant_url is not None and qdrant_path is not None:
            raise RagConfigurationError(
                "Qdrant URL ve gömülü depolama yolu aynı anda kullanılamaz."
            )
        corpus_path = (arguments.corpus or settings.active_legislation_path).resolve()
        chunks, corpus_binding = LegislationRepository(
            corpus_path
        ).load_with_binding()
        if not chunks:
            raise RagConfigurationError(
                "Aktif corpus boş; Qdrant indeksi oluşturulmadı."
            )
        rag_settings = replace(
            settings,
            qdrant_url=qdrant_url.strip() if qdrant_url is not None else None,
            qdrant_path=qdrant_path.resolve() if qdrant_path is not None else None,
            qdrant_collection=arguments.collection or settings.qdrant_collection,
            embedding_batch_size=(
                arguments.batch_size or settings.embedding_batch_size
            ),
            embedding_device=arguments.device or settings.embedding_device,
            embedding_local_files_only=(
                settings.embedding_local_files_only
                if arguments.local_files_only is None
                else arguments.local_files_only
            ),
        )
        runtime = build_retrieval_runtime(
            rag_settings,
            corpus_binding=corpus_binding,
        )
        report = runtime.indexing_service(
            batch_size=rag_settings.embedding_batch_size
        ).index(chunks)
        print(
            json.dumps(
                {
                    "corpus": str(corpus_path),
                    **asdict(report),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0
    else:  # pragma: no cover
        raise AssertionError(f"Bilinmeyen komut: {arguments.command}")

    print(json.dumps(state.model_dump(mode="json"), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
