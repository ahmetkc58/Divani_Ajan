from __future__ import annotations

import json
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path

import pytest

from karayol_agent.ingestion.snapshot import (
    CompetitionSnapshotCorpusBuilder,
    SnapshotBuildError,
)
from karayol_agent.ingestion.ocr_candidate import build_core_ocr_candidate_payloads
from karayol_agent.retrieval.contracts import (
    COMPETITION_SNAPSHOT_DATASET_NAME,
    COMPETITION_SNAPSHOT_NOTICE,
    COMPETITION_SNAPSHOT_STATUS,
    CorpusMode,
)
from karayol_agent.retrieval.repository import (
    LegislationRepository,
    RepositoryApprovalError,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _write_document_output(
    project_root: Path,
    *,
    document_id: str = "official-writing-guide",
    ocr: bool = False,
    derived_hash_override: str | None = None,
) -> Path:
    source = project_root / "sources" / f"{document_id}.pdf"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_bytes(f"pdf fixture: {document_id}".encode())
    source_hash = sha256(source.read_bytes()).hexdigest()
    title = "Snapshot Belgesi"
    source_url = None
    ocr_status = "ocr_candidate_unverified" if ocr else "text_layer_available"
    payload: dict[str, object] = {
        "schema_version": "2.0",
        "dataset_name": title,
        "document_id": document_id,
        "source_file": str(source),
        "source_url": source_url,
        "source_sha256": source_hash,
        "source_kind": "public_legislation",
        "validity_status": "needs_verification",
        "approved_for_active_rag": False,
        "text_origin": "machine_ocr_candidate" if ocr else "pdf_text_layer",
        "data": [
            {
                "chunk_id": f"SNAP-{document_id}-001",
                "document_id": document_id,
                "title": title,
                "section": "Kılavuz Bölümü",
                "article": None,
                "text": "Mevcut proje snapshot'ındaki örnek hüküm metnidir.",
                "source": str(source),
                "source_sha256": source_hash,
                "source_kind": "public_legislation",
                "page": 1,
                "page_end": 1,
                "source_url": source_url,
                "document_type": "kilavuz",
                "domain": "official_writing",
                "subdomain": "formal_correspondence",
                "validity_status": "needs_verification",
                "approved_for_active_rag": False,
                "ocr_status": ocr_status,
                "context_text": "Snapshot Belgesi > Kılavuz Bölümü > Sayfa 1",
                "status": "karantina_insan_dogrulamasi_bekliyor",
            }
        ],
    }
    if ocr:
        derived = project_root / "processed" / f"{document_id}.ocr.txt"
        derived.parent.mkdir(parents=True, exist_ok=True)
        derived.write_text("makine OCR aday metni", encoding="utf-8")
        payload["derived_text_file"] = str(derived)
        payload["derived_text_sha256"] = (
            derived_hash_override or sha256(derived.read_bytes()).hexdigest()
        )

    output = project_root / "processed" / f"{document_id}.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return output


def _build_snapshot(project_root: Path, *, ocr: bool = False) -> Path:
    document_output = _write_document_output(project_root, ocr=ocr)
    return CompetitionSnapshotCorpusBuilder(project_root=project_root).build(
        [document_output],
        project_root / "processed" / "competition_snapshot.json",
        acknowledge_not_current=True,
    )


def test_builder_emits_bounded_snapshot_without_public_law_approval(
    tmp_path: Path,
) -> None:
    output = _build_snapshot(tmp_path)
    payload = json.loads(output.read_text(encoding="utf-8"))

    assert payload["dataset_name"] == COMPETITION_SNAPSHOT_DATASET_NAME
    assert payload["corpus_mode"] == CorpusMode.COMPETITION_SNAPSHOT.value
    assert payload["currentness_verified"] is False
    assert payload["legal_reliance_allowed"] is False
    assert payload["usage_notice"] == COMPETITION_SNAPSHOT_NOTICE
    assert payload["documents"][0]["source_url"] is None
    assert payload["documents"][0]["source_path"].startswith("sources/")
    assert not Path(payload["documents"][0]["source_path"]).is_absolute()

    chunk = payload["data"][0]
    assert chunk["article"] is None
    assert chunk["source_kind"] == CorpusMode.COMPETITION_SNAPSHOT.value
    assert chunk["validity_status"] == "needs_verification"
    assert chunk["approved_for_active_rag"] is False
    assert chunk["status"] == COMPETITION_SNAPSHOT_STATUS

    chunks = LegislationRepository(
        output, corpus_mode=CorpusMode.COMPETITION_SNAPSHOT
    ).load()
    assert [item.chunk_id for item in chunks] == [chunk["chunk_id"]]
    with pytest.raises(RepositoryApprovalError):
        LegislationRepository(output).load()


def test_builder_requires_explicit_not_current_acknowledgement(tmp_path: Path) -> None:
    source = _write_document_output(tmp_path)
    output = tmp_path / "processed" / "competition_snapshot.json"

    with pytest.raises(SnapshotBuildError, match="açıkça kabul"):
        CompetitionSnapshotCorpusBuilder(project_root=tmp_path).build(
            [source], output
        )

    assert not output.exists()


def test_builder_verifies_ocr_derived_text_hash_and_marks_candidate(
    tmp_path: Path,
) -> None:
    output = _build_snapshot(tmp_path, ocr=True)
    payload = json.loads(output.read_text(encoding="utf-8"))

    assert payload["documents"][0]["text_origin"] == "machine_ocr_candidate"
    assert len(payload["documents"][0]["derived_text_sha256"]) == 64
    assert payload["data"][0]["ocr_status"] == "ocr_candidate_unverified"


def test_builder_consolidates_only_exact_duplicate_rows_and_preserves_page_span(
    tmp_path: Path,
) -> None:
    source = _write_document_output(tmp_path)
    payload = json.loads(source.read_text(encoding="utf-8"))
    duplicate = dict(payload["data"][0])
    duplicate.update({"page": 3, "page_end": 4})
    payload["data"].append(duplicate)
    source.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    output = CompetitionSnapshotCorpusBuilder(project_root=tmp_path).build(
        [source],
        tmp_path / "processed" / "competition_snapshot.json",
        acknowledge_not_current=True,
    )
    corpus = json.loads(output.read_text(encoding="utf-8"))

    assert corpus["source_chunk_count"] == 2
    assert corpus["chunk_count"] == 1
    assert corpus["exact_duplicate_rows_consolidated"] == 1
    assert corpus["documents"][0]["source_chunk_count"] == 2
    assert corpus["documents"][0]["chunk_count"] == 1
    assert corpus["documents"][0]["exact_duplicate_rows_consolidated"] == 1
    assert (corpus["data"][0]["page"], corpus["data"][0]["page_end"]) == (1, 4)


def test_builder_rejects_same_chunk_id_with_different_evidence(tmp_path: Path) -> None:
    source = _write_document_output(tmp_path)
    payload = json.loads(source.read_text(encoding="utf-8"))
    conflicting = dict(payload["data"][0])
    conflicting["text"] = "Aynı kimlikle farklı kanıt içeriği."
    payload["data"].append(conflicting)
    source.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    output = tmp_path / "processed" / "competition_snapshot.json"

    with pytest.raises(SnapshotBuildError, match="farklı kanıt içeriği"):
        CompetitionSnapshotCorpusBuilder(project_root=tmp_path).build(
            [source], output, acknowledge_not_current=True
        )

    assert not output.exists()


def test_real_quarantine_duplicate_rows_are_explicitly_consolidated() -> None:
    builder = CompetitionSnapshotCorpusBuilder(project_root=PROJECT_ROOT)
    cases = [
        (
            "law-2918.json",
            472,
            471,
            1,
            "MEV-A387AA1FF347063F",
            (44, 44),
        ),
        (
            "uab-road-transport-regulation.json",
            860,
            858,
            2,
            "MEV-784FE42DB1BD2032",
            (42, 43),
        ),
    ]

    for filename, source_count, chunk_count, consolidated, chunk_id, pages in cases:
        input_path = PROJECT_ROOT / "data" / "processed" / "stage3_quarantine" / filename
        document, chunks = builder._normalize_document(
            builder._read_document_output(input_path), input_path
        )
        merged = next(chunk for chunk in chunks if chunk["chunk_id"] == chunk_id)

        assert document["source_chunk_count"] == source_count
        assert document["chunk_count"] == chunk_count
        assert document["exact_duplicate_rows_consolidated"] == consolidated
        assert (merged["page"], merged["page_end"]) == pages


def test_real_eight_document_snapshot_is_2606_rows_to_2603_unique_chunks() -> None:
    builder = CompetitionSnapshotCorpusBuilder(project_root=PROJECT_ROOT)
    documents: list[dict[str, object]] = []
    chunks: list[dict[str, object]] = []
    quarantine_dir = PROJECT_ROOT / "data" / "processed" / "stage3_quarantine"
    text_layer_outputs = (
        "law-2918.json",
        "law-4925.json",
        "uab-road-expropriation-regulation.json",
        "uab-road-infrastructure-safety-regulation.json",
        "uab-road-traffic-regulation.json",
        "uab-road-transport-regulation.json",
    )
    for filename in text_layer_outputs:
        input_path = quarantine_dir / filename
        document, document_chunks = builder._normalize_document(
            builder._read_document_output(input_path), input_path
        )
        documents.append(document)
        chunks.extend(document_chunks)
    for payload in build_core_ocr_candidate_payloads(PROJECT_ROOT):
        document, document_chunks = builder._normalize_document(
            payload, PROJECT_ROOT / "in-memory-ocr-payload.json"
        )
        documents.append(document)
        chunks.extend(document_chunks)

    source_chunk_count = sum(
        int(document["source_chunk_count"]) for document in documents
    )
    consolidated = sum(
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
        "exact_duplicate_rows_consolidated": consolidated,
        "documents": documents,
        "data": chunks,
    }

    LegislationRepository.validate_competition_snapshot_envelope(corpus)
    assert len(documents) == 8
    assert source_chunk_count == 2606
    assert len(chunks) == 2603
    assert consolidated == 3
    assert len({str(chunk["chunk_id"]) for chunk in chunks}) == 2603


def test_builder_rejects_mismatched_ocr_derived_text_hash_before_write(
    tmp_path: Path,
) -> None:
    source = _write_document_output(
        tmp_path,
        ocr=True,
        derived_hash_override="0" * 64,
    )
    output = tmp_path / "processed" / "competition_snapshot.json"

    with pytest.raises(SnapshotBuildError, match="türetilmiş metin SHA-256"):
        CompetitionSnapshotCorpusBuilder(project_root=tmp_path).build(
            [source], output, acknowledge_not_current=True
        )

    assert not output.exists()


@pytest.mark.parametrize(
    "mutate",
    [
        pytest.param(
            lambda payload: payload.update({"currentness_verified": True}),
            id="claims-currentness",
        ),
        pytest.param(
            lambda payload: payload.update({"legal_reliance_allowed": True}),
            id="allows-legal-reliance",
        ),
        pytest.param(
            lambda payload: payload.update({"usage_notice": "kısaltılmış uyarı"}),
            id="changes-fixed-notice",
        ),
        pytest.param(
            lambda payload: payload["data"][0].update(
                {"approved_for_active_rag": True}
            ),
            id="claims-public-approval",
        ),
        pytest.param(
            lambda payload: payload["data"][0].update(
                {"validity_status": "verified"}
            ),
            id="claims-verified-validity",
        ),
        pytest.param(
            lambda payload: payload["data"][0].update(
                {"source_kind": "public_legislation"}
            ),
            id="masquerades-as-public",
        ),
        pytest.param(
            lambda payload: (
                payload["documents"][0].update({"source_path": "../outside.pdf"}),
                payload["data"][0].update({"source": "../outside.pdf"}),
            ),
            id="path-traversal",
        ),
        pytest.param(
            lambda payload: (
                payload["documents"][0].update(
                    {"source_path": "C:\\private\\outside.pdf"}
                ),
                payload["data"][0].update(
                    {"source": "C:\\private\\outside.pdf"}
                ),
            ),
            id="absolute-windows-path",
        ),
        pytest.param(
            lambda payload: payload.update({"chunk_count": 2}),
            id="forged-count",
        ),
        pytest.param(
            lambda payload: payload.update({"source_chunk_count": 2}),
            id="forged-source-count",
        ),
        pytest.param(
            lambda payload: payload["documents"][0].update(
                {"exact_duplicate_rows_consolidated": 1}
            ),
            id="forged-document-consolidation-count",
        ),
    ],
)
def test_snapshot_repository_fails_closed_for_contract_mutations(
    tmp_path: Path,
    mutate: object,
) -> None:
    output = _build_snapshot(tmp_path)
    payload = json.loads(output.read_text(encoding="utf-8"))
    mutate(payload)  # type: ignore[operator]
    output.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    with pytest.raises(RepositoryApprovalError):
        LegislationRepository(
            output, corpus_mode=CorpusMode.COMPETITION_SNAPSHOT
        ).load()


def test_builder_rejects_source_outside_project_root(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()
    source_output = _write_document_output(project_root)
    payload = json.loads(source_output.read_text(encoding="utf-8"))
    outside = tmp_path / "outside.pdf"
    outside.write_bytes(b"outside")
    payload["source_file"] = str(outside)
    payload["source_sha256"] = sha256(outside.read_bytes()).hexdigest()
    payload["data"][0]["source_sha256"] = payload["source_sha256"]
    source_output.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(SnapshotBuildError, match="proje kökü dışına"):
        CompetitionSnapshotCorpusBuilder(project_root=project_root).build(
            [source_output],
            project_root / "processed" / "snapshot.json",
            acknowledge_not_current=True,
        )
