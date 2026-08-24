"""Build an explicitly non-current competition corpus from reviewed artifacts."""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path

from pydantic import ValidationError

from karayol_agent.retrieval.contracts import (
    COMPETITION_SNAPSHOT_DATASET_NAME,
    COMPETITION_SNAPSHOT_NOTICE,
    COMPETITION_SNAPSHOT_STATUS,
    CorpusMode,
    competition_snapshot_chunk_blockers,
    is_sha256,
)
from karayol_agent.retrieval.repository import (
    LegislationRepository,
    RepositoryApprovalError,
)
from karayol_agent.schemas import LegislationChunk


class SnapshotBuildError(ValueError):
    """A source artifact cannot form the bounded competition snapshot."""


class CompetitionSnapshotCorpusBuilder:
    """Combine per-document chunk files without granting public-law approval."""

    def __init__(self, *, project_root: Path) -> None:
        self.project_root = project_root.resolve()

    def build(
        self,
        document_outputs: Iterable[Path],
        output_path: Path,
        *,
        acknowledge_not_current: bool = False,
    ) -> Path:
        if acknowledge_not_current is not True:
            raise SnapshotBuildError(
                "Snapshot üretimi, mevzuat güncelliğinin doğrulanmadığının açıkça "
                "kabul edilmesini gerektirir."
            )

        input_paths = [path.resolve() for path in document_outputs]
        if not input_paths:
            raise SnapshotBuildError("Snapshot için belge çıktısı bulunmuyor.")
        if len(set(input_paths)) != len(input_paths):
            raise SnapshotBuildError("Snapshot girdi listesinde yinelenen dosya var.")

        documents: list[dict[str, object]] = []
        chunks: list[dict[str, object]] = []
        for input_path in input_paths:
            payload = self._read_document_output(input_path)
            document, document_chunks = self._normalize_document(payload, input_path)
            documents.append(document)
            chunks.extend(document_chunks)

        documents.sort(key=lambda item: str(item["document_id"]))
        chunks.sort(key=lambda item: str(item["chunk_id"]))
        source_chunk_count = sum(
            int(document["source_chunk_count"]) for document in documents
        )
        consolidated_count = sum(
            int(document["exact_duplicate_rows_consolidated"])
            for document in documents
        )
        corpus = {
            "schema_version": "2.0",
            "dataset_name": COMPETITION_SNAPSHOT_DATASET_NAME,
            "corpus_mode": CorpusMode.COMPETITION_SNAPSHOT.value,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "currentness_verified": False,
            "legal_reliance_allowed": False,
            "approved_for_competition_use": True,
            "usage_notice": COMPETITION_SNAPSHOT_NOTICE,
            "document_count": len(documents),
            "source_chunk_count": source_chunk_count,
            "chunk_count": len(chunks),
            "exact_duplicate_rows_consolidated": consolidated_count,
            "documents": documents,
            "data": chunks,
        }
        try:
            LegislationRepository.validate_competition_snapshot_envelope(corpus)
        except (RepositoryApprovalError, ValidationError) as exc:
            raise SnapshotBuildError(
                f"Snapshot korpusu doğrulanamadı: {exc}"
            ) from exc

        resolved_output = output_path.resolve()
        self._require_inside_project(resolved_output, field_name="output_path")
        if resolved_output in input_paths:
            raise SnapshotBuildError("Snapshot çıktısı girdi dosyasının üzerine yazılamaz.")
        resolved_output.parent.mkdir(parents=True, exist_ok=True)
        resolved_output.write_text(
            json.dumps(corpus, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return resolved_output

    @staticmethod
    def _read_document_output(path: Path) -> Mapping[str, object]:
        if not path.is_file():
            raise SnapshotBuildError(f"Belge chunk çıktısı bulunamadı: {path}")
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise SnapshotBuildError(
                f"Belge chunk çıktısı okunamadı: {path}: {exc}"
            ) from exc
        if not isinstance(payload, Mapping):
            raise SnapshotBuildError(f"Belge chunk çıktısı nesne olmalıdır: {path}")
        return payload

    def _normalize_document(
        self,
        payload: Mapping[str, object],
        input_path: Path,
    ) -> tuple[dict[str, object], list[dict[str, object]]]:
        document_id = self._required_text(payload, "document_id", input_path)
        title = str(payload.get("title") or payload.get("dataset_name") or "").strip()
        if not title:
            raise SnapshotBuildError(f"{document_id}: belge başlığı eksik.")
        if payload.get("approved_for_active_rag") is not False:
            raise SnapshotBuildError(
                f"{document_id}: yalnız approved_for_active_rag=false karantina "
                "çıktısı snapshot'a alınabilir."
            )
        if payload.get("validity_status") != "needs_verification":
            raise SnapshotBuildError(
                f"{document_id}: snapshot girdisi validity_status=needs_verification "
                "taşımalıdır."
            )

        source_file_raw = self._required_text(payload, "source_file", input_path)
        source_file = self._resolve_project_file(source_file_raw, field_name="source_file")
        actual_source_sha256 = self._file_sha256(source_file)
        declared_source_sha256 = payload.get("source_sha256")
        if not is_sha256(declared_source_sha256):
            raise SnapshotBuildError(f"{document_id}: kaynak SHA-256 değeri geçersiz.")
        if str(declared_source_sha256).lower() != actual_source_sha256:
            raise SnapshotBuildError(
                f"{document_id}: kaynak PDF SHA-256 değeri gerçek dosyayla eşleşmiyor."
            )
        source_path = source_file.relative_to(self.project_root).as_posix()
        source_url = payload.get("source_url")

        records = payload.get("data")
        if not isinstance(records, list) or not records:
            raise SnapshotBuildError(f"{document_id}: chunk listesi boş veya geçersiz.")
        text_origin = self._text_origin(payload, records, document_id=document_id)
        derived_text_sha256 = self._derived_text_sha256(
            payload,
            text_origin=text_origin,
            document_id=document_id,
        )

        normalized_chunks: list[dict[str, object]] = []
        for position, record in enumerate(records):
            if not isinstance(record, Mapping):
                raise SnapshotBuildError(
                    f"{document_id}: data[{position}] bir nesne olmalıdır."
                )
            try:
                original = LegislationChunk.model_validate(record)
            except ValidationError as exc:
                raise SnapshotBuildError(
                    f"{document_id}: data[{position}] chunk şeması geçersiz: {exc}"
                ) from exc
            if original.document_id != document_id:
                raise SnapshotBuildError(
                    f"{original.chunk_id}: document_id üst seviye kayıtla eşleşmiyor."
                )
            if original.approved_for_active_rag or original.validity_status != (
                "needs_verification"
            ):
                raise SnapshotBuildError(
                    f"{original.chunk_id}: doğrulanmış/aktif kamu iddiası snapshot'a "
                    "taşınamaz."
                )
            if original.source_kind not in {
                "public_legislation",
                CorpusMode.COMPETITION_SNAPSHOT.value,
            }:
                raise SnapshotBuildError(
                    f"{original.chunk_id}: kaynak türü snapshot girdisi olamaz."
                )
            if original.source_sha256 and (
                original.source_sha256.lower() != actual_source_sha256
            ):
                raise SnapshotBuildError(
                    f"{original.chunk_id}: chunk kaynak SHA-256 değeri belgeyle eşleşmiyor."
                )
            if original.source_url != source_url:
                raise SnapshotBuildError(
                    f"{original.chunk_id}: chunk source_url üst seviye kayıtla eşleşmiyor."
                )

            normalized = original.model_copy(
                update={
                    "title": title,
                    "source": source_path,
                    "source_sha256": actual_source_sha256,
                    "source_kind": CorpusMode.COMPETITION_SNAPSHOT.value,
                    "validity_status": "needs_verification",
                    "approved_for_active_rag": False,
                    "ocr_status": (
                        "ocr_candidate_unverified"
                        if text_origin == "machine_ocr_candidate"
                        else "text_layer_available"
                    ),
                    "status": COMPETITION_SNAPSHOT_STATUS,
                }
            )
            blockers = competition_snapshot_chunk_blockers(normalized)
            if blockers:
                raise SnapshotBuildError(
                    f"{normalized.chunk_id}: snapshot chunk sözleşmesini karşılamıyor: "
                    + ", ".join(blockers)
                    + "."
                )
            normalized_chunks.append(normalized.model_dump(mode="json"))

        source_chunk_count = len(normalized_chunks)
        normalized_chunks = self._consolidate_exact_duplicates(
            normalized_chunks,
            document_id=document_id,
        )
        document = {
            "document_id": document_id,
            "title": title,
            "source_path": source_path,
            "source_url": source_url,
            "source_sha256": actual_source_sha256,
            "source_chunk_count": source_chunk_count,
            "chunk_count": len(normalized_chunks),
            "exact_duplicate_rows_consolidated": (
                source_chunk_count - len(normalized_chunks)
            ),
            "text_origin": text_origin,
            "derived_text_sha256": derived_text_sha256,
        }
        return document, normalized_chunks

    @staticmethod
    def _consolidate_exact_duplicates(
        chunks: list[dict[str, object]],
        *,
        document_id: str,
    ) -> list[dict[str, object]]:
        """Merge exact duplicate rows while preserving their full page span."""

        unique: dict[str, dict[str, object]] = {}
        for chunk in chunks:
            chunk_id = str(chunk["chunk_id"])
            existing = unique.get(chunk_id)
            if existing is None:
                unique[chunk_id] = dict(chunk)
                continue
            if existing.get("document_id") != document_id:
                raise SnapshotBuildError(
                    f"{chunk_id}: farklı belgeler arası chunk_id çakışması."
                )
            existing_evidence = {
                key: value
                for key, value in existing.items()
                if key not in {"page", "page_end"}
            }
            incoming_evidence = {
                key: value
                for key, value in chunk.items()
                if key not in {"page", "page_end"}
            }
            if existing_evidence != incoming_evidence:
                raise SnapshotBuildError(
                    f"{chunk_id}: aynı kimlik farklı kanıt içeriği taşıyor; "
                    "konsolidasyon reddedildi."
                )
            existing["page"] = min(int(existing["page"]), int(chunk["page"]))
            existing["page_end"] = max(
                int(existing["page_end"]), int(chunk["page_end"])
            )
        return list(unique.values())

    def _derived_text_sha256(
        self,
        payload: Mapping[str, object],
        *,
        text_origin: str,
        document_id: str,
    ) -> str | None:
        declared = payload.get("derived_text_sha256")
        artifact = payload.get("derived_text_file")
        if text_origin == "pdf_text_layer":
            if declared is not None or artifact is not None:
                raise SnapshotBuildError(
                    f"{document_id}: PDF metin katmanı OCR türetilmiş metin izi "
                    "taşıyamaz."
                )
            return None
        if not is_sha256(declared):
            raise SnapshotBuildError(
                f"{document_id}: OCR derived_text_sha256 değeri eksik/geçersiz."
            )
        if not isinstance(artifact, str) or not artifact.strip():
            raise SnapshotBuildError(
                f"{document_id}: OCR derived_text_file yolu eksik."
            )
        artifact_path = self._resolve_project_file(
            artifact, field_name=f"{document_id}.derived_text_file"
        )
        actual = self._file_sha256(artifact_path)
        if actual != str(declared).lower():
            raise SnapshotBuildError(
                f"{document_id}: OCR türetilmiş metin SHA-256 değeri eşleşmiyor."
            )
        return actual

    @staticmethod
    def _text_origin(
        payload: Mapping[str, object],
        records: list[object],
        *,
        document_id: str,
    ) -> str:
        declared = payload.get("text_origin")
        if declared in {"pdf_text_layer", "machine_ocr_candidate"}:
            return str(declared)
        statuses = {
            record.get("ocr_status")
            for record in records
            if isinstance(record, Mapping)
        }
        if statuses == {"ocr_candidate_unverified"}:
            return "machine_ocr_candidate"
        if statuses == {"text_layer_available"}:
            return "pdf_text_layer"
        raise SnapshotBuildError(
            f"{document_id}: text_origin eksik veya chunk OCR durumları belirsiz."
        )

    def _resolve_project_file(self, value: str, *, field_name: str) -> Path:
        candidate = Path(value)
        resolved = (
            candidate.resolve()
            if candidate.is_absolute()
            else (self.project_root / candidate).resolve()
        )
        self._require_inside_project(resolved, field_name=field_name)
        if not resolved.is_file():
            raise SnapshotBuildError(f"{field_name} dosyası bulunamadı: {resolved}")
        return resolved

    def _require_inside_project(self, path: Path, *, field_name: str) -> None:
        try:
            path.relative_to(self.project_root)
        except ValueError as exc:
            raise SnapshotBuildError(
                f"{field_name} proje kökü dışına çıkamaz: {path}"
            ) from exc

    @staticmethod
    def _required_text(
        payload: Mapping[str, object], field_name: str, input_path: Path
    ) -> str:
        value = payload.get(field_name)
        if not isinstance(value, str) or not value.strip():
            raise SnapshotBuildError(f"{input_path}: {field_name} eksik.")
        return value.strip()

    @staticmethod
    def _file_sha256(path: Path) -> str:
        digest = sha256()
        with path.open("rb") as source:
            for block in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(block)
        return digest.hexdigest()


__all__ = ["CompetitionSnapshotCorpusBuilder", "SnapshotBuildError"]
