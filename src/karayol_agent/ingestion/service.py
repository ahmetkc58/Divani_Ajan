from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import TYPE_CHECKING

from karayol_agent.ingestion.chunker import LegalStructureChunker
from karayol_agent.ingestion.quality import assess_text_layer
from karayol_agent.schemas import IngestionReport

if TYPE_CHECKING:
    from karayol_agent.curation.models import (
        LegislationManifest,
        LegislationManifestRecord,
    )


class IngestionError(ValueError):
    """Mevzuat ingestion girdisi veya güvenlik sözleşmesi hatası."""


class IngestionApprovalError(IngestionError):
    """Güvenli aktif-RAG koşulları sağlanmadan onay istendiğinde oluşur."""


class LegislationIngestionService:
    DOCUMENT_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{1,119}$")

    def __init__(self, chunker: LegalStructureChunker | None = None) -> None:
        self.chunker = chunker or LegalStructureChunker()

    def ingest_pdf(
        self,
        path: Path,
        *,
        title: str,
        source_status: str,
        output_path: Path,
        allow_low_quality: bool = False,
        document_id: str | None = None,
        source_url: str | None = None,
        document_type: str = "unknown",
        domain: str = "unknown",
        subdomain: str = "unknown",
        validity_status: str = "needs_verification",
        approved_for_active_rag: bool = False,
        reviewed_by: str | None = None,
        review_notes: str | None = None,
        source_kind: str = "public_legislation",
    ) -> IngestionReport:
        if approved_for_active_rag:
            raise IngestionApprovalError(
                "Genel PDF alımı aktif RAG onayı veremez; insan tarafından "
                "doğrulanmış manifest kaydıyla ingest_manifest_record kullanın."
            )
        return self._ingest_pdf(
            path,
            title=title,
            source_status=source_status,
            output_path=output_path,
            allow_low_quality=allow_low_quality,
            document_id=document_id,
            source_url=source_url,
            document_type=document_type,
            domain=domain,
            subdomain=subdomain,
            validity_status=validity_status,
            approved_for_active_rag=False,
            reviewed_by=reviewed_by,
            review_notes=review_notes,
            reviewed_at=None,
            source_kind=source_kind,
            expected_source_sha256=None,
        )

    def ingest_manifest_record(
        self,
        record: "LegislationManifestRecord",
        *,
        path: Path,
        output_path: Path,
    ) -> IngestionReport:
        blockers = list(record.activation_blockers())
        if not record.approved_for_active_rag:
            blockers.insert(0, "manifest_record_not_approved")
        if blockers:
            raise IngestionApprovalError(
                "Manifest kaydı aktif RAG için kullanılamaz: " + ", ".join(blockers)
            )

        return self._ingest_pdf(
            path,
            title=record.title,
            source_status="resmi_kaynak_insan_dogrulamali",
            output_path=output_path,
            allow_low_quality=False,
            document_id=record.document_id,
            source_url=record.source_url,
            document_type=record.document_type,
            domain=self._enum_value(record.domain),
            subdomain=record.subdomain,
            validity_status=self._enum_value(record.validity_status),
            approved_for_active_rag=True,
            reviewed_by=record.reviewed_by,
            review_notes=record.review_notes,
            reviewed_at=(
                record.reviewed_at.isoformat() if record.reviewed_at else None
            ),
            source_kind="public_legislation",
            expected_source_sha256=record.source_sha256,
        )

    def ingest_approved_manifest(
        self,
        manifest: "LegislationManifest",
        *,
        project_root: Path,
        output_dir: Path,
        corpus_output_path: Path | None = None,
    ) -> list[IngestionReport]:
        """Manifestte açıkça onaylanmış kayıtları ayrı JSON çıktılara işler."""

        project_root = project_root.resolve()
        output_dir = output_dir.resolve()
        reports: list[IngestionReport] = []
        for record in manifest.data:
            if not record.approved_for_active_rag:
                continue
            if len(record.local_pdfs) != 1:
                raise IngestionApprovalError(
                    f"{record.document_id or record.legislation_id}: "
                    "tekil PDF yolu yok."
                )
            source_path = Path(record.local_pdfs[0])
            if not source_path.is_absolute():
                source_path = project_root / source_path
            document_id = record.document_id or f"legislation-{record.legislation_id}"
            reports.append(
                self.ingest_manifest_record(
                    record,
                    path=source_path,
                    output_path=output_dir / f"{document_id}.json",
                )
            )
        if corpus_output_path is not None:
            self.write_active_corpus(reports, corpus_output_path)
        return reports

    def ingest_manifest_quarantine(
        self,
        manifest: "LegislationManifest",
        *,
        project_root: Path,
        output_dir: Path,
    ) -> list[IngestionReport]:
        """İnceleme bekleyen manifesti aktif-RAG onayı vermeden toplu işler.

        Metin kalitesi yeterli belgeler yapısal JSON'a dönüştürülür. OCR bekleyen
        belgeler için çıktı üretilmez; raporları OCR kuyruğu olarak korunur.
        """

        project_root = project_root.resolve()
        output_dir = output_dir.resolve()
        reports: list[IngestionReport] = []
        for record in manifest.data:
            if len(record.local_pdfs) != 1:
                continue
            source_path = Path(record.local_pdfs[0])
            if not source_path.is_absolute():
                source_path = project_root / source_path
            document_id = record.document_id or f"legislation-{record.legislation_id}"
            reports.append(
                self.ingest_pdf(
                    source_path,
                    title=record.title,
                    source_status="karantina_insan_dogrulamasi_bekliyor",
                    output_path=output_dir / f"{document_id}.json",
                    document_id=document_id,
                    source_url=record.source_url,
                    document_type=record.document_type,
                    domain=self._enum_value(record.domain),
                    subdomain=record.subdomain,
                    validity_status=self._enum_value(record.validity_status),
                    source_kind="public_legislation",
                )
            )
        return reports

    def write_active_corpus(
        self,
        reports: list[IngestionReport],
        output_path: Path,
    ) -> Path:
        """Onaylı tekil ingestion çıktılarını taşınabilir tek korpusta birleştirir."""

        if not reports:
            raise IngestionApprovalError(
                "Aktif corpus üretilemedi: manifestte onaylı belge bulunmuyor."
            )

        chunks: list[dict[str, object]] = []
        documents: list[dict[str, object]] = []
        seen_chunk_ids: set[str] = set()
        seen_document_ids: set[str] = set()
        for report in reports:
            if not report.approved_for_active_rag or not report.output_file:
                raise IngestionApprovalError(
                    f"{report.document_id or report.title}: aktif ve yazılmış çıktı değil."
                )
            source_path = Path(report.output_file)
            try:
                payload = json.loads(source_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise IngestionError(
                    f"Aktif ingestion çıktısı okunamadı: {source_path}: {exc}"
                ) from exc
            if payload.get("approved_for_active_rag") is not True:
                raise IngestionApprovalError(
                    f"{source_path}: üst seviye aktif-RAG onayı bulunmuyor."
                )
            document_id = str(payload.get("document_id") or "")
            if not document_id or document_id in seen_document_ids:
                raise IngestionApprovalError(
                    f"{source_path}: document_id eksik veya yineleniyor: {document_id!r}"
                )
            seen_document_ids.add(document_id)
            source_sha256 = str(payload.get("source_sha256") or "")
            if not re.fullmatch(r"[0-9a-fA-F]{64}", source_sha256):
                raise IngestionApprovalError(
                    f"{source_path}: geçerli kaynak SHA-256 değeri bulunmuyor."
                )
            if not payload.get("reviewed_by") or not payload.get("reviewed_at"):
                raise IngestionApprovalError(
                    f"{source_path}: insan inceleme izi eksik."
                )

            records = payload.get("data")
            if not isinstance(records, list) or not records:
                raise IngestionApprovalError(
                    f"{source_path}: aktif corpus için parça bulunmuyor."
                )
            for chunk in records:
                if not isinstance(chunk, dict):
                    raise IngestionError(f"{source_path}: nesne olmayan parça bulundu.")
                chunk_id = str(chunk.get("chunk_id") or "")
                if not chunk_id or chunk_id in seen_chunk_ids:
                    raise IngestionApprovalError(
                        f"{source_path}: chunk_id eksik veya yineleniyor: {chunk_id!r}"
                    )
                if (
                    chunk.get("approved_for_active_rag") is not True
                    or chunk.get("validity_status") != "verified"
                    or chunk.get("source_kind") != "public_legislation"
                    or chunk.get("ocr_status")
                    not in {"text_layer_available", "ocr_verified"}
                ):
                    raise IngestionApprovalError(
                        f"{chunk_id}: aktif corpus güvenlik sözleşmesini karşılamıyor."
                    )
                if (
                    chunk.get("document_id") != document_id
                    or chunk.get("source_sha256") != source_sha256
                    or not chunk.get("article")
                    or not chunk.get("context_text")
                    or not isinstance(chunk.get("page"), int)
                    or not isinstance(chunk.get("page_end"), int)
                    or int(chunk["page_end"]) < int(chunk["page"])
                ):
                    raise IngestionApprovalError(
                        f"{chunk_id}: kaynak, yapı veya sayfa izi eksik/tutarsız."
                    )
                seen_chunk_ids.add(chunk_id)
                chunks.append(chunk)
            documents.append(
                {
                    "document_id": document_id,
                    "title": payload.get("dataset_name"),
                    "source_url": payload.get("source_url"),
                    "source_sha256": payload.get("source_sha256"),
                    "chunk_count": len(records),
                    "reviewed_by": payload.get("reviewed_by"),
                    "reviewed_at": payload.get("reviewed_at"),
                }
            )

        output_path = output_path.resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        corpus = {
            "schema_version": "2.0",
            "dataset_name": "active_public_legislation",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "approved_for_active_rag": True,
            "document_count": len(documents),
            "chunk_count": len(chunks),
            "documents": documents,
            "data": chunks,
        }
        output_path.write_text(
            json.dumps(corpus, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return output_path

    def _ingest_pdf(
        self,
        path: Path,
        *,
        title: str,
        source_status: str,
        output_path: Path,
        allow_low_quality: bool,
        document_id: str | None,
        source_url: str | None,
        document_type: str,
        domain: str,
        subdomain: str,
        validity_status: str,
        approved_for_active_rag: bool,
        reviewed_by: str | None,
        review_notes: str | None,
        reviewed_at: str | None,
        source_kind: str,
        expected_source_sha256: str | None,
    ) -> IngestionReport:
        resolved_path = path.resolve()
        source_sha256 = sha256(resolved_path.read_bytes()).hexdigest()
        if (
            expected_source_sha256
            and source_sha256.lower() != expected_source_sha256.lower()
        ):
            raise IngestionApprovalError(
                "Kaynak PDF SHA-256 değeri manifestten farklı; onay geçersizleşti."
            )
        normalized_document_id = self._normalize_document_id(document_id)
        page_texts = self._read_pages(resolved_path)
        quality = assess_text_layer(page_texts)
        activation_blockers = self._activation_blockers(
            document_id=normalized_document_id,
            domain=domain,
            validity_status=validity_status,
            reviewed_by=reviewed_by,
            requires_ocr=quality.requires_ocr,
        )
        if approved_for_active_rag and activation_blockers:
            raise IngestionApprovalError(
                "Kaynak aktif RAG için onaylanamaz: "
                + " ".join(activation_blockers)
            )

        if quality.requires_ocr and not allow_low_quality:
            return IngestionReport(
                document_id=normalized_document_id,
                source_file=str(resolved_path),
                title=title,
                source_status=source_status,
                quality=quality,
                chunk_count=0,
                approved_for_active_rag=False,
                activation_blockers=activation_blockers,
            )

        # allow_low_quality yalnızca karantina/inceleme çıktısı üretir. Bu bayrak
        # hiçbir koşulda aktif-RAG güvenlik kapısını aşamaz.
        effective_approval = approved_for_active_rag and not quality.requires_ocr
        ocr_status = (
            "ocr_required_unverified"
            if quality.requires_ocr
            else "text_layer_available"
        )
        chunks = self.chunker.chunk_pages(
            page_texts,
            title=title,
            source=str(resolved_path),
            source_status=source_status,
            document_id=normalized_document_id,
            source_url=source_url,
            source_sha256=source_sha256,
            source_kind=source_kind,
            document_type=document_type,
            domain=domain,
            subdomain=subdomain,
            validity_status=validity_status,
            approved_for_active_rag=effective_approval,
            ocr_status=ocr_status,
        )
        output_path = output_path.resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema_version": "2.0",
            "dataset_name": title,
            "document_id": normalized_document_id,
            "source_file": str(resolved_path),
            "source_url": source_url,
            "source_sha256": source_sha256,
            "source_kind": source_kind,
            "source_status": source_status,
            "document_type": document_type,
            "domain": domain,
            "subdomain": subdomain,
            "validity_status": validity_status,
            "approved_for_active_rag": effective_approval,
            "reviewed_by": reviewed_by,
            "reviewed_at": reviewed_at,
            "review_notes": review_notes,
            "activation_blockers": activation_blockers,
            "quality": quality.model_dump(mode="json"),
            "data": [chunk.model_dump(mode="json") for chunk in chunks],
        }
        output_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return IngestionReport(
            document_id=normalized_document_id,
            source_file=str(resolved_path),
            title=title,
            source_status=source_status,
            quality=quality,
            chunk_count=len(chunks),
            output_file=str(output_path),
            approved_for_active_rag=effective_approval,
            activation_blockers=activation_blockers,
        )

    @staticmethod
    def _enum_value(value: object) -> str:
        raw = getattr(value, "value", value)
        return str(raw)

    @classmethod
    def _normalize_document_id(cls, document_id: str | None) -> str | None:
        if document_id is None:
            return None
        normalized = document_id.strip()
        if not cls.DOCUMENT_ID_PATTERN.fullmatch(normalized):
            raise IngestionError(
                "document_id 2-120 karakter olmalı ve yalnızca harf, rakam, "
                "nokta, alt çizgi veya tire içermelidir."
            )
        return normalized

    @staticmethod
    def _activation_blockers(
        *,
        document_id: str | None,
        domain: str,
        validity_status: str,
        reviewed_by: str | None,
        requires_ocr: bool,
    ) -> list[str]:
        blockers: list[str] = []
        if not document_id:
            blockers.append("Kararlı document_id bulunmuyor.")
        if not domain.strip() or domain == "unknown":
            blockers.append("İnsan tarafından doğrulanmış kapsam/alan bulunmuyor.")
        if validity_status != "verified":
            blockers.append("Yürürlük durumu doğrulanmamış.")
        if not reviewed_by or not reviewed_by.strip():
            blockers.append("İnsan doğrulayıcı bilgisi bulunmuyor.")
        if requires_ocr:
            blockers.append("Metin katmanı yetersiz; doğrulanmış OCR gerekli.")
        return blockers

    @staticmethod
    def _read_pages(path: Path) -> list[str]:
        try:
            import pymupdf

            document = pymupdf.open(path)
            try:
                return [page.get_text("text") for page in document]
            finally:
                document.close()
        except ImportError:
            from pypdf import PdfReader

            reader = PdfReader(str(path))
            return [(page.extract_text() or "") for page in reader.pages]
