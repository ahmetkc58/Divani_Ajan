import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import karayol_agent.api as api_module
from karayol_agent.config import Settings
from karayol_agent.orchestrator import EvrakOrchestrator

ROOT = Path(__file__).resolve().parents[1]


def build_client(monkeypatch, tmp_path: Path) -> TestClient:
    settings = Settings(
        project_root=ROOT,
        data_dir=ROOT / "data",
        templates_dir=ROOT / "templates",
        output_dir=tmp_path / "output",
        runtime_dir=tmp_path / "runtime",
    )
    monkeypatch.setattr(api_module, "orchestrator", EvrakOrchestrator(settings))
    return TestClient(api_module.app)


def test_backend_is_api_only_and_openapi_exposes_canonical_routes(
    monkeypatch, tmp_path: Path
) -> None:
    client = build_client(monkeypatch, tmp_path)

    root = client.get("/")
    schema = client.get("/openapi.json").json()

    assert root.headers["content-type"].startswith("application/json")
    assert root.json()["api_base"] == "/api/v1"
    assert client.get("/ui-assets/app.js").status_code == 404
    assert "/api/v1/system/health" in schema["paths"]
    assert "/api/v1/system/readiness" in schema["paths"]
    assert "/api/v1/processes/text" in schema["paths"]
    assert "/api/v1/processes/{document_id}/approval" in schema["paths"]
    assert "/health" not in schema["paths"]
    assert "/v1/process/text" not in schema["paths"]


def test_backend_allows_configured_frontend_origin_only(
    monkeypatch, tmp_path: Path
) -> None:
    client = build_client(monkeypatch, tmp_path)
    requested_headers = {
        "Origin": "http://127.0.0.1:3000",
        "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": "content-type",
    }

    allowed = client.options("/api/v1/processes/text", headers=requested_headers)
    denied = client.options(
        "/api/v1/processes/text",
        headers={**requested_headers, "Origin": "https://untrusted.example"},
    )

    assert allowed.status_code == 200
    assert allowed.headers["access-control-allow-origin"] == "http://127.0.0.1:3000"
    assert "access-control-allow-origin" not in denied.headers


def test_frontend_uses_only_the_versioned_rest_bridge() -> None:
    frontend = ROOT / "frontend"
    index = (frontend / "index.html").read_text(encoding="utf-8")
    script = (frontend / "static" / "app.js").read_text(encoding="utf-8")
    config = (frontend / "config.js").read_text(encoding="utf-8")

    assert "./static/app.css" in index
    assert "./config.js" in index
    assert 'apiBaseUrl: "http://127.0.0.1:8010"' in config
    for route in (
        "/api/v1/system/readiness",
        "/api/v1/processes/text",
        "/api/v1/processes/file",
        "/information",
        "/approval",
    ):
        assert route in script
    assert 'fetch("/ready"' not in script
    assert 'requestJson("/v1/process' not in script


def test_cors_configuration_rejects_wildcards() -> None:
    with pytest.raises(ValueError, match="joker"):
        Settings(cors_allowed_origins=("*",))


def test_frontend_swagger_handoff_matches_runtime_openapi() -> None:
    documented = json.loads((ROOT / "docs" / "swagger.json").read_text("utf-8"))

    assert documented == api_module.app.openapi()
    assert documented["openapi"] == "3.1.0"
    assert documented["servers"][0]["url"] == "http://127.0.0.1:8010"
    assert all(path.startswith("/api/v1/") for path in documented["paths"])
    operation_ids = [
        operation["operationId"]
        for methods in documented["paths"].values()
        for operation in methods.values()
    ]
    assert len(operation_ids) == len(set(operation_ids))
