"""Complete weak PDF text layers with Turkish EasyOCR for human review.

This is a curation utility, not an approval mechanism.  Its outputs always
remain review candidates and are never written into the active RAG corpus.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import statistics
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


_SAFE_DOCUMENT_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_WINDOWS_RESERVED_NAMES = {
    "aux",
    "con",
    "nul",
    "prn",
    *(f"com{number}" for number in range(1, 10)),
    *(f"lpt{number}" for number in range(1, 10)),
}


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("değer en az 1 olmalıdır")
    return parsed


def _document_spec(value: str) -> tuple[str, Path]:
    if "=" not in value:
        raise argparse.ArgumentTypeError("BELGE_KIMLIGI=PDF_YOLU bekleniyor")
    document_id, raw_path = value.split("=", 1)
    document_id = document_id.strip()
    if not document_id or not raw_path.strip():
        raise argparse.ArgumentTypeError("belge kimliği ve PDF yolu boş olamaz")
    if not _SAFE_DOCUMENT_ID.fullmatch(document_id):
        raise argparse.ArgumentTypeError(
            "belge kimliği yalnız harf, rakam, nokta, alt çizgi ve tire içerebilir"
        )
    if document_id.split(".", 1)[0].casefold() in _WINDOWS_RESERVED_NAMES:
        raise argparse.ArgumentTypeError("Windows aygıt adı belge kimliği olamaz")
    return document_id, Path(raw_path.strip())


def _assert_unique_document_ids(documents: list[tuple[str, Path]]) -> None:
    normalized = [document_id.casefold() for document_id, _ in documents]
    duplicates = sorted(
        document_id
        for document_id in set(normalized)
        if normalized.count(document_id) > 1
    )
    if duplicates:
        raise ValueError(f"yinelenen belge kimlikleri: {', '.join(duplicates)}")


def _candidate_output_path(output_dir: Path, document_id: str) -> Path:
    resolved_dir = output_dir.resolve()
    resolved_path = (resolved_dir / f"{document_id}.ocr-candidate.txt").resolve()
    try:
        resolved_path.relative_to(resolved_dir)
    except ValueError as exc:  # defense in depth if the identifier contract changes
        raise ValueError("OCR çıktı yolu hedef dizinin dışına çıkamaz") from exc
    return resolved_path


def _portable_path(path: Path, project_root: Path) -> str:
    """Serialize a project-relative path without leaking workstation details."""

    resolved = path.resolve()
    try:
        return resolved.relative_to(project_root.resolve()).as_posix()
    except ValueError:
        return resolved.name


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _normalize_text(text: str) -> str:
    lines = [re.sub(r"\s+", " ", line).strip() for line in text.splitlines()]
    return "\n".join(line for line in lines if line)


def _ocr_lines(results: list[Any]) -> tuple[str, list[float]]:
    parsed: list[tuple[float, float, str, float]] = []
    for item in results:
        if not isinstance(item, (list, tuple)) or len(item) != 3:
            continue
        box, raw_text, raw_confidence = item
        if not isinstance(box, (list, tuple)) or not box:
            continue
        text = _normalize_text(str(raw_text))
        if not text:
            continue
        xs = [float(point[0]) for point in box]
        ys = [float(point[1]) for point in box]
        parsed.append((min(ys), min(xs), text, float(raw_confidence)))
    parsed.sort(key=lambda value: (round(value[0] / 8), value[1], value[0]))
    return "\n".join(value[2] for value in parsed), [value[3] for value in parsed]


def _model_inventory(model_dir: Path) -> list[dict[str, Any]]:
    return [
        {
            "filename": path.name,
            "bytes": path.stat().st_size,
            "sha256": _sha256(path),
        }
        for path in sorted(model_dir.glob("*.pth"))
    ]


def _process_pdf(
    *,
    document_id: str,
    pdf_path: Path,
    reader: Any,
    output_dir: Path,
    project_root: Path,
    dpi: int,
    native_character_threshold: int,
    force_ocr_all: bool,
) -> dict[str, Any]:
    try:
        import pymupdf as fitz
        import numpy as np
    except ImportError as exc:  # pragma: no cover - environment guard
        raise RuntimeError("PyMuPDF ve NumPy OCR için kurulmalıdır.") from exc

    resolved_pdf = pdf_path.resolve()
    if not resolved_pdf.is_file():
        raise FileNotFoundError(resolved_pdf)
    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = _candidate_output_path(output_dir, document_id)
    pages: list[dict[str, Any]] = []
    sections: list[str] = [
        "UYARI: Bu metin makine OCR çıktısıdır; insan doğrulaması olmadan aktif RAG kanıtı değildir.",
        f"Belge kimliği: {document_id}",
        f"Kaynak PDF: {_portable_path(resolved_pdf, project_root)}",
    ]
    started = time.perf_counter()

    with fitz.open(resolved_pdf) as document:
        for page_index, page in enumerate(document, start=1):
            page_started = time.perf_counter()
            native_text = _normalize_text(page.get_text("text"))
            use_native = (
                not force_ocr_all
                and len(native_text) >= native_character_threshold
            )
            confidences: list[float] = []
            if use_native:
                page_text = native_text
                method = "native_text"
            else:
                scale = dpi / 72
                pixmap = page.get_pixmap(
                    matrix=fitz.Matrix(scale, scale),
                    colorspace=fitz.csRGB,
                    alpha=False,
                )
                image = np.frombuffer(pixmap.samples, dtype=np.uint8).reshape(
                    pixmap.height,
                    pixmap.width,
                    pixmap.n,
                )
                raw_results = reader.readtext(
                    image,
                    detail=1,
                    paragraph=False,
                    batch_size=8,
                    workers=0,
                    canvas_size=2560,
                    mag_ratio=1.0,
                )
                page_text, confidences = _ocr_lines(raw_results)
                method = "easyocr_tr_en"

            elapsed = time.perf_counter() - page_started
            page_record: dict[str, Any] = {
                "page": page_index,
                "method": method,
                "native_character_count": len(native_text),
                "output_character_count": len(page_text),
                "line_count": len(page_text.splitlines()) if page_text else 0,
                "seconds": round(elapsed, 3),
            }
            if confidences:
                page_record.update(
                    {
                        "ocr_box_count": len(confidences),
                        "ocr_mean_confidence": round(statistics.fmean(confidences), 4),
                        "ocr_min_confidence": round(min(confidences), 4),
                        "ocr_low_confidence_ratio": round(
                            sum(value < 0.50 for value in confidences)
                            / len(confidences),
                            4,
                        ),
                    }
                )
            pages.append(page_record)
            sections.extend([f"\n===== SAYFA {page_index} =====", page_text])
            print(
                json.dumps(
                    {
                        "document_id": document_id,
                        "page": page_index,
                        "page_count": len(document),
                        "method": method,
                        "characters": len(page_text),
                        "seconds": round(elapsed, 3),
                    },
                    ensure_ascii=False,
                ),
                flush=True,
            )

    output_path.write_text("\n".join(sections).strip() + "\n", encoding="utf-8")
    ocr_pages = [page for page in pages if page["method"] == "easyocr_tr_en"]
    native_pages = [page for page in pages if page["method"] == "native_text"]
    confidence_values = [
        float(page["ocr_mean_confidence"])
        for page in ocr_pages
        if "ocr_mean_confidence" in page
    ]
    return {
        "document_id": document_id,
        "source_pdf": _portable_path(resolved_pdf, project_root),
        "source_sha256": _sha256(resolved_pdf),
        "source_bytes": resolved_pdf.stat().st_size,
        "output_text": _portable_path(output_path, project_root),
        "output_sha256": _sha256(output_path),
        "output_bytes": output_path.stat().st_size,
        "output_character_count": sum(page["output_character_count"] for page in pages),
        "page_count": len(pages),
        "native_page_count": len(native_pages),
        "ocr_page_count": len(ocr_pages),
        "empty_output_page_count": sum(
            page["output_character_count"] == 0 for page in pages
        ),
        "mean_ocr_page_confidence": (
            round(statistics.fmean(confidence_values), 4)
            if confidence_values
            else None
        ),
        "seconds": round(time.perf_counter() - started, 3),
        "pages": pages,
        "status": "ocr_candidate_human_verification_required",
        "approved_for_active_rag": False,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Türkçe PDF OCR aday metni ve denetim raporu üretir."
    )
    parser.add_argument(
        "--document",
        action="append",
        type=_document_spec,
        required=True,
        metavar="BELGE_KIMLIGI=PDF_YOLU",
    )
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--model-dir", type=Path, required=True)
    parser.add_argument(
        "--project-root",
        type=Path,
        default=Path.cwd(),
        help="Rapor yollarının göreli yazılacağı proje kökü (varsayılan: cwd).",
    )
    parser.add_argument("--dpi", type=_positive_int, default=150)
    parser.add_argument("--native-character-threshold", type=_positive_int, default=250)
    parser.add_argument("--force-ocr-all", action="store_true")
    parser.add_argument("--allow-model-download", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    arguments = parser.parse_args(argv)
    try:
        _assert_unique_document_ids(arguments.document)
    except ValueError as exc:
        parser.error(str(exc))
    try:
        import easyocr
    except ImportError as exc:  # pragma: no cover - environment guard
        raise SystemExit(
            "EasyOCR bulunamadı. OCR inceleme bağımlılıklarını kurun."
        ) from exc

    model_dir = arguments.model_dir.resolve()
    model_dir.mkdir(parents=True, exist_ok=True)
    reader = easyocr.Reader(
        ["tr", "en"],
        gpu=False,
        model_storage_directory=str(model_dir),
        user_network_directory=str(model_dir),
        download_enabled=arguments.allow_model_download,
        verbose=False,
    )
    documents = [
        _process_pdf(
            document_id=document_id,
            pdf_path=pdf_path,
            reader=reader,
            output_dir=arguments.output_dir.resolve(),
            project_root=arguments.project_root.resolve(),
            dpi=arguments.dpi,
            native_character_threshold=arguments.native_character_threshold,
            force_ocr_all=arguments.force_ocr_all,
        )
        for document_id, pdf_path in arguments.document
    ]
    report = {
        "schema_version": "1.1",
        "generated_at": datetime.now(UTC).isoformat(),
        "engine": f"EasyOCR {getattr(easyocr, '__version__', 'unknown')}",
        "languages": ["tr", "en"],
        "device": "cpu",
        "dpi": arguments.dpi,
        "native_character_threshold": arguments.native_character_threshold,
        "force_ocr_all": arguments.force_ocr_all,
        "benchmark_only": False,
        "production_legal_evidence": False,
        "human_verification_required": True,
        "approved_for_active_rag": False,
        "model_files": _model_inventory(model_dir),
        "documents": documents,
    }
    report_path = arguments.report.resolve()
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "report": str(report_path),
                "document_count": len(documents),
                "page_count": sum(item["page_count"] for item in documents),
                "ocr_page_count": sum(item["ocr_page_count"] for item in documents),
                "approved_for_active_rag": False,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
