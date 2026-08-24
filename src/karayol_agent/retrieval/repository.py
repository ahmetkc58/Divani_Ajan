from __future__ import annotations

import json
from collections import Counter
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

from pydantic import ValidationError

from karayol_agent.schemas import LegislationChunk

from .corpus import CorpusBinding, build_corpus_binding


class RepositoryApprovalError(ValueError):
    """Aktif arama korpusu güvenlik sözleşmesini karşılamadığında oluşur."""


class LegislationRepository:
    VERIFIED_TEXT_STATUSES = {"text_layer_available", "ocr_verified"}
    ACTIVE_PUBLIC_DOMAINS = {
        "official_writing",
        "general_application",
        "kgm_infrastructure",
        "road_transport",
    }

    def __init__(self, data_path: Path, *, trusted_synthetic: bool = False) -> None:
        self.data_path = data_path
        self.trusted_synthetic = trusted_synthetic

    def load(self) -> list[LegislationChunk]:
        chunks, _ = self.load_with_binding()
        return chunks

    def load_with_binding(self) -> tuple[list[LegislationChunk], CorpusBinding]:
        """Load records and return their deterministic, exact corpus identity."""

        payload = json.loads(self.data_path.read_text(encoding="utf-8"))
        if self.trusted_synthetic:
            records = payload.get("data") if isinstance(payload, Mapping) else payload
        else:
            records = self.validate_active_corpus_envelope(payload)
        if not isinstance(records, list):
            raise RepositoryApprovalError("Mevzuat veri kümesi bir data listesi içermeli.")
        try:
            chunks = [LegislationChunk.model_validate(record) for record in records]
        except ValidationError as exc:
            raise RepositoryApprovalError(
                f"Mevzuat chunk şeması doğrulanamadı: {exc}"
            ) from exc
        if self.trusted_synthetic:
            synthetic_chunks = self._load_trusted_synthetic(chunks)
            return synthetic_chunks, build_corpus_binding(synthetic_chunks)

        violations: list[str] = []
        for chunk in chunks:
            blockers = self.public_chunk_blockers(chunk)
            if blockers:
                violations.append(f"{chunk.chunk_id}: {', '.join(blockers)}")
        if violations:
            preview = "; ".join(violations[:5])
            remaining = len(violations) - 5
            suffix = f"; ayrıca {remaining} kayıt" if remaining > 0 else ""
            raise RepositoryApprovalError(
                "Aktif kamu mevzuatı korpusu doğrulanamadı: " + preview + suffix
            )
        return chunks, build_corpus_binding(chunks)

    @classmethod
    def validate_active_corpus_envelope(cls, payload: object) -> list[object]:
        """Validate the human-reviewed schema-2 active-public-corpus envelope."""

        if not isinstance(payload, Mapping):
            raise RepositoryApprovalError(
                "Aktif kamu mevzuatı çıplak bir kayıt listesi olamaz; "
                "schema_version=2.0 insan-onay zarfı zorunludur."
            )
        if payload.get("schema_version") != "2.0":
            raise RepositoryApprovalError(
                "Aktif kamu mevzuatı schema_version=2.0 olmalıdır."
            )
        if payload.get("dataset_name") != "active_public_legislation":
            raise RepositoryApprovalError(
                "Aktif kamu mevzuatı dataset_name=active_public_legislation olmalıdır."
            )
        cls._require_aware_iso_timestamp(
            payload.get("generated_at"),
            field_name="generated_at",
        )
        if payload.get("approved_for_active_rag") is not True:
            raise RepositoryApprovalError(
                "Aktif kamu mevzuatı üst seviye approved_for_active_rag=true "
                "onayı taşımıyor."
            )

        records = payload.get("data")
        documents = payload.get("documents")
        if not isinstance(records, list) or not isinstance(documents, list):
            raise RepositoryApprovalError(
                "Aktif kamu mevzuatı data ve documents listelerini içermelidir."
            )
        document_count = payload.get("document_count")
        chunk_count = payload.get("chunk_count")
        if type(document_count) is not int or document_count != len(documents):
            raise RepositoryApprovalError(
                "Aktif corpus document_count değeri documents listesiyle eşleşmiyor."
            )
        if type(chunk_count) is not int or chunk_count != len(records):
            raise RepositoryApprovalError(
                "Aktif corpus chunk_count değeri data listesiyle eşleşmiyor."
            )
        if not records or not documents:
            raise RepositoryApprovalError("Aktif kamu mevzuatı korpusu boş olamaz.")

        document_by_id: dict[str, Mapping[str, object]] = {}
        for position, document in enumerate(documents):
            if not isinstance(document, Mapping):
                raise RepositoryApprovalError(
                    f"documents[{position}] bir nesne olmalıdır."
                )
            document_id = document.get("document_id")
            if not isinstance(document_id, str) or not document_id.strip():
                raise RepositoryApprovalError(
                    f"documents[{position}] document_id taşımıyor."
                )
            if document_id in document_by_id:
                raise RepositoryApprovalError(
                    f"Aktif corpus yinelenen document_id içeriyor: {document_id}."
                )
            source_sha256 = document.get("source_sha256")
            if not isinstance(source_sha256, str) or not cls._is_sha256(source_sha256):
                raise RepositoryApprovalError(
                    f"{document_id}: belge zarfındaki source_sha256 geçersiz."
                )
            source_url = document.get("source_url")
            if not cls._is_http_url(source_url):
                raise RepositoryApprovalError(
                    f"{document_id}: belge zarfındaki source_url geçersiz."
                )
            reviewed_by = document.get("reviewed_by")
            reviewed_at = document.get("reviewed_at")
            if (
                not isinstance(reviewed_by, str)
                or not reviewed_by.strip()
                or not isinstance(reviewed_at, str)
                or not reviewed_at.strip()
            ):
                raise RepositoryApprovalError(
                    f"{document_id}: reviewed_by/reviewed_at insan inceleme izi eksik."
                )
            cls._require_aware_iso_timestamp(
                reviewed_at,
                field_name=f"{document_id}.reviewed_at",
            )
            declared_chunk_count = document.get("chunk_count")
            if type(declared_chunk_count) is not int or declared_chunk_count < 1:
                raise RepositoryApprovalError(
                    f"{document_id}: belge chunk_count değeri geçersiz."
                )
            document_by_id[document_id] = document

        observed_document_counts: Counter[str] = Counter()
        seen_chunk_ids: set[str] = set()
        for position, record in enumerate(records):
            if not isinstance(record, Mapping):
                raise RepositoryApprovalError(f"data[{position}] bir nesne olmalıdır.")
            chunk_id = record.get("chunk_id")
            if not isinstance(chunk_id, str) or not chunk_id.strip():
                raise RepositoryApprovalError(f"data[{position}] chunk_id taşımıyor.")
            if chunk_id in seen_chunk_ids:
                raise RepositoryApprovalError(
                    f"Aktif corpus yinelenen chunk_id içeriyor: {chunk_id}."
                )
            seen_chunk_ids.add(chunk_id)
            document_id = record.get("document_id")
            document = document_by_id.get(str(document_id))
            if document is None or document_id != document.get("document_id"):
                raise RepositoryApprovalError(
                    f"{chunk_id}: chunk document_id belge zarfıyla eşleşmiyor."
                )
            if record.get("source_sha256") != document.get("source_sha256"):
                raise RepositoryApprovalError(
                    f"{chunk_id}: chunk source_sha256 belge zarfıyla eşleşmiyor."
                )
            if record.get("source_url") != document.get("source_url"):
                raise RepositoryApprovalError(
                    f"{chunk_id}: chunk source_url belge zarfıyla eşleşmiyor."
                )
            observed_document_counts[str(document_id)] += 1

        for document_id, document in document_by_id.items():
            if observed_document_counts[document_id] != document["chunk_count"]:
                raise RepositoryApprovalError(
                    f"{document_id}: belge chunk_count değeri gerçek parçalarla eşleşmiyor."
                )
        return records

    @classmethod
    def _validate_active_corpus_envelope(cls, payload: object) -> list[object]:
        """Backward-compatible alias for the public envelope validator."""

        return cls.validate_active_corpus_envelope(payload)

    @staticmethod
    def _require_aware_iso_timestamp(value: object, *, field_name: str) -> datetime:
        if not isinstance(value, str) or not value.strip():
            raise RepositoryApprovalError(f"{field_name} ISO-8601 zaman damgası eksik.")
        normalized = value.strip().replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(normalized)
        except ValueError as exc:
            raise RepositoryApprovalError(
                f"{field_name} geçerli bir ISO-8601 zaman damgası değil."
            ) from exc
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise RepositoryApprovalError(
                f"{field_name} timezone-aware bir ISO-8601 zaman damgası olmalıdır."
            )
        return parsed

    @staticmethod
    def _load_trusted_synthetic(
        chunks: list[LegislationChunk],
    ) -> list[LegislationChunk]:
        result: list[LegislationChunk] = []
        for chunk in chunks:
            if chunk.source_kind not in {"unknown", "synthetic"}:
                raise RepositoryApprovalError(
                    f"{chunk.chunk_id}: trusted_synthetic modunda kamu kaynağı yüklenemez."
                )
            if chunk.status != "sentetik_demo_kurali":
                raise RepositoryApprovalError(
                    f"{chunk.chunk_id}: kayıt açıkça sentetik demo kuralı değil."
                )
            result.append(chunk.model_copy(update={"source_kind": "synthetic"}))
        return result

    @classmethod
    def public_chunk_blockers(cls, chunk: LegislationChunk) -> list[str]:
        """Return every fail-closed blocker for an active public chunk."""

        blockers: list[str] = []
        if chunk.source_kind != "public_legislation":
            blockers.append("source_kind_public_legislation_degil")
        if not chunk.approved_for_active_rag:
            blockers.append("aktif_rag_onayi_yok")
        if chunk.validity_status != "verified":
            blockers.append("yururluk_dogrulanmamis")
        if chunk.ocr_status not in cls.VERIFIED_TEXT_STATUSES:
            blockers.append("metin_veya_ocr_dogrulanmamis")
        if not chunk.document_id:
            blockers.append("document_id_yok")
        required_text_fields = {
            "title": chunk.title,
            "section": chunk.section,
            "article": chunk.article,
            "text": chunk.text,
            "source": chunk.source,
            "context_text": chunk.context_text,
        }
        blockers.extend(
            f"{field_name}_yok"
            for field_name, value in required_text_fields.items()
            if not isinstance(value, str) or not value.strip()
        )
        if not cls._is_http_url(chunk.source_url):
            blockers.append("source_url_gecersiz")
        if not cls._is_sha256(chunk.source_sha256):
            blockers.append("source_sha256_gecersiz")
        if chunk.domain not in cls.ACTIVE_PUBLIC_DOMAINS:
            blockers.append("domain_aktif_proje_kapsaminda_degil")
        if (
            chunk.page is None
            or chunk.page_end is None
            or chunk.page_end < chunk.page
        ):
            blockers.append("sayfa_kaynagi_gecersiz")
        return blockers

    @classmethod
    def _public_chunk_blockers(cls, chunk: LegislationChunk) -> list[str]:
        """Backward-compatible alias for callers predating the public contract."""

        return cls.public_chunk_blockers(chunk)

    @staticmethod
    def _is_sha256(value: str | None) -> bool:
        return bool(
            value
            and len(value) == 64
            and all(character in "0123456789abcdefABCDEF" for character in value)
        )

    @staticmethod
    def _is_http_url(value: object) -> bool:
        if not isinstance(value, str) or not value.strip():
            return False
        parsed = urlparse(value.strip())
        return parsed.scheme in {"http", "https"} and bool(parsed.netloc)
