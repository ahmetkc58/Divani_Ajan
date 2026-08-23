from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from karayol_agent.cli import main
from karayol_agent.curation import (
    CurationDomain,
    CurationError,
    LegislationDomainClassifier,
    LegislationManifestService,
    PdfMatchStatus,
    ScopeStatus,
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


def test_curate_legislation_cli_writes_manifest(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
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
