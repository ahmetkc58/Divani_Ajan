from pathlib import Path

from fastapi.testclient import TestClient

import karayol_agent.api as api_module
from karayol_agent.config import Settings
from karayol_agent.orchestrator import EvrakOrchestrator


ROOT = Path(__file__).resolve().parents[1]


def test_completed_process_cannot_be_changed_or_approved_twice(
    monkeypatch, tmp_path: Path
) -> None:
    # Regression: ISSUE-003 - onaylanmış evrak bilgi güncellemesiyle değiştirilebiliyordu.
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
    client.post(
        f"/v1/process/{document_id}/information",
        json={
            "fields": {
                    "sayi": "E-67915368-903.07.02-3",
                "imzalayan": "Yetkili Kullanıcı",
                "unvan": "Şube Müdürü",
            }
        },
    )
    approved = client.post(
        f"/v1/process/{document_id}/approve",
        json={"approved_by": "QA Yetkilisi"},
    )
    original_subject = approved.json()["draft"]["subject"]["value"]

    mutation = client.post(
        f"/v1/process/{document_id}/information",
        json={"fields": {"konu": "Onay sonrası değişiklik"}},
    )
    repeated_approval = client.post(
        f"/v1/process/{document_id}/approve",
        json={"approved_by": "İkinci Yetkili"},
    )
    persisted = client.get(f"/v1/process/{document_id}").json()

    assert mutation.status_code == 422
    assert "değiştirilemez" in mutation.json()["detail"]
    assert repeated_approval.status_code == 422
    assert persisted["status"] == "tamamlandi"
    assert persisted["draft"]["subject"]["value"] == original_subject
