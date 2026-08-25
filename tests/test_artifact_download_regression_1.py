from pathlib import Path

from fastapi.testclient import TestClient

import karayol_agent.api as api_module
from karayol_agent.config import Settings
from karayol_agent.orchestrator import EvrakOrchestrator


ROOT = Path(__file__).resolve().parents[1]


def test_generated_tex_can_be_downloaded_but_missing_pdf_is_404(
    monkeypatch, tmp_path: Path
) -> None:
    # Regression: ISSUE-005 - API çıktının yerel yolunu veriyor ama indirme ucu sunmuyordu.
    # Found by /qa on 2026-08-23
    # Report: .gstack/qa-reports/qa-report-localhost-2026-08-23.md
    app_settings = Settings(
        project_root=ROOT,
        data_dir=ROOT / "data",
        templates_dir=ROOT / "templates",
        output_dir=tmp_path / "output",
        runtime_dir=tmp_path / "runtime",
    )
    monkeypatch.setattr(api_module, "orchestrator", EvrakOrchestrator(app_settings))
    client = TestClient(api_module.app)
    text = (ROOT / "examples" / "yol_bakim_talebi.txt").read_text(encoding="utf-8")
    payload = client.post("/v1/process/text", json={"text": text}).json()
    document_id = payload["document_id"]

    tex_response = client.get(payload["artifact"]["tex_download_url"])
    pdf_response = client.get(f"/v1/process/{document_id}/artifacts/pdf")

    assert tex_response.status_code == 200
    assert tex_response.headers["content-type"].startswith("application/x-tex")
    assert tex_response.headers["x-content-type-options"] == "nosniff"
    assert "\\documentclass" in tex_response.text
    assert pdf_response.status_code == 404
    assert "PDF çıktısı bulunmuyor" in pdf_response.json()["detail"]


def test_pdf_is_generated_without_a_latex_installation(
    monkeypatch, tmp_path: Path
) -> None:
    app_settings = Settings(
        project_root=ROOT,
        data_dir=ROOT / "data",
        templates_dir=ROOT / "templates",
        output_dir=tmp_path / "output",
        runtime_dir=tmp_path / "runtime",
    )
    monkeypatch.setattr(api_module, "orchestrator", EvrakOrchestrator(app_settings))
    monkeypatch.setattr(
        "karayol_agent.latex.renderer.LatexRenderer._find_compiler",
        staticmethod(lambda: None),
    )
    client = TestClient(api_module.app)
    text = (ROOT / "examples" / "yol_bakim_talebi.txt").read_text(encoding="utf-8")

    payload = client.post(
        "/v1/process/text", json={"text": text, "compile_pdf": True}
    ).json()
    response = client.get(payload["artifact"]["pdf_download_url"])

    assert payload["artifact"]["compiled"] is True
    assert payload["artifact"]["compiler"] == "reportlab"
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/pdf")
    assert response.content.startswith(b"%PDF")
