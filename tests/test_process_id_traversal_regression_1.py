from pathlib import Path

from fastapi.testclient import TestClient

import karayol_agent.api as api_module
from karayol_agent.config import Settings
from karayol_agent.orchestrator import EvrakOrchestrator


ROOT = Path(__file__).resolve().parents[1]


def test_backslash_path_traversal_cannot_read_process(monkeypatch, tmp_path: Path) -> None:
    # Regression: ISSUE-007 - Windows ters eğik çizgileriyle süreç dizini aşılabiliyordu.
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

    normal = client.get(f"/v1/process/{document_id}")
    traversal = client.get(
        f"/v1/process/..%5Cprocesses%5C{document_id}"
    )

    assert normal.status_code == 200
    assert traversal.status_code == 404

