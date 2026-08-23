from __future__ import annotations

import json
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace

import pytest

from karayol_agent.curation import (
    CurationDomain,
    LegislationManifestRecord,
    PdfMatchStatus,
    ReviewStatus,
    ScopeStatus,
    TextLayerStatus,
)
from karayol_agent.ingestion import LegalStructureChunker
from karayol_agent.ingestion.quality import assess_text_layer
from karayol_agent.ingestion.service import (
    IngestionApprovalError,
    LegislationIngestionService,
)
from karayol_agent.text_utils import normalize_whitespace


def _readable_legal_page() -> str:
    sentence = (
        "Yol bakım başvurularında açık konum, tarih, hasar türü ve talep bilgisi "
        "birlikte kaydedilir. "
    )
    return (
        "BİRİNCİ BÖLÜM\nAmaç ve kapsam\nMADDE 1- (1) "
        + sentence * 5
    )


def _approved_manifest_record(
    path: Path,
    *,
    source_sha256: str | None = None,
) -> LegislationManifestRecord:
    digest = source_sha256 or sha256(path.read_bytes()).hexdigest()
    return LegislationManifestRecord(
        legislation_id=42,
        document_id="UAB-42",
        title="Sentetik Test Yönetmeliği",
        document_type="Yönetmelik",
        source_url="https://example.test/mevzuat/42",
        local_pdfs=[str(path)],
        pdf_match_status=PdfMatchStatus.MATCHED,
        source_sha256=digest,
        domain=CurationDomain.KGM_INFRASTRUCTURE,
        subdomain="maintenance",
        classification_confidence=1.0,
        scope_status=ScopeStatus.ACTIVE,
        candidate_for_active_rag=True,
        review_status=ReviewStatus.APPROVED,
        validity_status="verified",
        approved_for_active_rag=True,
        reviewed_by="Test Doğrulayıcısı",
        reviewed_at=datetime(2026, 8, 24, 12, 0, tzinfo=timezone.utc),
        review_notes="Kaynak, kapsam ve yürürlük doğrulandı.",
        text_layer_status=TextLayerStatus.AVAILABLE,
        ocr_required=False,
    )


def test_quality_report_flags_sparse_pdf_text() -> None:
    report = assess_text_layer(["MADDE 1- kısa", "", "MADDE 2-"])

    assert report.requires_ocr
    assert report.quality == "yetersiz"
    assert report.readable_page_ratio == 0


def test_quality_report_accepts_readable_legal_text() -> None:
    report = assess_text_layer([_readable_legal_page()])

    assert not report.requires_ocr
    assert report.quality == "uygun"
    assert report.readable_page_ratio == 1


def test_legal_chunker_preserves_section_article_paragraph_and_clause() -> None:
    text = (
        "BİRİNCİ BÖLÜM\nAmaç ve kapsam\n"
        "MADDE 1- (1) Başvuruda aşağıdaki bilgiler bulunur: "
        "a) Açık konum belirtilir. b) Hasar türü açıklanır. "
        "(2) Başvuru tarihi ayrıca kaydedilir.\n"
        "İKİNCİ BÖLÜM\nTrafik güvenliği\n"
        "MADDE 2- (1) Acil riskler ayrı değerlendirilir."
    )

    chunks = LegalStructureChunker().chunk(
        text,
        title="Sentetik Yönetmelik",
        source="test",
        source_status="sentetik_demo_kurali",
        document_id="TEST-MEV-1",
        source_kind="synthetic",
    )

    assert len(chunks) == 4
    assert chunks[0].section == "Birinci Bölüm — Amaç ve kapsam"
    assert chunks[0].article == "Madde 1"
    assert chunks[0].paragraph == "1"
    assert chunks[0].clause == "a"
    assert chunks[0].text.startswith("a)")
    assert "Başvuruda aşağıdaki bilgiler bulunur" in (chunks[0].context_text or "")
    assert chunks[1].clause == "b"
    assert chunks[2].paragraph == "2"
    assert chunks[2].clause is None
    assert chunks[3].section == "İkinci Bölüm — Trafik güvenliği"
    assert chunks[3].article == "Madde 2"


def test_legal_chunker_records_start_and_end_pages() -> None:
    pages = [
        "BİRİNCİ BÖLÜM\nGenel hükümler\n"
        "MADDE 1- (1) Birinci sayfada başlayan hüküm açıklanır.",
        "Hüküm ikinci sayfada devam eder. "
        "MADDE 2- (1) Bu hüküm yalnızca ikinci sayfadadır.",
    ]

    chunks = LegalStructureChunker().chunk_pages(
        pages,
        title="Sayfalı Yönetmelik",
        source="test.pdf",
        source_status="sentetik_demo_kurali",
        document_id="TEST-MEV-PAGES",
        source_kind="synthetic",
    )

    assert len(chunks) == 2
    assert (chunks[0].page, chunks[0].page_end) == (1, 2)
    assert (chunks[1].page, chunks[1].page_end) == (2, 2)


def test_long_paragraph_is_bounded_without_text_loss() -> None:
    paragraph = " ".join(f"kelime{index}" for index in range(80))
    text = f"MADDE 7- (1) {paragraph}"

    chunks = LegalStructureChunker(max_chars=64).chunk(
        text,
        title="Uzun Hüküm",
        source="first/location.pdf",
        source_status="sentetik_demo_kurali",
        document_id="TEST-MEV-LONG",
        source_kind="synthetic",
    )

    assert len(chunks) > 1
    assert all(len(chunk.text) <= 64 for chunk in chunks)
    assert " ".join(chunk.text for chunk in chunks) == normalize_whitespace(paragraph)
    assert all(chunk.article == "Madde 7" for chunk in chunks)
    assert all(chunk.paragraph == "1" for chunk in chunks)


def test_chunk_ids_are_stable_for_document_id_after_source_relocation() -> None:
    text = (
        "MADDE 3- (1) Yol bakım talepleri kaydedilir. "
        "(2) Konum bilgisi doğrulanır."
    )
    chunker = LegalStructureChunker()

    first = chunker.chunk(
        text,
        title="Kararlı Kimlik Testi",
        source="old/location/source.pdf",
        source_status="test",
        document_id="UAB-00042",
    )
    relocated = chunker.chunk(
        text,
        title="Kararlı Kimlik Testi",
        source="new/location/source.pdf",
        source_status="test",
        document_id="UAB-00042",
    )

    assert [chunk.chunk_id for chunk in first] == [
        chunk.chunk_id for chunk in relocated
    ]
    assert len({chunk.chunk_id for chunk in first}) == len(first)


def test_generic_pdf_ingestion_cannot_activate_public_legislation(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    path = tmp_path / "42_public.pdf"
    path.write_bytes(b"public legislation fixture")
    service = LegislationIngestionService()
    monkeypatch.setattr(service, "_read_pages", lambda _: [_readable_legal_page()])

    with pytest.raises(IngestionApprovalError):
        service.ingest_pdf(
            path,
            title="Kamu Mevzuatı",
            source_status="verified",
            output_path=tmp_path / "chunks.json",
            document_id="UAB-42",
            domain="kgm_infrastructure",
            validity_status="verified",
            approved_for_active_rag=True,
            reviewed_by="Test Doğrulayıcısı",
            source_kind="public_legislation",
        )

    assert not (tmp_path / "chunks.json").exists()


def test_manifest_ingestion_rejects_missing_human_approval(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    path = tmp_path / "42_public.pdf"
    path.write_bytes(b"public legislation fixture")
    record = _approved_manifest_record(path).model_copy(
        update={
            "approved_for_active_rag": False,
            "review_status": ReviewStatus.NEEDS_HUMAN_REVIEW,
            "reviewed_by": None,
        }
    )
    service = LegislationIngestionService()
    monkeypatch.setattr(service, "_read_pages", lambda _: [_readable_legal_page()])

    with pytest.raises(IngestionApprovalError):
        service.ingest_manifest_record(
            record,
            path=path,
            output_path=tmp_path / "chunks.json",
        )

    assert not (tmp_path / "chunks.json").exists()


def test_manifest_ingestion_rejects_source_hash_mismatch(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    path = tmp_path / "42_public.pdf"
    path.write_bytes(b"public legislation fixture")
    record = _approved_manifest_record(path, source_sha256="0" * 64)
    service = LegislationIngestionService()
    monkeypatch.setattr(service, "_read_pages", lambda _: [_readable_legal_page()])

    with pytest.raises(IngestionApprovalError):
        service.ingest_manifest_record(
            record,
            path=path,
            output_path=tmp_path / "chunks.json",
        )

    assert not (tmp_path / "chunks.json").exists()


def test_manifest_ingestion_cannot_activate_low_quality_text(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    path = tmp_path / "42_public.pdf"
    path.write_bytes(b"public legislation fixture")
    record = _approved_manifest_record(path)
    service = LegislationIngestionService()
    monkeypatch.setattr(service, "_read_pages", lambda _: ["MADDE 1- kısa"])

    with pytest.raises(IngestionApprovalError):
        service.ingest_manifest_record(
            record,
            path=path,
            output_path=tmp_path / "chunks.json",
        )

    assert not (tmp_path / "chunks.json").exists()


def test_verified_manifest_ingestion_writes_active_provenance(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    path = tmp_path / "42_public.pdf"
    path.write_bytes(b"public legislation fixture")
    digest = sha256(path.read_bytes()).hexdigest()
    record = _approved_manifest_record(path, source_sha256=digest)
    output = tmp_path / "chunks.json"
    service = LegislationIngestionService()
    monkeypatch.setattr(service, "_read_pages", lambda _: [_readable_legal_page()])

    report = service.ingest_manifest_record(record, path=path, output_path=output)
    payload = json.loads(output.read_text(encoding="utf-8"))

    assert report.approved_for_active_rag
    assert report.chunk_count > 0
    assert payload["approved_for_active_rag"] is True
    assert payload["source_sha256"] == digest
    assert payload["source_kind"] == "public_legislation"
    assert payload["validity_status"] == "verified"
    assert payload["document_id"]
    assert all(chunk["approved_for_active_rag"] is True for chunk in payload["data"])
    assert all(chunk["source_sha256"] == digest for chunk in payload["data"])
    assert all(chunk["page"] == 1 for chunk in payload["data"])


def test_active_corpus_combines_only_verified_ingestion_outputs(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    path = tmp_path / "42_public.pdf"
    path.write_bytes(b"public legislation fixture")
    record = _approved_manifest_record(path)
    document_output = tmp_path / "document.json"
    corpus_output = tmp_path / "active_corpus.json"
    service = LegislationIngestionService()
    monkeypatch.setattr(service, "_read_pages", lambda _: [_readable_legal_page()])

    report = service.ingest_manifest_record(
        record,
        path=path,
        output_path=document_output,
    )
    result = service.write_active_corpus([report], corpus_output)
    payload = json.loads(result.read_text(encoding="utf-8"))

    assert payload["approved_for_active_rag"] is True
    assert payload["document_count"] == 1
    assert payload["chunk_count"] == report.chunk_count
    assert payload["documents"][0]["document_id"] == "UAB-42"
    assert all(chunk["validity_status"] == "verified" for chunk in payload["data"])


def test_active_corpus_rejects_empty_approval_set(tmp_path: Path) -> None:
    with pytest.raises(IngestionApprovalError, match="onaylı belge bulunmuyor"):
        LegislationIngestionService().write_active_corpus(
            [], tmp_path / "active_corpus.json"
        )


def test_manifest_quarantine_chunks_without_granting_active_approval(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    path = tmp_path / "42_public.pdf"
    path.write_bytes(b"public legislation fixture")
    record = _approved_manifest_record(path)
    service = LegislationIngestionService()
    monkeypatch.setattr(service, "_read_pages", lambda _: [_readable_legal_page()])

    reports = service.ingest_manifest_quarantine(
        SimpleNamespace(data=[record]),
        project_root=tmp_path,
        output_dir=tmp_path / "quarantine",
    )
    payload = json.loads(Path(reports[0].output_file or "").read_text(encoding="utf-8"))

    assert reports[0].chunk_count > 0
    assert reports[0].approved_for_active_rag is False
    assert payload["approved_for_active_rag"] is False
    assert all(chunk["approved_for_active_rag"] is False for chunk in payload["data"])
