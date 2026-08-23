from __future__ import annotations

import csv
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

from karayol_agent.curation.classifier import LegislationDomainClassifier
from karayol_agent.curation.models import (
    LegislationManifest,
    LegislationManifestRecord,
    ManifestSummary,
    PdfMatchStatus,
    ScopeStatus,
    TextLayerStatus,
)
from karayol_agent.ingestion.quality import assess_text_layer


class CurationError(RuntimeError):
    pass


class LegislationManifestService:
    PDF_ID_PATTERN = re.compile(r"^(?P<id>\d+)_")

    def __init__(
        self,
        *,
        project_root: Path,
        classifier: LegislationDomainClassifier | None = None,
    ) -> None:
        self.project_root = project_root.resolve()
        self.classifier = classifier or LegislationDomainClassifier()

    def build(
        self,
        records_path: Path,
        archive_root: Path,
        *,
        inspect_pdfs: bool = False,
    ) -> LegislationManifest:
        records_path = records_path.resolve()
        archive_root = archive_root.resolve()
        records = self._load_records(records_path)
        pdf_index, archive_pdf_ids = self._index_pdfs(archive_root)

        seen_ids: set[int] = set()
        manifest_records: list[LegislationManifestRecord] = []
        for source in records:
            legislation_id = self._record_id(source)
            if legislation_id in seen_ids:
                raise CurationError(
                    f"Kaynak veri kümesinde yinelenen mevzuat kimliği var: {legislation_id}"
                )
            seen_ids.add(legislation_id)
            manifest_records.append(
                self._build_record(
                    source,
                    pdf_index.get(legislation_id, []),
                    inspect_pdfs=inspect_pdfs,
                )
            )

        manifest_records.sort(key=lambda item: item.legislation_id)
        summary = self._summarize(
            manifest_records,
            source_record_count=len(records),
            unmatched_archive_pdf_count=len(archive_pdf_ids - seen_ids),
        )
        return LegislationManifest(
            source_records=self._display_path(records_path),
            archive_root=self._display_path(archive_root),
            summary=summary,
            data=manifest_records,
        )

    def write(
        self,
        manifest: LegislationManifest,
        output_path: Path,
        *,
        review_csv_path: Path | None = None,
    ) -> tuple[Path, Path]:
        output_path = output_path.resolve()
        review_csv_path = (
            review_csv_path.resolve()
            if review_csv_path
            else output_path.with_name(f"{output_path.stem}_review.csv")
        )
        output_path.parent.mkdir(parents=True, exist_ok=True)
        review_csv_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(manifest.model_dump(mode="json"), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        self._write_review_csv(manifest, review_csv_path)
        return output_path, review_csv_path

    def _build_record(
        self,
        source: dict[str, Any],
        pdf_paths: list[Path],
        *,
        inspect_pdfs: bool,
    ) -> LegislationManifestRecord:
        legislation_id = self._record_id(source)
        title = str(source.get("ad") or "").strip()
        document_type = str(source.get("tur") or "").strip()
        if not title:
            raise CurationError(f"{legislation_id} kimlikli kaydın başlığı boş.")

        classification = self.classifier.classify(title, document_type)
        if not pdf_paths:
            match_status = PdfMatchStatus.MISSING
        elif len(pdf_paths) == 1:
            match_status = PdfMatchStatus.MATCHED
        else:
            match_status = PdfMatchStatus.DUPLICATE

        record = LegislationManifestRecord(
            legislation_id=legislation_id,
            title=title,
            document_type=document_type,
            regulation_number=self._clean_optional(source.get("sayi")),
            official_gazette_number=self._clean_optional(source.get("rgSayi")),
            official_gazette_date=self._clean_optional(source.get("rgTarih")),
            source_url=self._clean_optional(source.get("detail_url")),
            local_pdfs=[self._display_path(path) for path in sorted(pdf_paths)],
            pdf_match_status=match_status,
            domain=classification.domain,
            secondary_domains=classification.secondary_domains,
            subdomain=classification.subdomain,
            classification_confidence=classification.confidence,
            classification_reasons=classification.reasons,
            scope_status=classification.scope_status,
            candidate_for_active_rag=(
                classification.candidate_for_active_rag
                and match_status == PdfMatchStatus.MATCHED
            ),
            text_layer_status=(
                TextLayerStatus.MISSING
                if match_status == PdfMatchStatus.MISSING
                else TextLayerStatus.NOT_INSPECTED
            ),
        )
        if inspect_pdfs and match_status == PdfMatchStatus.MATCHED:
            self._inspect_text_layer(record, pdf_paths[0])
        return record

    @staticmethod
    def _inspect_text_layer(record: LegislationManifestRecord, pdf_path: Path) -> None:
        try:
            import pymupdf

            document = pymupdf.open(stream=pdf_path.read_bytes(), filetype="pdf")
            try:
                page_texts = [page.get_text("text") for page in document]
            finally:
                document.close()
            quality = assess_text_layer(page_texts)
            record.text_quality = quality
            record.ocr_required = quality.requires_ocr
            record.text_layer_status = (
                TextLayerStatus.OCR_REQUIRED
                if quality.requires_ocr
                else TextLayerStatus.AVAILABLE
            )
        except Exception as exc:  # kalite kuyruğuna alınması gereken dosya hatası
            record.text_layer_status = TextLayerStatus.READ_ERROR
            record.ocr_required = None
            record.text_inspection_error = f"{type(exc).__name__}: {exc}"
            record.scope_status = ScopeStatus.REVIEW_REQUIRED
            record.candidate_for_active_rag = False

    @classmethod
    def _index_pdfs(cls, archive_root: Path) -> tuple[dict[int, list[Path]], set[int]]:
        if not archive_root.is_dir():
            raise CurationError(f"Mevzuat PDF arşivi bulunamadı: {archive_root}")
        index: dict[int, list[Path]] = {}
        archive_pdf_ids: set[int] = set()
        for path in archive_root.rglob("*.pdf"):
            match = cls.PDF_ID_PATTERN.match(path.name)
            if not match:
                continue
            legislation_id = int(match.group("id"))
            index.setdefault(legislation_id, []).append(path.resolve())
            archive_pdf_ids.add(legislation_id)
        return index, archive_pdf_ids

    @staticmethod
    def _load_records(records_path: Path) -> list[dict[str, Any]]:
        if not records_path.is_file():
            raise CurationError(f"Mevzuat kayıt dosyası bulunamadı: {records_path}")
        try:
            payload = json.loads(records_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise CurationError(f"Mevzuat kayıt dosyası okunamadı: {exc}") from exc
        records = payload.get("data") if isinstance(payload, dict) else payload
        if not isinstance(records, list):
            raise CurationError("Mevzuat kayıt dosyasında bir data listesi bulunmalı.")
        if not all(isinstance(record, dict) for record in records):
            raise CurationError("Mevzuat data listesinde nesne olmayan kayıt var.")
        return records

    @staticmethod
    def _record_id(source: dict[str, Any]) -> int:
        try:
            return int(source["mevzuatId"])
        except (KeyError, TypeError, ValueError) as exc:
            raise CurationError("Geçerli mevzuatId içermeyen kayıt bulundu.") from exc

    @staticmethod
    def _clean_optional(value: Any) -> str | None:
        if value is None:
            return None
        cleaned = str(value).strip()
        return cleaned or None

    def _display_path(self, path: Path) -> str:
        resolved = path.resolve()
        try:
            return resolved.relative_to(self.project_root).as_posix()
        except ValueError:
            return str(resolved)

    @staticmethod
    def _summarize(
        records: list[LegislationManifestRecord],
        *,
        source_record_count: int,
        unmatched_archive_pdf_count: int,
    ) -> ManifestSummary:
        domain_counts = Counter(record.domain.value for record in records)
        return ManifestSummary(
            source_record_count=source_record_count,
            manifest_record_count=len(records),
            matched_pdf_count=sum(
                record.pdf_match_status == PdfMatchStatus.MATCHED for record in records
            ),
            missing_pdf_count=sum(
                record.pdf_match_status == PdfMatchStatus.MISSING for record in records
            ),
            duplicate_pdf_count=sum(
                record.pdf_match_status == PdfMatchStatus.DUPLICATE for record in records
            ),
            unmatched_archive_pdf_count=unmatched_archive_pdf_count,
            candidate_for_active_rag_count=sum(
                record.candidate_for_active_rag for record in records
            ),
            approved_for_active_rag_count=sum(
                record.approved_for_active_rag for record in records
            ),
            review_required_count=sum(
                record.scope_status == ScopeStatus.REVIEW_REQUIRED for record in records
            ),
            out_of_scope_count=sum(
                record.scope_status == ScopeStatus.OUT_OF_SCOPE for record in records
            ),
            ocr_required_count=sum(record.ocr_required is True for record in records),
            text_read_error_count=sum(
                record.text_layer_status == TextLayerStatus.READ_ERROR for record in records
            ),
            text_not_inspected_count=sum(
                record.text_layer_status == TextLayerStatus.NOT_INSPECTED
                for record in records
            ),
            domain_counts=dict(sorted(domain_counts.items())),
        )

    @staticmethod
    def _write_review_csv(manifest: LegislationManifest, path: Path) -> None:
        fieldnames = [
            "legislation_id",
            "title",
            "document_type",
            "proposed_domain",
            "proposed_subdomain",
            "classification_confidence",
            "classification_reasons",
            "scope_status",
            "pdf_match_status",
            "local_pdf",
            "text_layer_status",
            "ocr_required",
            "official_gazette_date",
            "official_gazette_number",
            "source_url",
            "human_domain",
            "human_subdomain",
            "validity_status",
            "approved_for_active_rag",
            "reviewed_by",
            "review_notes",
        ]
        with path.open("w", encoding="utf-8-sig", newline="") as output:
            writer = csv.DictWriter(output, fieldnames=fieldnames)
            writer.writeheader()
            for record in manifest.data:
                writer.writerow(
                    {
                        "legislation_id": record.legislation_id,
                        "title": record.title,
                        "document_type": record.document_type,
                        "proposed_domain": record.domain.value,
                        "proposed_subdomain": record.subdomain,
                        "classification_confidence": record.classification_confidence,
                        "classification_reasons": " | ".join(
                            record.classification_reasons
                        ),
                        "scope_status": record.scope_status.value,
                        "pdf_match_status": record.pdf_match_status.value,
                        "local_pdf": " | ".join(record.local_pdfs),
                        "text_layer_status": record.text_layer_status.value,
                        "ocr_required": record.ocr_required,
                        "official_gazette_date": record.official_gazette_date,
                        "official_gazette_number": record.official_gazette_number,
                        "source_url": record.source_url,
                        "human_domain": "",
                        "human_subdomain": "",
                        "validity_status": "needs_verification",
                        "approved_for_active_rag": "false",
                        "reviewed_by": "",
                        "review_notes": "",
                    }
                )
