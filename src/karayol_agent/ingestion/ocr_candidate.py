"""Turn pinned OCR review artifacts into page-aware snapshot chunks.

The OCR review script deliberately produces *candidates*, not verified legal
text.  This module preserves that distinction while making the two pinned
official-writing artifacts usable by the competition-snapshot pipeline.

No OCR is performed here.  Candidate text, its OCR report, and the original
PDF are bound together by path, page count, and SHA-256 before any chunk is
returned.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any, Literal

from karayol_agent.ingestion.chunker import LegalStructureChunker
from karayol_agent.ingestion.quality import assess_text_layer
from karayol_agent.retrieval.contracts import (
    COMPETITION_SNAPSHOT_STATUS,
    CorpusMode,
)
from karayol_agent.schemas import LegislationChunk
from karayol_agent.text_utils import normalize_whitespace


COMPETITION_SNAPSHOT_SOURCE_KIND = CorpusMode.COMPETITION_SNAPSHOT.value
OCR_CANDIDATE_STATUS = "ocr_candidate_unverified"


class OcrCandidateIngestionError(ValueError):
    """The OCR candidate cannot be bound safely to its source PDF."""


OcrChunkingStrategy = Literal[
    "official_writing_guide",
    "official_writing_regulation",
]


@dataclass(frozen=True, slots=True)
class OcrCandidateSpec:
    """Auditable inputs for one already-produced OCR candidate."""

    document_id: str
    title: str
    document_type: str
    domain: str
    subdomain: str
    source_pdf: str
    candidate_text: str
    ocr_report: str
    source_sha256: str
    candidate_sha256: str
    page_count: int
    strategy: OcrChunkingStrategy
    source_url: str | None = None


@dataclass(frozen=True, slots=True)
class ParsedOcrCandidate:
    document_id: str
    source_pdf: str
    pages: tuple[str, ...]


OFFICIAL_WRITING_GUIDE_SPEC = OcrCandidateSpec(
    document_id="official-writing-guide",
    title=(
        "Resmî Yazışmalarda Uygulanacak Usul ve Esaslar Hakkında "
        "Yönetmelik Kılavuzu"
    ),
    document_type="kilavuz",
    domain="official_writing",
    subdomain="formal_correspondence",
    source_pdf="mevzuat-kılavuz.pdf",
    candidate_text=(
        "data/processed/ocr_review/"
        "official-writing-guide.ocr-candidate.txt"
    ),
    ocr_report="reports/ocr_review_2026-08-24.json",
    source_sha256=(
        "0716b0e39b62fadf8d9ded7b20f6be3660199eea397f417e127b81775ca129e1"
    ),
    candidate_sha256=(
        "db6f4a622b83bbc17ae0216474c4a4e844120bf7655c458d21919ae884ffb723"
    ),
    page_count=26,
    strategy="official_writing_guide",
)


OFFICIAL_WRITING_REGULATION_SPEC = OcrCandidateSpec(
    document_id="official-writing-regulation",
    title="Resmî Yazışmalarda Uygulanacak Usul ve Esaslar Hakkında Yönetmelik",
    document_type="yonetmelik",
    domain="official_writing",
    subdomain="formal_correspondence",
    source_pdf="mevzuat-1.pdf",
    candidate_text=(
        "data/processed/ocr_review/full_ocr/"
        "official-writing-regulation.ocr-candidate.txt"
    ),
    ocr_report="reports/ocr_review_regulation_full_2026-08-24.json",
    source_sha256=(
        "aabd2d739037fff061f348c4a1f239afac5e1a58241fe041f15728775d6ccab9"
    ),
    candidate_sha256=(
        "79e089f90b46e0d91398a21065e0521a0ab2c382fb33ff06b1bbe9061d9f3c50"
    ),
    page_count=49,
    strategy="official_writing_regulation",
)


CORE_OCR_CANDIDATE_SPECS = (
    OFFICIAL_WRITING_GUIDE_SPEC,
    OFFICIAL_WRITING_REGULATION_SPEC,
)


_PAGE_MARKER = re.compile(
    r"(?m)^[ \t]*===== SAYFA[ \t]+(?P<page>\d+)[ \t]+=====[ \t]*$"
)
_DOCUMENT_HEADER = re.compile(r"(?m)^Belge kimliği:[ \t]*(?P<value>[^\n]+)$")
_SOURCE_HEADER = re.compile(r"(?m)^Kaynak PDF:[ \t]*(?P<value>[^\n]+)$")
_INVERTED_ARTICLE_MARKER = re.compile(
    r"(?m)^(?P<number>\d+[A-ZÇĞİÖŞÜ]?)[ \t]*[-–—][ \t]*"
    r"(?P<lead>\(\d+\)[^\n]*)\n[ \t]*MADDE[ \t]*$"
)
_EXAMPLE_HEADING = re.compile(
    r"(?mi)^[ \t]*ÖRNEK[ \t]+(?P<number>\d+(?:/[A-ZÇĞİÖŞÜ])?)[ \t]*$"
)
_SHA256_PATTERN = re.compile(r"^[0-9a-fA-F]{64}$")


class _OcrLegalStructureChunker(LegalStructureChunker):
    """Legal chunker whose optional article modifier cannot cross a line."""

    ARTICLE_PATTERN = re.compile(
        r"(?i)\b(?P<label>(?:(?:GEÇİCİ|EK)[ \t]+)?MADDE\s+"
        r"(?P<number>\d+[A-ZÇĞİÖŞÜ]?))\s*[-–—]"
    )


_GUIDE_PAGE_STRUCTURE: tuple[tuple[int, int, str, str], ...] = (
    (1, 1, "Ön Bölüm — Kapak", "Kılavuz Ön Bölüm"),
    (2, 2, "Ön Bölüm — Hazırlama Notu", "Kılavuz Ön Bölüm"),
    (3, 4, "Ön Bölüm — İçindekiler", "Kılavuz Ön Bölüm"),
    (5, 6, "Ön Söz", "Kılavuz Ön Bölüm"),
    (7, 8, "Giriş", "Kılavuz Ön Bölüm"),
    (9, 10, "1. Resmî Yazışma Ortamları", "Kılavuz Bölüm 1"),
    (11, 11, "2. Nüsha Sayısı", "Kılavuz Bölüm 2"),
    (12, 12, "3. Belgenin Şekli Özellikleri", "Kılavuz Bölüm 3"),
    (13, 13, "4. Yazı Tipi ve Harf Büyüklüğü", "Kılavuz Bölüm 4"),
    (14, 14, "5. Yazı Alanı", "Kılavuz Bölüm 5"),
    (15, 16, "6. Kurumsal Logo Kullanımı", "Kılavuz Bölüm 6"),
    (17, 22, "7. Başlık", "Kılavuz Bölüm 7"),
    (23, 24, "8. Sayı", "Kılavuz Bölüm 8"),
    (25, 25, "9. Tarih", "Kılavuz Bölüm 9"),
    (26, 26, "10. Konu", "Kılavuz Bölüm 10"),
)


def parse_ocr_candidate_text(
    text: str,
    *,
    expected_document_id: str,
    expected_source_pdf: str,
    expected_page_count: int,
) -> ParsedOcrCandidate:
    """Parse the review-script format without treating its header as content."""

    normalized = text.replace("\r\n", "\n").replace("\r", "\n").lstrip("\ufeff")
    marker_matches = list(_PAGE_MARKER.finditer(normalized))
    marker_mentions = len(re.findall(r"(?m)^.*===== SAYFA.*$", normalized))
    if not marker_matches or marker_mentions != len(marker_matches):
        raise OcrCandidateIngestionError(
            "OCR adayında eksik veya bozuk SAYFA işaretçisi bulundu."
        )

    document_values = [
        match.group("value").strip()
        for match in _DOCUMENT_HEADER.finditer(normalized[: marker_matches[0].start()])
    ]
    source_values = [
        match.group("value").strip()
        for match in _SOURCE_HEADER.finditer(normalized[: marker_matches[0].start()])
    ]
    if document_values != [expected_document_id]:
        raise OcrCandidateIngestionError(
            "OCR adayı belge kimliği beklenen kayıtla eşleşmiyor."
        )
    expected_source = _normalize_portable_path(expected_source_pdf)
    if len(source_values) != 1 or _normalize_portable_path(source_values[0]) != expected_source:
        raise OcrCandidateIngestionError(
            "OCR adayı kaynak PDF başlığı beklenen kayıtla eşleşmiyor."
        )

    page_numbers = [int(match.group("page")) for match in marker_matches]
    expected_numbers = list(range(1, expected_page_count + 1))
    if page_numbers != expected_numbers:
        raise OcrCandidateIngestionError(
            "OCR adayı sayfa işaretçileri 1..N sırasında eksiksiz değil."
        )

    pages: list[str] = []
    for index, marker in enumerate(marker_matches):
        content_start = marker.end()
        content_end = (
            marker_matches[index + 1].start()
            if index + 1 < len(marker_matches)
            else len(normalized)
        )
        content = normalized[content_start:content_end].strip()
        if not content:
            raise OcrCandidateIngestionError(
                f"OCR adayının {page_numbers[index]}. sayfası boş."
            )
        pages.append(content)

    return ParsedOcrCandidate(
        document_id=expected_document_id,
        source_pdf=expected_source,
        pages=tuple(pages),
    )


def build_ocr_candidate_payload(
    project_root: Path,
    spec: OcrCandidateSpec,
    *,
    max_chars: int = 1800,
) -> dict[str, Any]:
    """Validate and chunk one pinned OCR candidate without granting approval."""

    if max_chars < 1:
        raise ValueError("max_chars pozitif olmalıdır.")
    if not _SHA256_PATTERN.fullmatch(spec.source_sha256):
        raise OcrCandidateIngestionError("Beklenen kaynak PDF SHA-256 geçersiz.")
    if not _SHA256_PATTERN.fullmatch(spec.candidate_sha256):
        raise OcrCandidateIngestionError("Beklenen OCR aday SHA-256 geçersiz.")

    root = project_root.resolve()
    source_path, source_file = _resolve_project_path(root, spec.source_pdf)
    candidate_path, derived_text_file = _resolve_project_path(
        root, spec.candidate_text
    )
    report_path, ocr_report_file = _resolve_project_path(root, spec.ocr_report)

    source_digest = _file_sha256(source_path)
    if source_digest != spec.source_sha256.lower():
        raise OcrCandidateIngestionError(
            "Kaynak PDF SHA-256 sabitlenmiş OCR spesifikasyonuyla eşleşmiyor."
        )
    candidate_bytes = candidate_path.read_bytes()
    candidate_digest = sha256(candidate_bytes).hexdigest()
    if candidate_digest != spec.candidate_sha256.lower():
        raise OcrCandidateIngestionError(
            "OCR aday SHA-256 sabitlenmiş spesifikasyonla eşleşmiyor."
        )

    report_document, report = _load_report_document(report_path, spec.document_id)
    _validate_report_binding(
        report=report,
        document=report_document,
        spec=spec,
        source_file=source_file,
        derived_text_file=derived_text_file,
        source_digest=source_digest,
        candidate_digest=candidate_digest,
    )

    try:
        candidate_text = candidate_bytes.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise OcrCandidateIngestionError("OCR adayı UTF-8 olarak okunamadı.") from exc
    parsed = parse_ocr_candidate_text(
        candidate_text,
        expected_document_id=spec.document_id,
        expected_source_pdf=source_file,
        expected_page_count=spec.page_count,
    )
    _validate_report_pages(report_document, parsed.pages)
    if _pdf_page_count(source_path) != spec.page_count:
        raise OcrCandidateIngestionError(
            "Kaynak PDF sayfa sayısı OCR adayıyla eşleşmiyor."
        )

    if spec.strategy == "official_writing_guide":
        chunks = _chunk_guide(
            pages=parsed.pages,
            spec=spec,
            source_file=source_file,
            max_chars=max_chars,
        )
    elif spec.strategy == "official_writing_regulation":
        if report.get("force_ocr_all") is not True:
            raise OcrCandidateIngestionError(
                "Yönetmelik için tam OCR (force_ocr_all=true) raporu zorunludur."
            )
        chunks = _chunk_regulation(
            pages=parsed.pages,
            spec=spec,
            source_file=source_file,
            max_chars=max_chars,
        )
    else:  # pragma: no cover - guarded by the typed spec
        raise OcrCandidateIngestionError(f"Bilinmeyen OCR stratejisi: {spec.strategy}")

    _validate_chunks(chunks, spec=spec, source_file=source_file)
    quality = assess_text_layer(list(parsed.pages))
    if quality.requires_ocr:
        raise OcrCandidateIngestionError(
            "OCR adayının çıkarılmış metin kalitesi asgari eşiği karşılamıyor."
        )

    return {
        "schema_version": "2.0",
        "dataset_name": spec.title,
        "document_id": spec.document_id,
        "source_file": source_file,
        "source_url": spec.source_url,
        "source_sha256": source_digest,
        "source_kind": COMPETITION_SNAPSHOT_SOURCE_KIND,
        "source_status": COMPETITION_SNAPSHOT_STATUS,
        "document_type": spec.document_type,
        "domain": spec.domain,
        "subdomain": spec.subdomain,
        "validity_status": "needs_verification",
        "approved_for_active_rag": False,
        "text_origin": "machine_ocr_candidate",
        "ocr_status": OCR_CANDIDATE_STATUS,
        "derived_text_file": derived_text_file,
        "derived_text_sha256": candidate_digest,
        "ocr_report_file": ocr_report_file,
        "ocr_report_sha256": _file_sha256(report_path),
        "page_count": len(parsed.pages),
        "quality": quality.model_dump(mode="json"),
        "activation_blockers": [
            "competition_snapshot_currentness_not_verified",
            "ocr_candidate_unverified",
        ],
        "data": [chunk.model_dump(mode="json") for chunk in chunks],
    }


def build_core_ocr_candidate_payloads(
    project_root: Path,
    *,
    max_chars: int = 1800,
) -> list[dict[str, Any]]:
    """Build both pinned official-writing OCR document payloads."""

    return [
        build_ocr_candidate_payload(project_root, spec, max_chars=max_chars)
        for spec in CORE_OCR_CANDIDATE_SPECS
    ]


def _chunk_regulation(
    *,
    pages: Sequence[str],
    spec: OcrCandidateSpec,
    source_file: str,
    max_chars: int,
) -> list[LegislationChunk]:
    if len(pages) != 49:
        raise OcrCandidateIngestionError(
            "Yönetmelik OCR stratejisi tam 49 sayfalık sabit adayı bekliyor."
        )

    repaired_core_pages = [_repair_inverted_article_markers(page) for page in pages[:16]]
    legal_chunker = _OcrLegalStructureChunker(max_chars=max_chars)
    legal_chunks = legal_chunker.chunk_pages(
        repaired_core_pages,
        title=spec.title,
        source=source_file,
        source_status=COMPETITION_SNAPSHOT_STATUS,
        document_id=spec.document_id,
        source_url=spec.source_url,
        source_sha256=spec.source_sha256.lower(),
        source_kind=COMPETITION_SNAPSHOT_SOURCE_KIND,
        document_type=spec.document_type,
        domain=spec.domain,
        subdomain=spec.subdomain,
        validity_status="needs_verification",
        approved_for_active_rag=False,
        ocr_status=OCR_CANDIDATE_STATUS,
    )
    expected_articles = [*(f"Madde {number}" for number in range(1, 38))]
    expected_articles.extend(["Geçici Madde 1", "Madde 38", "Madde 39"])
    observed_articles = list(dict.fromkeys(chunk.article for chunk in legal_chunks))
    if observed_articles != expected_articles:
        raise OcrCandidateIngestionError(
            "Yönetmelik madde dizisi OCR sonrasında eksik veya bozuk: "
            f"{observed_articles!r}"
        )
    if any((chunk.page_end or 0) > 16 for chunk in legal_chunks):
        raise OcrCandidateIngestionError(
            "Yönetmelik örnek sayfaları son kanun maddesine karıştı."
        )

    supplement_chunks = _chunk_example_pages(
        pages=pages[16:],
        page_offset=16,
        spec=spec,
        source_file=source_file,
        max_chars=max_chars,
    )
    return [*legal_chunks, *supplement_chunks]


def _repair_inverted_article_markers(page: str) -> str:
    """Repair the two observed EasyOCR ordering inversions, conservatively."""

    return _INVERTED_ARTICLE_MARKER.sub(
        lambda match: (
            f"MADDE {match.group('number')}- {match.group('lead').strip()}"
        ),
        page,
    )


def _chunk_example_pages(
    *,
    pages: Sequence[str],
    page_offset: int,
    spec: OcrCandidateSpec,
    source_file: str,
    max_chars: int,
) -> list[LegislationChunk]:
    chunks: list[LegislationChunk] = []
    current_article: str | None = None
    for local_index, page_text in enumerate(pages, start=1):
        page_number = page_offset + local_index
        matches = list(_EXAMPLE_HEADING.finditer(page_text))
        segments: list[tuple[str, str]] = []
        if not matches:
            segments.append((current_article or f"Ek Sayfası {page_number}", page_text))
        else:
            prefix = page_text[: matches[0].start()]
            if normalize_whitespace(prefix):
                segments.append(
                    (current_article or f"Ek Sayfası {page_number}", prefix)
                )
            for index, match in enumerate(matches):
                end = matches[index + 1].start() if index + 1 < len(matches) else len(page_text)
                current_article = f"Örnek {match.group('number').upper()}"
                segments.append((current_article, page_text[match.start() : end]))

        for article, segment in segments:
            chunks.extend(
                _page_chunks(
                    text=segment,
                    page=page_number,
                    section="Ekler ve Örnekler",
                    article=article,
                    spec=spec,
                    source_file=source_file,
                    max_chars=max_chars,
                )
            )
    return chunks


def _chunk_guide(
    *,
    pages: Sequence[str],
    spec: OcrCandidateSpec,
    source_file: str,
    max_chars: int,
) -> list[LegislationChunk]:
    if len(pages) != 26:
        raise OcrCandidateIngestionError(
            "Kılavuz OCR stratejisi tam 26 sayfalık sabit adayı bekliyor."
        )
    chunks: list[LegislationChunk] = []
    for page_number, page_text in enumerate(pages, start=1):
        section, article = _guide_structure_for_page(page_number)
        chunks.extend(
            _page_chunks(
                text=page_text,
                page=page_number,
                section=section,
                article=article,
                spec=spec,
                source_file=source_file,
                max_chars=max_chars,
            )
        )
    return chunks


def _guide_structure_for_page(page: int) -> tuple[str, str]:
    for start, end, section, article in _GUIDE_PAGE_STRUCTURE:
        if start <= page <= end:
            return section, article
    raise OcrCandidateIngestionError(f"Kılavuz sayfa haritasında {page} bulunmuyor.")


def _page_chunks(
    *,
    text: str,
    page: int,
    section: str,
    article: str,
    spec: OcrCandidateSpec,
    source_file: str,
    max_chars: int,
) -> list[LegislationChunk]:
    normalized = normalize_whitespace(text)
    if not normalized:
        return []
    parts = _split_bounded(normalized, max_chars=max_chars)
    result: list[LegislationChunk] = []
    for part_index, part in enumerate(parts, start=1):
        identity = (
            f"{spec.document_id}|{section}|{article}|{page}|{part_index}|{part}"
        )
        chunk_id = "MEV-" + sha256(identity.encode("utf-8")).hexdigest()[:16].upper()
        result.append(
            LegislationChunk(
                chunk_id=chunk_id,
                document_id=spec.document_id,
                title=spec.title,
                section=section,
                article=article,
                text=part,
                source=source_file,
                source_sha256=spec.source_sha256.lower(),
                source_kind=COMPETITION_SNAPSHOT_SOURCE_KIND,
                page=page,
                page_end=page,
                source_url=spec.source_url,
                document_type=spec.document_type,
                domain=spec.domain,
                subdomain=spec.subdomain,
                validity_status="needs_verification",
                approved_for_active_rag=False,
                ocr_status=OCR_CANDIDATE_STATUS,
                context_text=(
                    f"{spec.title} > {section} > {article} > Sayfa {page}"
                ),
                status=COMPETITION_SNAPSHOT_STATUS,
                tags=[section, article, f"sayfa {page}", "OCR adayı"],
            )
        )
    return result


def _split_bounded(text: str, *, max_chars: int) -> list[str]:
    if len(text) <= max_chars:
        return [text]
    sentences = [
        normalize_whitespace(sentence)
        for sentence in re.split(r"(?<=[.!?;])\s+", text)
        if normalize_whitespace(sentence)
    ]
    parts: list[str] = []
    current = ""
    for sentence in sentences:
        if len(sentence) > max_chars:
            if current:
                parts.append(current)
                current = ""
            parts.extend(_hard_split(sentence, max_chars=max_chars))
            continue
        candidate = f"{current} {sentence}".strip()
        if current and len(candidate) > max_chars:
            parts.append(current)
            current = sentence
        else:
            current = candidate
    if current:
        parts.append(current)
    return parts


def _hard_split(text: str, *, max_chars: int) -> list[str]:
    words = text.split()
    parts: list[str] = []
    current = ""
    for word in words:
        if len(word) > max_chars:
            if current:
                parts.append(current)
                current = ""
            parts.extend(
                word[start : start + max_chars]
                for start in range(0, len(word), max_chars)
            )
            continue
        candidate = f"{current} {word}".strip()
        if current and len(candidate) > max_chars:
            parts.append(current)
            current = word
        else:
            current = candidate
    if current:
        parts.append(current)
    return parts


def _validate_chunks(
    chunks: Sequence[LegislationChunk],
    *,
    spec: OcrCandidateSpec,
    source_file: str,
) -> None:
    if not chunks:
        raise OcrCandidateIngestionError("OCR adayından hiç chunk üretilemedi.")
    seen: set[str] = set()
    for chunk in chunks:
        if chunk.chunk_id in seen:
            raise OcrCandidateIngestionError(
                f"OCR çıktısında yinelenen chunk_id: {chunk.chunk_id}"
            )
        seen.add(chunk.chunk_id)
        if (
            chunk.document_id != spec.document_id
            or chunk.source != source_file
            or chunk.source_sha256 != spec.source_sha256.lower()
            or chunk.source_kind != COMPETITION_SNAPSHOT_SOURCE_KIND
            or chunk.status != COMPETITION_SNAPSHOT_STATUS
            or chunk.validity_status != "needs_verification"
            or chunk.approved_for_active_rag
            or chunk.ocr_status != OCR_CANDIDATE_STATUS
        ):
            raise OcrCandidateIngestionError(
                f"{chunk.chunk_id}: snapshot/OCR kaynak sözleşmesi bozuk."
            )
        if (
            chunk.page is None
            or chunk.page_end is None
            or chunk.page < 1
            or chunk.page_end < chunk.page
            or chunk.page_end > spec.page_count
        ):
            raise OcrCandidateIngestionError(
                f"{chunk.chunk_id}: sayfa kaynağı geçersiz."
            )


def _load_report_document(
    report_path: Path,
    document_id: str,
) -> tuple[Mapping[str, Any], Mapping[str, Any]]:
    try:
        report = json.loads(report_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise OcrCandidateIngestionError(f"OCR raporu okunamadı: {exc}") from exc
    if not isinstance(report, Mapping):
        raise OcrCandidateIngestionError("OCR raporu bir JSON nesnesi olmalıdır.")
    raw_documents = report.get("documents")
    if isinstance(raw_documents, Mapping):
        documents: Sequence[object] = [raw_documents]
    elif isinstance(raw_documents, list):
        documents = raw_documents
    else:
        raise OcrCandidateIngestionError("OCR raporunda documents kaydı yok.")
    matches = [
        item
        for item in documents
        if isinstance(item, Mapping) and item.get("document_id") == document_id
    ]
    if len(matches) != 1:
        raise OcrCandidateIngestionError(
            "OCR raporunda belge kimliği tekil olarak bulunamadı."
        )
    return matches[0], report


def _validate_report_binding(
    *,
    report: Mapping[str, Any],
    document: Mapping[str, Any],
    spec: OcrCandidateSpec,
    source_file: str,
    derived_text_file: str,
    source_digest: str,
    candidate_digest: str,
) -> None:
    if report.get("human_verification_required") is not True:
        raise OcrCandidateIngestionError(
            "OCR raporu insan doğrulaması gerekliliğini taşımıyor."
        )
    if report.get("approved_for_active_rag") is not False:
        raise OcrCandidateIngestionError("OCR raporu güvenli fail-closed durumda değil.")
    if document.get("approved_for_active_rag") is not False:
        raise OcrCandidateIngestionError("OCR belge raporu aktif onay taşıyamaz.")
    if document.get("status") != "ocr_candidate_human_verification_required":
        raise OcrCandidateIngestionError("OCR belge raporu aday statüsünde değil.")
    if _normalize_portable_path(document.get("source_pdf")) != source_file:
        raise OcrCandidateIngestionError("OCR raporu farklı bir kaynak PDF'ye bağlı.")
    if _normalize_portable_path(document.get("output_text")) != derived_text_file:
        raise OcrCandidateIngestionError("OCR raporu farklı bir aday metne bağlı.")
    if str(document.get("source_sha256", "")).lower() != source_digest:
        raise OcrCandidateIngestionError("OCR raporu kaynak PDF hash'i eşleşmiyor.")
    if str(document.get("output_sha256", "")).lower() != candidate_digest:
        raise OcrCandidateIngestionError("OCR raporu aday metin hash'i eşleşmiyor.")
    if document.get("page_count") != spec.page_count:
        raise OcrCandidateIngestionError("OCR raporu sayfa sayısı eşleşmiyor.")
    if document.get("empty_output_page_count") != 0:
        raise OcrCandidateIngestionError("OCR raporunda boş aday sayfası bulunuyor.")


def _validate_report_pages(
    document: Mapping[str, Any],
    pages: Sequence[str],
) -> None:
    records = document.get("pages")
    if not isinstance(records, list) or len(records) != len(pages):
        raise OcrCandidateIngestionError("OCR raporu sayfa kayıtları eksik.")
    observed_numbers: list[int] = []
    for index, (record, page_text) in enumerate(zip(records, pages, strict=True), start=1):
        if not isinstance(record, Mapping):
            raise OcrCandidateIngestionError("OCR raporunda bozuk sayfa kaydı var.")
        observed_numbers.append(record.get("page"))
        if record.get("output_character_count") != len(page_text):
            raise OcrCandidateIngestionError(
                f"OCR raporunun {index}. sayfa karakter sayısı adayla eşleşmiyor."
            )
    if observed_numbers != list(range(1, len(pages) + 1)):
        raise OcrCandidateIngestionError("OCR raporu sayfa sırası geçersiz.")
    if document.get("output_character_count") != sum(len(page) for page in pages):
        raise OcrCandidateIngestionError("OCR raporu toplam karakter sayısı eşleşmiyor.")


def _resolve_project_path(project_root: Path, raw_path: str) -> tuple[Path, str]:
    portable = _normalize_portable_path(raw_path)
    resolved = (project_root / Path(portable)).resolve()
    try:
        relative = resolved.relative_to(project_root)
    except ValueError as exc:
        raise OcrCandidateIngestionError(
            "OCR girdisi proje kökünün dışında olamaz."
        ) from exc
    if not resolved.is_file():
        raise OcrCandidateIngestionError(f"OCR girdisi bulunamadı: {portable}")
    return resolved, relative.as_posix()


def _normalize_portable_path(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise OcrCandidateIngestionError("Boş veya geçersiz OCR kaynak yolu.")
    raw = value.strip()
    posix = PurePosixPath(raw.replace("\\", "/"))
    windows = PureWindowsPath(raw)
    if posix.is_absolute() or windows.is_absolute() or ".." in posix.parts:
        raise OcrCandidateIngestionError("OCR kaynak yolu proje-göreli olmalıdır.")
    normalized = posix.as_posix()
    if normalized in {"", "."}:
        raise OcrCandidateIngestionError("OCR kaynak yolu proje-göreli olmalıdır.")
    return normalized


def _file_sha256(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _pdf_page_count(path: Path) -> int:
    try:
        import pymupdf

        document = pymupdf.open(path)
        try:
            return len(document)
        finally:
            document.close()
    except ImportError:
        try:
            from pypdf import PdfReader

            return len(PdfReader(str(path)).pages)
        except ImportError as exc:  # pragma: no cover - declared dependencies
            raise OcrCandidateIngestionError(
                "PDF sayfa doğrulaması için PyMuPDF veya pypdf gereklidir."
            ) from exc


__all__ = [
    "CORE_OCR_CANDIDATE_SPECS",
    "OFFICIAL_WRITING_GUIDE_SPEC",
    "OFFICIAL_WRITING_REGULATION_SPEC",
    "OCR_CANDIDATE_STATUS",
    "OcrCandidateIngestionError",
    "OcrCandidateSpec",
    "ParsedOcrCandidate",
    "build_core_ocr_candidate_payloads",
    "build_ocr_candidate_payload",
    "parse_ocr_candidate_text",
]
