from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from karayol_agent.config import settings
from karayol_agent.curation import CurationError, LegislationManifestService
from karayol_agent.documents import ExtractionError
from karayol_agent.evaluation import EvaluationError, EvaluationService
from karayol_agent.ingestion import (
    IngestionError,
    LegislationIngestionService,
    StructureNotFoundError,
)
from karayol_agent.orchestrator import (
    ProcessNotFoundError,
    ProcessValidationError,
    build_orchestrator,
)


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

    evaluate = subcommands.add_parser(
        "evaluate",
        help="Sentetik gold veri setinde sınıflandırma, yönlendirme ve RAG ölçümü yap",
    )
    evaluate.add_argument("--dataset", type=Path, help="Gold veri seti JSON dosyası")
    evaluate.add_argument("--output", type=Path, help="Değerlendirme raporu JSON dosyası")
    return parser


def _parse_fields(values: list[str]) -> dict[str, str]:
    result: dict[str, str] = {}
    for value in values:
        if "=" not in value:
            raise SystemExit(f"Geçersiz --field değeri: {value!r}; ANAHTAR=DEGER bekleniyor.")
        key, field_value = value.split("=", 1)
        result[key.strip()] = field_value.strip()
    return result


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
        CurationError,
        EvaluationError,
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
        )
        print(
            json.dumps(
                {
                    "approved_document_count": len(reports),
                    "chunk_count": sum(report.chunk_count for report in reports),
                    "outputs": [report.output_file for report in reports],
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
            low_confidence_threshold=settings.low_confidence_threshold,
        )
        report = evaluator.evaluate(dataset_path)
        report_path = evaluator.write(report, output_path)
        print(
            json.dumps(
                {
                    "report": str(report_path),
                    "dataset": report.dataset_name,
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
    else:  # pragma: no cover
        raise AssertionError(f"Bilinmeyen komut: {arguments.command}")

    print(json.dumps(state.model_dump(mode="json"), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
