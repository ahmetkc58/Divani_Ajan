from __future__ import annotations

import csv
import json
from hashlib import sha256
from pathlib import Path

import pytest

from karayol_agent.cli import main
from karayol_agent.curation import (
    CurationDomain,
    CurationError,
    LegislationDomainClassifier,
    LegislationManifestRecord,
    LegislationManifestService,
    PdfMatchStatus,
    ReviewStatus,
    ScopeStatus,
    TextLayerStatus,
    ValidityStatus,
)


def test_domain_classifier_separates_infrastructure_and_transport() -> None:
    classifier = LegislationDomainClassifier()

    infrastructure = classifier.classify(
        "Karayolu Yapımı Amaçlı Kamulaştırmalar Hakkında Yönetmelik"
    )
    transport = classifier.classify("Karayolu Taşıma Yönetmeliği")

    assert infrastructure.domain == CurationDomain.KGM_INFRASTRUCTURE
    assert infrastructure.subdomain == "expropriation"
    assert infrastructure.candidate_for_active_rag
    assert transport.domain == CurationDomain.ROAD_TRANSPORT
    assert transport.candidate_for_active_rag


def test_domain_classifier_marks_cross_sector_title_for_review() -> None:
    result = LegislationDomainClassifier().classify(
        "Karayolu sınır kapıları ile hava limanlarında güvenlik yönetmeliği"
    )

    assert result.domain == CurationDomain.AVIATION
    assert result.scope_status == ScopeStatus.REVIEW_REQUIRED
    assert not result.candidate_for_active_rag
    assert any("insan kapsam kontrolü" in reason for reason in result.reasons)


def test_domain_classifier_does_not_treat_maritime_authorization_as_road() -> None:
    result = LegislationDomainClassifier().classify(
        "Su Motosikleti İmalat Yetki Belgesi Kriterleri Talimatı"
    )

    assert result.domain == CurationDomain.MARITIME
    assert result.scope_status == ScopeStatus.OUT_OF_SCOPE
    assert not result.candidate_for_active_rag


def test_domain_classifier_marks_road_and_rail_tunnel_rule_for_review() -> None:
    result = LegislationDomainClassifier().classify(
        "Türkiye Karayolları ve Demiryolları Tünelleri Deprem Yönetmeliği"
    )

    assert result.scope_status == ScopeStatus.REVIEW_REQUIRED
    assert not result.candidate_for_active_rag


def test_manifest_matches_pdfs_without_auto_approving_records(tmp_path: Path) -> None:
    records_path = tmp_path / "mevzuatlar.json"
    records_path.write_text(
        json.dumps(
            {
                "data": [
                    {
                        "mevzuatId": 100,
                        "ad": "Karayolu Taşıma Yönetmeliği",
                        "tur": "Kurum Yönetmeliği",
                        "detail_url": "https://example.test/100",
                    },
                    {
                        "mevzuatId": 200,
                        "ad": "Deniz Ticareti Yönetmeliği",
                        "tur": "Kurum Yönetmeliği",
                    },
                    {
                        "mevzuatId": 300,
                        "ad": "Belirsiz Genel Düzenleme",
                        "tur": "Yönerge",
                    },
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    archive = tmp_path / "archive"
    archive.mkdir()
    (archive / "100_karayolu.pdf").write_bytes(b"not inspected")
    (archive / "200_deniz.pdf").write_bytes(b"not inspected")
    (archive / "999_eslesmeyen.pdf").write_bytes(b"not inspected")

    service = LegislationManifestService(project_root=tmp_path)
    manifest = service.build(records_path, archive)

    assert manifest.summary.manifest_record_count == 3
    assert manifest.summary.matched_pdf_count == 2
    assert manifest.summary.missing_pdf_count == 1
    assert manifest.summary.unmatched_archive_pdf_count == 1
    assert manifest.summary.candidate_for_active_rag_count == 1
    assert manifest.summary.approved_for_active_rag_count == 0
    assert all(not record.approved_for_active_rag for record in manifest.data)
    assert manifest.data[0].pdf_match_status == PdfMatchStatus.MATCHED
    assert manifest.data[2].pdf_match_status == PdfMatchStatus.MISSING

    output = tmp_path / "data" / "manifest.json"
    json_path, csv_path = service.write(manifest, output)
    assert json_path.exists()
    assert csv_path.exists()
    with csv_path.open(encoding="utf-8-sig", newline="") as source:
        rows = list(csv.DictReader(source))
    assert len(rows) == 3
    assert rows[0]["approved_for_active_rag"] == "false"
    assert "human_domain" in rows[0]


def test_manifest_rejects_duplicate_source_ids(tmp_path: Path) -> None:
    records = tmp_path / "records.json"
    records.write_text(
        json.dumps(
            {
                "data": [
                    {"mevzuatId": 1, "ad": "Bir", "tur": "Yönerge"},
                    {"mevzuatId": 1, "ad": "İki", "tur": "Yönerge"},
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    archive = tmp_path / "archive"
    archive.mkdir()

    with pytest.raises(CurationError, match="yinelenen mevzuat kimliği"):
        LegislationManifestService(project_root=tmp_path).build(records, archive)


def test_active_rag_approval_requires_complete_human_review_chain(
    tmp_path: Path,
) -> None:
    with pytest.raises(ValueError, match="güvenlik kapılarını"):
        LegislationManifestRecord(
            legislation_id=42,
            document_id="uab-kaysis-42",
            title="Karayolu Taşıma Yönetmeliği",
            document_type="Yönetmelik",
            local_pdfs=[str(tmp_path / "42.pdf")],
            pdf_match_status=PdfMatchStatus.MATCHED,
            domain=CurationDomain.ROAD_TRANSPORT,
            subdomain="transport_operations",
            classification_confidence=1.0,
            scope_status=ScopeStatus.ACTIVE,
            review_status=ReviewStatus.NEEDS_HUMAN_REVIEW,
            validity_status=ValidityStatus.NEEDS_VERIFICATION,
            approved_for_active_rag=True,
        )


def test_review_csv_round_trip_activates_only_fully_verified_record(
    tmp_path: Path,
) -> None:
    records_path = tmp_path / "mevzuatlar.json"
    records_path.write_text(
        json.dumps(
            {
                "data": [
                    {
                        "mevzuatId": 42,
                        "ad": "Karayolu Taşıma Yönetmeliği",
                        "tur": "Yönetmelik",
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    archive = tmp_path / "archive"
    archive.mkdir()
    pdf = archive / "42_karayolu.pdf"
    pdf.write_bytes(b"reviewed source")

    service = LegislationManifestService(project_root=tmp_path)
    manifest = service.build(records_path, archive)
    record = manifest.data[0]
    record.source_sha256 = "a" * 64
    record.source_bytes = pdf.stat().st_size
    record.text_layer_status = TextLayerStatus.AVAILABLE
    record.ocr_required = False
    _, review_path = service.write(manifest, tmp_path / "manifest.json")

    with review_path.open(encoding="utf-8-sig", newline="") as source:
        reader = csv.DictReader(source)
        rows = list(reader)
        fieldnames = reader.fieldnames
    rows[0].update(
        {
            "human_domain": CurationDomain.ROAD_TRANSPORT.value,
            "human_subdomain": "transport_operations",
            "scope_status": ScopeStatus.ACTIVE.value,
            "review_status": "approved",
            "validity_status": ValidityStatus.VERIFIED.value,
            "approved_for_active_rag": "true",
            "reviewed_by": "Test Doğrulayıcısı",
            "review_notes": "Kapsam ve yürürlük doğrulandı.",
        }
    )
    with review_path.open("w", encoding="utf-8-sig", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    reviewed = service.apply_review_csv(manifest, review_path)

    assert reviewed.data[0].approved_for_active_rag
    assert reviewed.data[0].reviewed_at is not None
    assert reviewed.data[0].activation_blockers() == []
    assert reviewed.summary.approved_for_active_rag_count == 1


def test_review_csv_rejects_changed_source_hash(tmp_path: Path) -> None:
    records_path = tmp_path / "mevzuatlar.json"
    records_path.write_text(
        json.dumps(
            {
                "data": [
                    {
                        "mevzuatId": 42,
                        "ad": "Karayolu Taşıma Yönetmeliği",
                        "tur": "Yönetmelik",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    archive = tmp_path / "archive"
    archive.mkdir()
    (archive / "42_karayolu.pdf").write_bytes(b"reviewed source")
    service = LegislationManifestService(project_root=tmp_path)
    manifest = service.build(records_path, archive)
    manifest.data[0].source_sha256 = "a" * 64
    _, review_path = service.write(manifest, tmp_path / "manifest.json")

    with review_path.open(encoding="utf-8-sig", newline="") as source:
        reader = csv.DictReader(source)
        rows = list(reader)
        fieldnames = reader.fieldnames
    rows[0]["source_sha256"] = "b" * 64
    with review_path.open("w", encoding="utf-8-sig", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    with pytest.raises(CurationError, match="SHA-256 değişmiş"):
        service.apply_review_csv(manifest, review_path)


def test_manifest_write_revalidates_bypassed_active_approval(tmp_path: Path) -> None:
    records_path = tmp_path / "mevzuatlar.json"
    records_path.write_text(
        json.dumps(
            {
                "data": [
                    {
                        "mevzuatId": 42,
                        "ad": "Karayolu Taşıma Yönetmeliği",
                        "tur": "Yönetmelik",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    archive = tmp_path / "archive"
    archive.mkdir()
    (archive / "42_karayolu.pdf").write_bytes(b"unreviewed source")
    service = LegislationManifestService(project_root=tmp_path)
    manifest = service.build(records_path, archive)
    manifest.data[0] = manifest.data[0].model_copy(
        update={"approved_for_active_rag": True}
    )

    with pytest.raises(CurationError, match="güvenlik doğrulamasını"):
        service.write(manifest, tmp_path / "invalid.json")

    assert not (tmp_path / "invalid.json").exists()


def test_curate_legislation_cli_writes_manifest(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    records = tmp_path / "records.json"
    records.write_text(
        json.dumps(
            {
                "data": [
                    {
                        "mevzuatId": 42,
                        "ad": "Araç Muayene İstasyonları Yönetmeliği",
                        "tur": "Yönetmelik",
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    archive = tmp_path / "archive"
    archive.mkdir()
    (archive / "42_arac.pdf").write_bytes(b"not inspected")
    output = tmp_path / "manifest.json"

    exit_code = main(
        [
            "curate-legislation",
            "--records",
            str(records),
            "--archive",
            str(archive),
            "--output",
            str(output),
        ]
    )

    result = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert output.exists()
    assert result["summary"]["manifest_record_count"] == 1
    assert result["summary"]["approved_for_active_rag_count"] == 0


def test_core_inventory_builds_reviewable_manifest_without_auto_approval(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pdf = tmp_path / "source.pdf"
    pdf.write_bytes(b"core inventory source")
    digest = sha256(pdf.read_bytes()).hexdigest()
    inventory = tmp_path / "inventory.json"
    inventory.write_text(
        json.dumps(
            {
                "sources": [
                    {
                        "document_id": "law-test-1",
                        "title": "Test Kanunu",
                        "document_type": "kanun",
                        "domain": "kgm_infrastructure",
                        "subdomain": "traffic_safety",
                        "local_path": "source.pdf",
                        "source_url": "https://example.test/law-test-1",
                        "bytes": pdf.stat().st_size,
                        "sha256": digest,
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    service = LegislationManifestService(project_root=tmp_path)

    def inspect(record: LegislationManifestRecord, _: Path) -> None:
        record.source_bytes = pdf.stat().st_size
        record.source_sha256 = digest
        record.text_layer_status = TextLayerStatus.AVAILABLE
        record.ocr_required = False

    monkeypatch.setattr(service, "_inspect_text_layer", inspect)
    manifest = service.build_core_inventory(inventory)

    assert manifest.summary.manifest_record_count == 1
    assert manifest.summary.candidate_for_active_rag_count == 1
    assert manifest.summary.approved_for_active_rag_count == 0
    assert manifest.data[0].document_id == "law-test-1"
    assert manifest.data[0].source_sha256 == digest
    assert manifest.data[0].scope_status == ScopeStatus.REVIEW_REQUIRED
    assert manifest.data[0].review_status == ReviewStatus.NEEDS_HUMAN_REVIEW


def test_core_inventory_rejects_source_hash_change(tmp_path: Path) -> None:
    (tmp_path / "source.pdf").write_bytes(b"changed source")
    inventory = tmp_path / "inventory.json"
    inventory.write_text(
        json.dumps(
            {
                "sources": [
                    {
                        "document_id": "law-test-1",
                        "title": "Test Kanunu",
                        "document_type": "kanun",
                        "domain": "kgm_infrastructure",
                        "subdomain": "traffic_safety",
                        "local_path": "source.pdf",
                        "sha256": "0" * 64,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(CurationError, match="SHA-256"):
        LegislationManifestService(project_root=tmp_path).build_core_inventory(
            inventory
        )
