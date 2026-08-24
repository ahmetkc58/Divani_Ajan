from pathlib import Path

from fastapi.testclient import TestClient

import karayol_agent.api as api_module
from karayol_agent.config import Settings
from karayol_agent.orchestrator import EvrakOrchestrator


ROOT = Path(__file__).resolve().parents[1]


def test_health_and_text_process(monkeypatch, tmp_path: Path) -> None:
    app_settings = Settings(
        project_root=ROOT,
        data_dir=ROOT / "data",
        templates_dir=ROOT / "templates",
        output_dir=tmp_path / "output",
        runtime_dir=tmp_path / "runtime",
    )
    monkeypatch.setattr(api_module, "orchestrator", EvrakOrchestrator(app_settings))
    client = TestClient(api_module.app)

    health = client.get("/health")
    assert health.status_code == 200
    assert health.json()["data_mode"] == "sentetik_demo"
    assert health.json()["retrieval_mode"] == "bm25"
    assert health.json()["retrieval_setup_warning"] is None
    ready = client.get("/ready")
    assert ready.status_code == 200
    assert ready.json()["status"] == "ready"
    assert ready.json()["retrieval_mode"] == "bm25"

    text = (ROOT / "examples" / "yol_bakim_talebi.txt").read_text(encoding="utf-8")
    response = client.post(
        "/v1/process/text",
        json={"text": text, "source_name": "api-ornek.txt"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["analysis"]["document_type"] == "yol_bakim_talebi"
    assert payload["routing"]["unit_id"] == "ORKGM-YB-001"


def test_hybrid_readiness_fails_when_active_corpus_is_missing(
    monkeypatch, tmp_path: Path
) -> None:
    app_settings = Settings(
        project_root=ROOT,
        data_dir=ROOT / "data",
        templates_dir=ROOT / "templates",
        output_dir=tmp_path / "output",
        runtime_dir=tmp_path / "runtime",
        retrieval_mode="hybrid",
        active_legislation_path=tmp_path / "missing-active-corpus.json",
    )
    monkeypatch.setattr(api_module, "orchestrator", EvrakOrchestrator(app_settings))

    response = TestClient(api_module.app).get("/ready")

    assert response.status_code == 503
    assert response.json()["status"] == "not_ready"
    assert "sentetik BM25 fallback" in response.json()["detail"]
