from pathlib import Path

from fastapi.testclient import TestClient

import karayol_agent.api as api_module
from karayol_agent.config import Settings
from karayol_agent.orchestrator import EvrakOrchestrator


ROOT = Path(__file__).resolve().parents[1]


def test_unknown_information_field_is_rejected(monkeypatch, tmp_path: Path) -> None:
    # Regression: ISSUE-002 - bilinmeyen alanlar sessizce kabul edilip süreç yenileniyordu.
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
    document_id = client.post(
        "/v1/process/text", json={"text": text}
    ).json()["document_id"]

    response = client.post(
        f"/v1/process/{document_id}/information",
        json={"fields": {"bilinmeyen_alan": "değer"}},
    )

    assert response.status_code == 422
    detail = response.json()["detail"]
    assert "bilinmeyen_alan" in detail
    assert "İzin verilen alanlar" in detail

