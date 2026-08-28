from pathlib import Path

import pymupdf
from fastapi.testclient import TestClient

import karayol_agent.api as api_module
from karayol_agent.config import Settings
from karayol_agent.orchestrator import EvrakOrchestrator


ROOT = Path(__file__).resolve().parents[1]


def build_client(monkeypatch, tmp_path: Path) -> TestClient:
    app_settings = Settings(
        project_root=ROOT,
        data_dir=ROOT / "data",
        templates_dir=ROOT / "templates",
        output_dir=tmp_path / "output",
        runtime_dir=tmp_path / "runtime",
    )
    monkeypatch.setattr(api_module, "orchestrator", EvrakOrchestrator(app_settings))
    return TestClient(api_module.app)


def make_pdf(path: Path, lines: list[str]) -> None:
    document = pymupdf.open()
    page = document.new_page()
    for index, line in enumerate(lines):
        page.insert_text((72, 72 + index * 18), line, fontsize=11)
    document.save(path)
    document.close()


def test_short_text_layer_pdf_is_accepted(monkeypatch, tmp_path: Path) -> None:
    # Regression: ISSUE-004 - kısa ama geçerli metin PDF'si gereksiz OCR sonrası reddediliyordu.
    # Found by /qa on 2026-08-23
    # Report: .gstack/qa-reports/qa-report-localhost-2026-08-23.md
    client = build_client(monkeypatch, tmp_path)
    pdf_path = tmp_path / "kisa-evrak.pdf"
    make_pdf(
        pdf_path,
        [
            "Adi Soyadi: Test User",
            "Konu: Asfalt cukuru",
            "Konum: Test yolu 1. km",
            "Tarih: 23.08.2026",
            "Yol bakim ve onarim yapilmasini talep ediyorum.",
        ],
    )

    response = client.post(
        "/v1/process/file",
        files={"file": ("kisa-evrak.pdf", pdf_path.read_bytes(), "application/pdf")},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["source_name"] == "kisa-evrak.pdf"
    assert "Asfalt cukuru" in payload["raw_text"]

