"""Trust contracts shared by corpus loading and vector indexing.

The competition snapshot is deliberately *not* an active-public-legislation
approval.  It is a reproducible view of the files bundled with this project,
whose current legal validity has not been checked.
"""

from __future__ import annotations

from enum import StrEnum
from pathlib import PurePosixPath, PureWindowsPath
from urllib.parse import urlparse

from karayol_agent.schemas import LegislationChunk


class CorpusMode(StrEnum):
    VERIFIED_PUBLIC = "verified_public"
    COMPETITION_SNAPSHOT = "competition_snapshot"
    TRUSTED_SYNTHETIC = "trusted_synthetic"


COMPETITION_SNAPSHOT_DATASET_NAME = "competition_legislation_snapshot"
COMPETITION_SNAPSHOT_STATUS = "competition_snapshot_not_currentness_verified"
COMPETITION_SNAPSHOT_NOTICE = (
    "Bu sonuç yalnızca projeyle birlikte sabitlenmiş yarışma veri kümesine "
    "dayanır; mevzuatın güncelliği/yürürlüğü doğrulanmamıştır ve güncel hukuki "
    "görüş değildir."
)
COMPETITION_SNAPSHOT_TEXT_STATUSES = {
    "text_layer_available",
    "ocr_candidate_unverified",
}
ACTIVE_PROJECT_DOMAINS = {
    "official_writing",
    "general_application",
    "kgm_infrastructure",
    "road_transport",
}


def competition_snapshot_chunk_blockers(chunk: LegislationChunk) -> list[str]:
    """Return blockers for a non-currentness-guaranteed snapshot chunk.

    These rules intentionally require the public-law approval flags to remain
    false/unverified.  A snapshot record that masquerades as verified current
    law must fail closed.
    """

    blockers: list[str] = []
    if chunk.source_kind != CorpusMode.COMPETITION_SNAPSHOT.value:
        blockers.append("source_kind_competition_snapshot_degil")
    if chunk.approved_for_active_rag:
        blockers.append("public_active_rag_onayi_snapshotta_yasak")
    if chunk.validity_status != "needs_verification":
        blockers.append("snapshot_yururluk_durumu_needs_verification_degil")
    if chunk.status != COMPETITION_SNAPSHOT_STATUS:
        blockers.append("snapshot_durum_etiketi_gecersiz")
    if chunk.ocr_status not in COMPETITION_SNAPSHOT_TEXT_STATUSES:
        blockers.append("snapshot_metin_kokeni_gecersiz")
    if not chunk.document_id:
        blockers.append("document_id_yok")

    required_text_fields = {
        "title": chunk.title,
        "section": chunk.section,
        "text": chunk.text,
        "source": chunk.source,
        "context_text": chunk.context_text,
    }
    blockers.extend(
        f"{field_name}_yok"
        for field_name, value in required_text_fields.items()
        if not isinstance(value, str) or not value.strip()
    )

    if isinstance(chunk.source, str) and chunk.source.strip():
        if not is_safe_project_relative_path(chunk.source):
            blockers.append("source_path_proje_goreli_degil")
    if chunk.source_url is not None and not is_http_url(chunk.source_url):
        blockers.append("source_url_gecersiz")
    if not is_sha256(chunk.source_sha256):
        blockers.append("source_sha256_gecersiz")
    if chunk.domain not in ACTIVE_PROJECT_DOMAINS:
        blockers.append("domain_aktif_proje_kapsaminda_degil")
    if chunk.page is None or chunk.page_end is None or chunk.page_end < chunk.page:
        blockers.append("sayfa_kaynagi_gecersiz")
    return blockers


def is_safe_project_relative_path(value: object) -> bool:
    """Accept portable project-relative paths and reject traversal/absolutes."""

    if not isinstance(value, str) or not value.strip():
        return False
    normalized = value.strip().replace("\\", "/")
    posix = PurePosixPath(normalized)
    windows = PureWindowsPath(value.strip())
    if posix.is_absolute() or windows.is_absolute() or bool(windows.drive):
        return False
    return ".." not in posix.parts and "." not in posix.parts


def is_sha256(value: object) -> bool:
    return bool(
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdefABCDEF" for character in value)
    )


def is_http_url(value: object) -> bool:
    if not isinstance(value, str) or not value.strip():
        return False
    parsed = urlparse(value.strip())
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


__all__ = [
    "ACTIVE_PROJECT_DOMAINS",
    "COMPETITION_SNAPSHOT_DATASET_NAME",
    "COMPETITION_SNAPSHOT_NOTICE",
    "COMPETITION_SNAPSHOT_STATUS",
    "COMPETITION_SNAPSHOT_TEXT_STATUSES",
    "CorpusMode",
    "competition_snapshot_chunk_blockers",
    "is_http_url",
    "is_safe_project_relative_path",
    "is_sha256",
]
