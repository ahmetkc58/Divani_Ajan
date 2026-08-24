from __future__ import annotations

import json
from pathlib import Path

import pytest

from karayol_agent.retrieval import BM25Index, LegislationRepository
from karayol_agent.retrieval.corpus import build_corpus_binding
from karayol_agent.schemas import LegislationChunk


ROOT = Path(__file__).resolve().parents[1]


def _write_repository(tmp_path: Path, record: dict[str, object]) -> Path:
    path = tmp_path / "legislation.json"
    payload = _active_envelope([record])
    path.write_text(
        json.dumps(payload, ensure_ascii=False),
        encoding="utf-8",
    )
    return path


def _active_envelope(records: list[dict[str, object]]) -> dict[str, object]:
    by_document: dict[str, dict[str, object]] = {}
    for record in records:
        document_id = str(record["document_id"])
        document = by_document.setdefault(
            document_id,
            {
                "document_id": document_id,
                "source_sha256": record["source_sha256"],
                "source_url": record["source_url"],
                "chunk_count": 0,
                "reviewed_by": "Hukuk Uzmanı",
                "reviewed_at": "2026-08-24T12:00:00+03:00",
            },
        )
        document["chunk_count"] = int(document["chunk_count"]) + 1
    return {
        "schema_version": "2.0",
        "dataset_name": "active_public_legislation",
        "generated_at": "2026-08-24T12:30:00+03:00",
        "approved_for_active_rag": True,
        "document_count": len(by_document),
        "chunk_count": len(records),
        "documents": list(by_document.values()),
        "data": records,
    }


def _public_record(**overrides: object) -> dict[str, object]:
    record: dict[str, object] = {
        "chunk_id": "MEV-VALID-001",
        "document_id": "UAB-42",
        "title": "Doğrulanmış Kamu Mevzuatı",
        "section": "Birinci Bölüm",
        "article": "Madde 1",
        "paragraph": "1",
        "text": "Yol bakım başvurularında açık konum bilgisi bulunur.",
        "source": "archive/42_mevzuat.pdf",
        "source_url": "https://example.test/mevzuat/42",
        "source_sha256": "a" * 64,
        "source_kind": "public_legislation",
        "page": 1,
        "page_end": 1,
        "document_type": "yonetmelik",
        "domain": "kgm_infrastructure",
        "subdomain": "maintenance",
        "validity_status": "verified",
        "approved_for_active_rag": True,
        "ocr_status": "text_layer_available",
        "context_text": "Doğrulanmış Kamu Mevzuatı > Birinci Bölüm > Madde 1",
        "status": "verified",
    }
    record.update(overrides)
    return record


def test_legislation_chunk_source_kind_defaults_to_unknown() -> None:
    chunk = LegislationChunk(
        chunk_id="LEGACY-1",
        title="Eski Kayıt",
        section="Kural",
        text="Eski kayıtta açık bir kaynak türü bulunmuyor.",
        source="legacy.json",
    )

    assert chunk.source_kind == "unknown"


def test_public_repository_fails_closed_for_legacy_untrusted_data() -> None:
    repository = LegislationRepository(ROOT / "data" / "synthetic_legislation.json")

    with pytest.raises(ValueError):
        repository.load()


def test_trusted_synthetic_mode_loads_legacy_demo_dataset() -> None:
    chunks = LegislationRepository(
        ROOT / "data" / "synthetic_legislation.json",
        trusted_synthetic=True,
    ).load()

    assert chunks
    assert chunks[0].chunk_id == "SENT-KRY-001"


def test_public_repository_rejects_unapproved_chunk(tmp_path: Path) -> None:
    path = _write_repository(
        tmp_path,
        _public_record(approved_for_active_rag=False),
    )

    with pytest.raises(ValueError):
        LegislationRepository(path).load()


@pytest.mark.parametrize(
    "overrides",
    [
        pytest.param({"document_id": None}, id="missing-document-id"),
        pytest.param({"title": "  "}, id="missing-title"),
        pytest.param({"section": ""}, id="missing-section"),
        pytest.param({"article": None}, id="missing-article"),
        pytest.param({"article": "  "}, id="blank-article"),
        pytest.param({"text": ""}, id="missing-text"),
        pytest.param({"source": "  "}, id="missing-source-path"),
        pytest.param({"context_text": None}, id="missing-context"),
        pytest.param({"context_text": "  "}, id="blank-context"),
        pytest.param({"source_url": None}, id="missing-source-url"),
        pytest.param({"source_url": "ftp://example.test/42"}, id="invalid-source-url"),
        pytest.param({"source_sha256": None}, id="missing-source-hash"),
        pytest.param({"source_sha256": "abc"}, id="invalid-source-hash"),
        pytest.param({"source_sha256": "z" * 64}, id="non-hex-source-hash"),
        pytest.param({"domain": "aviation"}, id="out-of-scope-domain"),
        pytest.param({"page": None}, id="missing-start-page"),
        pytest.param({"page_end": None}, id="missing-end-page"),
        pytest.param(
            {"validity_status": "needs_verification"},
            id="unverified-validity",
        ),
        pytest.param(
            {"ocr_status": "ocr_required_unverified"},
            id="unverified-ocr",
        ),
    ],
)
def test_public_repository_rejects_incomplete_provenance(
    tmp_path: Path,
    overrides: dict[str, object],
) -> None:
    path = _write_repository(tmp_path, _public_record(**overrides))

    with pytest.raises(ValueError):
        LegislationRepository(path).load()


def test_trusted_synthetic_mode_does_not_bypass_public_approval(
    tmp_path: Path,
) -> None:
    path = _write_repository(
        tmp_path,
        _public_record(approved_for_active_rag=False),
    )

    with pytest.raises(ValueError):
        LegislationRepository(path, trusted_synthetic=True).load()


@pytest.mark.parametrize("ocr_status", ["text_layer_available", "ocr_verified"])
def test_public_repository_loads_only_fully_verified_chunk(
    tmp_path: Path,
    ocr_status: str,
) -> None:
    path = _write_repository(tmp_path, _public_record(ocr_status=ocr_status))

    chunks = LegislationRepository(path).load()

    assert len(chunks) == 1
    assert chunks[0].chunk_id == "MEV-VALID-001"
    assert chunks[0].approved_for_active_rag
    assert chunks[0].validity_status == "verified"
    assert chunks[0].source_kind == "public_legislation"
    assert chunks[0].ocr_status == ocr_status


def test_public_repository_returns_order_independent_exact_binding(
    tmp_path: Path,
) -> None:
    first = _public_record(chunk_id="MEV-VALID-001")
    second = _public_record(chunk_id="MEV-VALID-002")
    path = tmp_path / "active.json"
    path.write_text(
        json.dumps(_active_envelope([second, first]), ensure_ascii=False),
        encoding="utf-8",
    )

    chunks, binding = LegislationRepository(path).load_with_binding()

    assert binding == build_corpus_binding(reversed(chunks))
    assert binding.chunk_ids == ("MEV-VALID-001", "MEV-VALID-002")
    assert len(binding.fingerprint) == 64


@pytest.mark.parametrize("shape", ["bare-list", "data-only"])
def test_public_repository_rejects_missing_active_corpus_envelope(
    tmp_path: Path,
    shape: str,
) -> None:
    record = _public_record()
    payload: object = [record] if shape == "bare-list" else {"data": [record]}
    path = tmp_path / f"{shape}.json"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    with pytest.raises(ValueError, match="schema_version=2.0"):
        LegislationRepository(path).load()


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda payload: payload.update({"document_count": 2}), "document_count"),
        (lambda payload: payload.update({"chunk_count": 2}), "chunk_count"),
        (
            lambda payload: payload["documents"][0].update({"reviewed_by": None}),
            "reviewed_by/reviewed_at",
        ),
        (
            lambda payload: payload["documents"][0].update(
                {"reviewed_at": "2026-08-24T12:00:00"}
            ),
            "timezone-aware",
        ),
        (
            lambda payload: payload["documents"][0].update(
                {"source_sha256": "b" * 64}
            ),
            "source_sha256",
        ),
    ],
)
def test_public_repository_rejects_forged_review_envelope(
    tmp_path: Path,
    mutation: object,
    message: str,
) -> None:
    payload = _active_envelope([_public_record()])
    mutation(payload)  # type: ignore[operator]
    path = tmp_path / "forged.json"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    with pytest.raises(ValueError, match=message):
        LegislationRepository(path).load()


def test_bm25_returns_yol_bakim_rule_first() -> None:
    chunks = LegislationRepository(
        ROOT / "data" / "synthetic_legislation.json",
        trusted_synthetic=True,
    ).load()
    hits = BM25Index(chunks).search("asfalt çukuru için yol bakım onarım talebi", top_k=3)

    assert hits
    assert hits[0].chunk.chunk_id == "SENT-KRY-001"
    assert "asfalt" in hits[0].matched_terms
