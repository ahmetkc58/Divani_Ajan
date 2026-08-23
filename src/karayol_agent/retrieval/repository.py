from __future__ import annotations

import json
from pathlib import Path

from pydantic import ValidationError

from karayol_agent.schemas import LegislationChunk


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
        payload = json.loads(self.data_path.read_text(encoding="utf-8"))
        records = payload["data"] if isinstance(payload, dict) else payload
        if not isinstance(records, list):
            raise RepositoryApprovalError("Mevzuat veri kümesi bir data listesi içermeli.")
        try:
            chunks = [LegislationChunk.model_validate(record) for record in records]
        except ValidationError as exc:
            raise RepositoryApprovalError(
                f"Mevzuat chunk şeması doğrulanamadı: {exc}"
            ) from exc
        if self.trusted_synthetic:
            return self._load_trusted_synthetic(chunks)

        violations: list[str] = []
        for chunk in chunks:
            blockers = self._public_chunk_blockers(chunk)
            if blockers:
                violations.append(f"{chunk.chunk_id}: {', '.join(blockers)}")
        if violations:
            preview = "; ".join(violations[:5])
            remaining = len(violations) - 5
            suffix = f"; ayrıca {remaining} kayıt" if remaining > 0 else ""
            raise RepositoryApprovalError(
                "Aktif kamu mevzuatı korpusu doğrulanamadı: " + preview + suffix
            )
        return chunks

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
    def _public_chunk_blockers(cls, chunk: LegislationChunk) -> list[str]:
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

    @staticmethod
    def _is_sha256(value: str | None) -> bool:
        return bool(
            value
            and len(value) == 64
            and all(character in "0123456789abcdefABCDEF" for character in value)
        )
