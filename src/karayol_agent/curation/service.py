from __future__ import annotations

import csv
import json
import re
from collections import Counter
from datetime import datetime
from hashlib import sha256
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from karayol_agent.curation.classifier import LegislationDomainClassifier
from karayol_agent.curation.models import (
    CurationDomain,
    LegislationManifest,
    LegislationManifestRecord,
    ManifestSummary,
    PdfMatchStatus,
    ReviewStatus,
    ScopeStatus,
    TextLayerStatus,
    ValidityStatus,
)
from karayol_agent.ingestion.quality import assess_text_layer
from karayol_agent.schemas import utc_now


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

    def build_core_inventory(self, inventory_path: Path) -> LegislationManifest:
        """Depodaki çekirdek kaynak envanterini inceleme manifestine dönüştürür.

        Çekirdek envanter DETSİS arşivindeki ``<id>_*.pdf`` adlandırmasına bağlı
        değildir. Bu köprü, gerçek dosyaların hash ve metin katmanını yeniden
        denetler; kapsam/yürürlük veya aktif-RAG onayı üretmez.
        """

        inventory_path = inventory_path.resolve()
        try:
            payload = json.loads(inventory_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise CurationError(f"Çekirdek kaynak envanteri okunamadı: {exc}") from exc
        sources = payload.get("sources") if isinstance(payload, dict) else None
        if not isinstance(sources, list) or not all(
            isinstance(source, dict) for source in sources
        ):
            raise CurationError("Çekirdek envanterde geçerli bir sources listesi yok.")

        records: list[LegislationManifestRecord] = []
        seen_document_ids: set[str] = set()
        seen_legislation_ids: set[int] = set()
        for source in sources:
            document_id = str(source.get("document_id") or "").strip()
            if not document_id:
                raise CurationError("Çekirdek envanter kaydında document_id eksik.")
            if document_id in seen_document_ids:
                raise CurationError(
                    f"Çekirdek envanterde yinelenen document_id var: {document_id}"
                )
            seen_document_ids.add(document_id)

            legislation_id = self._stable_inventory_id(document_id)
            if legislation_id in seen_legislation_ids:
                raise CurationError(
                    "Çekirdek envanter kimlik çakışması üretti; document_id değerleri "
                    "yeniden adlandırılmalıdır."
                )
            seen_legislation_ids.add(legislation_id)
            records.append(
                self._build_core_inventory_record(
                    source,
                    document_id=document_id,
                    legislation_id=legislation_id,
                )
            )

        records.sort(key=lambda item: item.document_id or "")
        summary = self._summarize(
            records,
            source_record_count=len(sources),
            unmatched_archive_pdf_count=0,
        )
        return LegislationManifest(
            source_records=self._display_path(inventory_path),
            archive_root=self._display_path(self.project_root),
            summary=summary,
            data=records,
        )

    def _build_core_inventory_record(
        self,
        source: dict[str, Any],
        *,
        document_id: str,
        legislation_id: int,
    ) -> LegislationManifestRecord:
        local_path = str(source.get("local_path") or "").strip()
        if not local_path:
            raise CurationError(f"{document_id}: local_path eksik.")
        pdf_path = (self.project_root / local_path).resolve()
        try:
            pdf_path.relative_to(self.project_root)
        except ValueError as exc:
            raise CurationError(
                f"{document_id}: local_path proje kökü dışına çıkamaz."
            ) from exc

        domain_raw = str(source.get("domain") or "unknown")
        try:
            domain = CurationDomain(domain_raw)
        except ValueError as exc:
            raise CurationError(
                f"{document_id}: desteklenmeyen domain değeri: {domain_raw!r}"
            ) from exc

        is_file = pdf_path.is_file()
        record = LegislationManifestRecord(
            legislation_id=legislation_id,
            document_id=document_id,
            title=str(source.get("title") or "").strip(),
            document_type=str(source.get("document_type") or "unknown").strip(),
            source_url=self._clean_optional(source.get("source_url")),
            local_pdfs=[self._display_path(pdf_path)] if is_file else [],
            pdf_match_status=(PdfMatchStatus.MATCHED if is_file else PdfMatchStatus.MISSING),
            domain=domain,
            subdomain=str(source.get("subdomain") or "unknown").strip(),
            classification_confidence=1.0,
            classification_reasons=[
                "Depodaki çekirdek kaynak envanterinden alındı; insan kapsam ve "
                "yürürlük doğrulaması gereklidir."
            ],
            scope_status=ScopeStatus.REVIEW_REQUIRED,
            candidate_for_active_rag=(
                is_file
                and domain
                in {
                    CurationDomain.OFFICIAL_WRITING,
                    CurationDomain.GENERAL_APPLICATION,
                    CurationDomain.KGM_INFRASTRUCTURE,
                    CurationDomain.ROAD_TRANSPORT,
                }
            ),
            text_layer_status=(
                TextLayerStatus.NOT_INSPECTED if is_file else TextLayerStatus.MISSING
            ),
        )
        if not is_file:
            return record

        expected_bytes = source.get("bytes")
        expected_sha256 = self._clean_optional(source.get("sha256"))
        actual_bytes = pdf_path.stat().st_size
        actual_sha256 = sha256(pdf_path.read_bytes()).hexdigest()
        if expected_bytes is not None and int(expected_bytes) != actual_bytes:
            raise CurationError(
                f"{document_id}: dosya boyutu çekirdek envanterden farklı."
            )
        if expected_sha256 and expected_sha256.lower() != actual_sha256:
            raise CurationError(
                f"{document_id}: SHA-256 çekirdek envanterden farklı."
            )
        self._inspect_text_layer(record, pdf_path)
        return record

    @staticmethod
    def _stable_inventory_id(document_id: str) -> int:
        # CSV inceleme akışı sayısal kimlik bekliyor. Document ID'den türeyen bu
        # değer, envanter sırası değişse bile aynı kaynağa bağlı kalır.
        return 1_000_000_000 + int(sha256(document_id.encode("utf-8")).hexdigest()[:8], 16)

    def write(
        self,
        manifest: LegislationManifest,
        output_path: Path,
        *,
        review_csv_path: Path | None = None,
    ) -> tuple[Path, Path]:
        try:
            # model_copy/atama gibi doğrulamayı atlayabilen yollarla oluşmuş
            # tutarsız bir aktif onayın diske yazılmasını da engelle.
            manifest = LegislationManifest.model_validate(
                manifest.model_dump(mode="python")
            )
        except ValidationError as exc:
            raise CurationError(
                f"Mevzuat manifesti güvenlik doğrulamasını geçemedi: {exc}"
            ) from exc
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

    @staticmethod
    def load(manifest_path: Path) -> LegislationManifest:
        manifest_path = manifest_path.resolve()
        if not manifest_path.is_file():
            raise CurationError(f"Mevzuat manifesti bulunamadı: {manifest_path}")
        try:
            payload = json.loads(manifest_path.read_text(encoding="utf-8"))
            return LegislationManifest.model_validate(payload)
        except (OSError, json.JSONDecodeError, ValidationError) as exc:
            raise CurationError(f"Mevzuat manifesti okunamadı: {exc}") from exc

    def apply_review_csv(
        self,
        manifest: LegislationManifest,
        review_csv_path: Path,
    ) -> LegislationManifest:
        """İnsan kararlarını CSV'den alır ve aktif-RAG kapılarını doğrular."""

        review_csv_path = review_csv_path.resolve()
        if not review_csv_path.is_file():
            raise CurationError(f"İnceleme CSV dosyası bulunamadı: {review_csv_path}")
        try:
            with review_csv_path.open(encoding="utf-8-sig", newline="") as source:
                rows = list(csv.DictReader(source))
        except OSError as exc:
            raise CurationError(f"İnceleme CSV dosyası okunamadı: {exc}") from exc

        records_by_id = {record.legislation_id: record for record in manifest.data}
        reviewed: dict[int, LegislationManifestRecord] = {}
        for row_number, row in enumerate(rows, start=2):
            legislation_id = self._review_row_id(row, row_number)
            if legislation_id in reviewed:
                raise CurationError(
                    f"İnceleme CSV dosyasında yinelenen mevzuat kimliği var: "
                    f"{legislation_id}"
                )
            record = records_by_id.get(legislation_id)
            if record is None:
                raise CurationError(
                    f"İnceleme CSV satırı manifestte olmayan kimlik içeriyor: "
                    f"{legislation_id}"
                )
            reviewed[legislation_id] = self._apply_review_row(
                record, row, row_number=row_number
            )

        records = [
            reviewed.get(record.legislation_id, record) for record in manifest.data
        ]
        summary = self._summarize(
            records,
            source_record_count=manifest.summary.source_record_count,
            unmatched_archive_pdf_count=manifest.summary.unmatched_archive_pdf_count,
        )
        payload = manifest.model_dump(mode="python")
        payload.update(
            {
                "schema_version": "2.0",
                "generated_at": utc_now(),
                "summary": summary,
                "data": records,
            }
        )
        return LegislationManifest.model_validate(payload)

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
            document_id=f"uab-kaysis-{legislation_id}",
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
            pdf_bytes = pdf_path.read_bytes()
            record.source_bytes = len(pdf_bytes)
            record.source_sha256 = sha256(pdf_bytes).hexdigest()

            import pymupdf

            document = pymupdf.open(stream=pdf_bytes, filetype="pdf")
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

    @staticmethod
    def _review_row_id(row: dict[str, str | None], row_number: int) -> int:
        try:
            return int((row.get("legislation_id") or "").strip())
        except ValueError as exc:
            raise CurationError(
                f"İnceleme CSV satırı {row_number}: legislation_id geçersiz."
            ) from exc

    @classmethod
    def _apply_review_row(
        cls,
        record: LegislationManifestRecord,
        row: dict[str, str | None],
        *,
        row_number: int,
    ) -> LegislationManifestRecord:
        csv_hash = cls._clean_optional(row.get("source_sha256"))
        if (
            csv_hash
            and record.source_sha256
            and csv_hash.lower() != record.source_sha256.lower()
        ):
            raise CurationError(
                f"İnceleme CSV satırı {row_number}: kaynak SHA-256 değişmiş; "
                "önce PDF yeniden denetlenmelidir."
            )

        updates: dict[str, Any] = {}
        enum_fields: tuple[tuple[str, str, type], ...] = (
            ("human_domain", "domain", CurationDomain),
            ("scope_status", "scope_status", ScopeStatus),
            ("review_status", "review_status", ReviewStatus),
            ("validity_status", "validity_status", ValidityStatus),
        )
        for csv_name, model_name, enum_type in enum_fields:
            raw = cls._clean_optional(row.get(csv_name))
            if raw is None:
                continue
            try:
                updates[model_name] = enum_type(raw)
            except ValueError as exc:
                raise CurationError(
                    f"İnceleme CSV satırı {row_number}: {csv_name} değeri "
                    f"geçersiz: {raw!r}"
                ) from exc

        human_subdomain = cls._clean_optional(row.get("human_subdomain"))
        if human_subdomain is not None:
            updates["subdomain"] = human_subdomain
        if "approved_for_active_rag" in row:
            updates["approved_for_active_rag"] = cls._parse_bool(
                row.get("approved_for_active_rag"),
                field="approved_for_active_rag",
                row_number=row_number,
            )

        reviewed_by_present = "reviewed_by" in row
        reviewed_by = cls._clean_optional(row.get("reviewed_by"))
        if reviewed_by_present:
            updates["reviewed_by"] = reviewed_by
        if "review_notes" in row:
            updates["review_notes"] = cls._clean_optional(row.get("review_notes"))

        reviewed_at_present = "reviewed_at" in row
        reviewed_at = cls._clean_optional(row.get("reviewed_at"))
        if reviewed_at_present and reviewed_at:
            try:
                updates["reviewed_at"] = datetime.fromisoformat(reviewed_at)
            except ValueError as exc:
                raise CurationError(
                    f"İnceleme CSV satırı {row_number}: reviewed_at ISO-8601 "
                    "biçiminde olmalıdır."
                ) from exc
        elif reviewed_by:
            updates["reviewed_at"] = record.reviewed_at or utc_now()
        elif reviewed_at_present or reviewed_by_present:
            updates["reviewed_at"] = None

        payload = record.model_dump(mode="python")
        payload.update(updates)
        try:
            return LegislationManifestRecord.model_validate(payload)
        except ValidationError as exc:
            raise CurationError(
                f"İnceleme CSV satırı {row_number} güvenlik doğrulamasını geçemedi: "
                f"{exc}"
            ) from exc

    @staticmethod
    def _parse_bool(
        value: str | None,
        *,
        field: str,
        row_number: int,
    ) -> bool:
        normalized = (value or "").strip().casefold()
        if normalized in {"true", "1", "yes", "evet"}:
            return True
        if normalized in {"false", "0", "no", "hayır", "hayir", ""}:
            return False
        raise CurationError(
            f"İnceleme CSV satırı {row_number}: {field} boolean olmalıdır."
        )

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
            "review_status",
            "validity_status",
            "approved_for_active_rag",
            "reviewed_by",
            "reviewed_at",
            "review_notes",
            "source_sha256",
            "source_bytes",
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
                        "human_domain": (
                            record.domain.value if record.reviewed_by else ""
                        ),
                        "human_subdomain": (
                            record.subdomain if record.reviewed_by else ""
                        ),
                        "review_status": record.review_status.value,
                        "validity_status": record.validity_status.value,
                        "approved_for_active_rag": str(
                            record.approved_for_active_rag
                        ).lower(),
                        "reviewed_by": record.reviewed_by or "",
                        "reviewed_at": (
                            record.reviewed_at.isoformat() if record.reviewed_at else ""
                        ),
                        "review_notes": record.review_notes or "",
                        "source_sha256": record.source_sha256 or "",
                        "source_bytes": record.source_bytes,
                    }
                )
