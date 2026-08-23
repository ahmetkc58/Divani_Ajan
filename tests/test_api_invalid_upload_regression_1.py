from pathlib import Path

from fastapi.testclient import TestClient

import karayol_agent.api as api_module
from karayol_agent.config import Settings
from karayol_agent.orchestrator import EvrakOrchestrator


ROOT = Path(__file__).resolve().parents[1]
REPORT = ".gstack/qa-reports/qa-report-localhost-2026-08-23.md"


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


def test_corrupt_pdf_returns_actionable_422(monkeypatch, tmp_path: Path) -> None:
    # Regression: ISSUE-001 - bozuk PDF yüklemesi 500 Internal Server Error üretiyordu.
    # Found by /qa on 2026-08-23
    # Report: .gstack/qa-reports/qa-report-localhost-2026-08-23.md
    client = build_client(monkeypatch, tmp_path)

    response = client.post(
        "/v1/process/file",
        files={"file": ("bozuk.pdf", b"%PDF-1.7\ninvalid", "application/pdf")},
    )

    assert response.status_code == 422
    assert "bozuk" in response.json()["detail"].lower()


def test_invalid_utf8_text_returns_actionable_422(monkeypatch, tmp_path: Path) -> None:
    # Regression: ISSUE-001 - belge ayrıştırma hataları kullanıcı hatasına çevrilmelidir.
    # Found by /qa on 2026-08-23
    # Report: .gstack/qa-reports/qa-report-localhost-2026-08-23.md
    client = build_client(monkeypatch, tmp_path)

    response = client.post(
        "/v1/process/file",
        files={"file": ("bozuk.txt", b"\xff\xfe\xfa", "text/plain")},
    )

    assert response.status_code == 422
    assert "utf-8" in response.json()["detail"].lower()

