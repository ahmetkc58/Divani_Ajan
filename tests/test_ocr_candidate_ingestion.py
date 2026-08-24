from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from karayol_agent.ingestion.ocr_candidate import (
    COMPETITION_SNAPSHOT_SOURCE_KIND,
    COMPETITION_SNAPSHOT_STATUS,
    OFFICIAL_WRITING_GUIDE_SPEC,
    OFFICIAL_WRITING_REGULATION_SPEC,
    OCR_CANDIDATE_STATUS,
    OcrCandidateIngestionError,
    OcrCandidateSpec,
    build_ocr_candidate_payload,
    parse_ocr_candidate_text,
)
from karayol_agent.schemas import LegislationChunk


PROJECT_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def guide_payload() -> dict[str, object]:
    return build_ocr_candidate_payload(PROJECT_ROOT, OFFICIAL_WRITING_GUIDE_SPEC)


@pytest.fixture(scope="module")
def regulation_payload() -> dict[str, object]:
    return build_ocr_candidate_payload(
        PROJECT_ROOT,
        OFFICIAL_WRITING_REGULATION_SPEC,
    )


@pytest.mark.parametrize(
    ("spec", "expected_count", "expected_derived"),
    [
        (
            OFFICIAL_WRITING_GUIDE_SPEC,
            26,
            "data/processed/ocr_review/official-writing-guide.ocr-candidate.txt",
        ),
        (
            OFFICIAL_WRITING_REGULATION_SPEC,
            49,
            (
                "data/processed/ocr_review/full_ocr/"
                "official-writing-regulation.ocr-candidate.txt"
            ),
        ),
    ],
)
def test_pinned_ocr_payload_preserves_snapshot_and_source_provenance(
    spec: OcrCandidateSpec,
    expected_count: int,
    expected_derived: str,
) -> None:
    payload = build_ocr_candidate_payload(PROJECT_ROOT, spec)
    records = payload["data"]

    assert payload["source_file"] == spec.source_pdf
    assert payload["source_sha256"] == spec.source_sha256
    assert payload["derived_text_file"] == expected_derived
    assert payload["derived_text_sha256"] == spec.candidate_sha256
    assert payload["page_count"] == expected_count
    assert payload["text_origin"] == "machine_ocr_candidate"
    assert payload["source_kind"] == COMPETITION_SNAPSHOT_SOURCE_KIND
    assert payload["source_status"] == COMPETITION_SNAPSHOT_STATUS
    assert payload["validity_status"] == "needs_verification"
    assert payload["approved_for_active_rag"] is False
    assert payload["ocr_status"] == OCR_CANDIDATE_STATUS
    assert isinstance(records, list) and records

    chunks = [LegislationChunk.model_validate(record) for record in records]
    assert len({chunk.chunk_id for chunk in chunks}) == len(chunks)
    assert {chunk.source for chunk in chunks} == {spec.source_pdf}
    assert {chunk.source_sha256 for chunk in chunks} == {spec.source_sha256}
    assert {chunk.source_kind for chunk in chunks} == {
        COMPETITION_SNAPSHOT_SOURCE_KIND
    }
    assert {chunk.status for chunk in chunks} == {COMPETITION_SNAPSHOT_STATUS}
    assert {chunk.ocr_status for chunk in chunks} == {OCR_CANDIDATE_STATUS}
    assert not any(chunk.approved_for_active_rag for chunk in chunks)
    assert all(chunk.validity_status == "needs_verification" for chunk in chunks)
    assert all(chunk.page and chunk.page_end for chunk in chunks)
    assert max(chunk.page_end or 0 for chunk in chunks) == expected_count
    assert all(len(chunk.text) <= 1800 for chunk in chunks)
    assert all("===== SAYFA" not in chunk.text for chunk in chunks)
    assert all("insan doğrulaması olmadan" not in chunk.text for chunk in chunks)


def test_guide_uses_explicit_page_structure_instead_of_false_article_detection(
    guide_payload: dict[str, object],
) -> None:
    chunks = [
        LegislationChunk.model_validate(record)
        for record in guide_payload["data"]  # type: ignore[index]
    ]

    assert len(chunks) == 29
    assert {chunk.page for chunk in chunks} == set(range(1, 27))
    expected_sections = {
        3: "Ön Bölüm — İçindekiler",
        9: "1. Resmî Yazışma Ortamları",
        11: "2. Nüsha Sayısı",
        17: "7. Başlık",
        23: "8. Sayı",
        25: "9. Tarih",
        26: "10. Konu",
    }
    for page, section in expected_sections.items():
        assert {chunk.section for chunk in chunks if chunk.page == page} == {section}
    assert all(chunk.article and chunk.article.startswith("Kılavuz") for chunk in chunks)

    repeated = build_ocr_candidate_payload(PROJECT_ROOT, OFFICIAL_WRITING_GUIDE_SPEC)
    assert [record["chunk_id"] for record in guide_payload["data"]] == [  # type: ignore[index]
        record["chunk_id"] for record in repeated["data"]
    ]


def test_regulation_repairs_articles_and_separates_examples(
    regulation_payload: dict[str, object],
) -> None:
    chunks = [
        LegislationChunk.model_validate(record)
        for record in regulation_payload["data"]  # type: ignore[index]
    ]
    articles = list(dict.fromkeys(chunk.article for chunk in chunks))
    expected_core = [*(f"Madde {number}" for number in range(1, 38))]
    expected_core.extend(["Geçici Madde 1", "Madde 38", "Madde 39"])

    assert len(chunks) == 170
    assert articles[:40] == expected_core
    assert "Madde 14" in articles
    assert "Madde 36" in articles
    assert "Madde 18" in articles
    assert "Ek Madde 18" not in articles

    core = [chunk for chunk in chunks if chunk.article in expected_core]
    supplements = [chunk for chunk in chunks if chunk not in core]
    assert core and supplements
    assert max(chunk.page_end or 0 for chunk in core) == 16
    assert {chunk.page for chunk in supplements} == set(range(17, 50))
    assert all(chunk.section == "Ekler ve Örnekler" for chunk in supplements)
    assert max(
        chunk.page_end or 0 for chunk in chunks if chunk.article == "Madde 39"
    ) == 16
    assert any(
        chunk.page == 49 and "1234567" in chunk.text for chunk in supplements
    )


def _candidate_text(*pages: str) -> str:
    sections = [
        "UYARI: OCR adayıdır.",
        "Belge kimliği: test-document",
        "Kaynak PDF: source.pdf",
    ]
    for page, content in enumerate(pages, start=1):
        sections.extend([f"\n===== SAYFA {page} =====", content])
    return "\n".join(sections) + "\n"


def test_candidate_parser_accepts_bom_crlf_and_no_final_newline() -> None:
    text = "\ufeff" + _candidate_text("Birinci sayfa", "İkinci sayfa")
    parsed = parse_ocr_candidate_text(
        text.replace("\n", "\r\n").rstrip("\r\n"),
        expected_document_id="test-document",
        expected_source_pdf="source.pdf",
        expected_page_count=2,
    )

    assert parsed.document_id == "test-document"
    assert parsed.source_pdf == "source.pdf"
    assert parsed.pages == ("Birinci sayfa", "İkinci sayfa")


@pytest.mark.parametrize(
    "text",
    [
        _candidate_text("Bir", "İki").replace("SAYFA 2", "SAYFA 3"),
        _candidate_text("Bir", "İki").replace("SAYFA 2", "SAYFA 1"),
        _candidate_text("Bir", "İki").replace("===== SAYFA 2 =====", "== SAYFA 2 =="),
        _candidate_text("Bir", "   "),
    ],
)
def test_candidate_parser_rejects_missing_duplicate_malformed_or_empty_pages(
    text: str,
) -> None:
    with pytest.raises(OcrCandidateIngestionError):
        parse_ocr_candidate_text(
            text,
            expected_document_id="test-document",
            expected_source_pdf="source.pdf",
            expected_page_count=2,
        )


@pytest.mark.parametrize(
    ("document_id", "source_pdf"),
    [("other-document", "source.pdf"), ("test-document", "other.pdf")],
)
def test_candidate_parser_rejects_header_binding_mismatch(
    document_id: str,
    source_pdf: str,
) -> None:
    with pytest.raises(OcrCandidateIngestionError):
        parse_ocr_candidate_text(
            _candidate_text("Birinci sayfa"),
            expected_document_id=document_id,
            expected_source_pdf=source_pdf,
            expected_page_count=1,
        )


def test_pinned_hash_mismatch_fails_before_chunking() -> None:
    invalid = replace(OFFICIAL_WRITING_GUIDE_SPEC, candidate_sha256="0" * 64)

    with pytest.raises(OcrCandidateIngestionError, match="OCR aday SHA-256"):
        build_ocr_candidate_payload(PROJECT_ROOT, invalid)


def test_regulation_rejects_the_earlier_mixed_ocr_candidate() -> None:
    mixed = replace(
        OFFICIAL_WRITING_REGULATION_SPEC,
        candidate_text=(
            "data/processed/ocr_review/"
            "official-writing-regulation.ocr-candidate.txt"
        ),
        candidate_sha256=(
            "2b5ce92842f6a853775fde0be6cb146bfa1464b9a3a477f4bf4e35da02e59a5a"
        ),
        ocr_report="reports/ocr_review_2026-08-24.json",
    )

    with pytest.raises(OcrCandidateIngestionError, match="tam OCR"):
        build_ocr_candidate_payload(PROJECT_ROOT, mixed)


def test_project_relative_path_contract_rejects_traversal() -> None:
    invalid = replace(OFFICIAL_WRITING_GUIDE_SPEC, candidate_text="../candidate.txt")

    with pytest.raises(OcrCandidateIngestionError, match="proje-göreli"):
        build_ocr_candidate_payload(PROJECT_ROOT, invalid)
