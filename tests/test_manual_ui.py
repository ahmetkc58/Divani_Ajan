from pathlib import Path

from fastapi.testclient import TestClient

import karayol_agent.api as api_module
from karayol_agent.config import Settings
from karayol_agent.orchestrator import EvrakOrchestrator


ROOT = Path(__file__).resolve().parents[1]
MAINTENANCE_TEXT = """Gönderen: Ayşe Örnek
Tarih: 23.08.2026
Konu: D-100 bağlantı yolundaki asfalt bozulması
Konum: Örnek İl, Örnek İlçe, D-100 bağlantı yolu 12. kilometre
Telefon: 0555 111 22 33

Belirtilen konumda yol yüzeyinde geniş çukurlar ve asfalt bozulmaları oluşmuştur.
Trafik güvenliği açısından gerekli yol bakım ve onarım çalışmasının yapılmasını talep ediyorum."""


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


def test_manual_test_interface_and_local_assets(monkeypatch, tmp_path: Path) -> None:
    client = build_client(monkeypatch, tmp_path)

    page = client.get("/")
    stylesheet = client.get("/ui-assets/app.css")
    script = client.get("/ui-assets/app.js")

    assert page.status_code == 200
    assert page.headers["content-type"].startswith("text/html")
    assert page.headers["cache-control"] == "no-store"
    assert "default-src 'self'" in page.headers["content-security-policy"]
    assert page.headers["x-frame-options"] == "DENY"
    assert "YolYaz — Evrak Test Masası" in page.text
    assert 'id="process-form"' in page.text
    assert "Paraphrase sınır testi" in page.text
    assert stylesheet.status_code == 200
    assert stylesheet.headers["content-type"].startswith("text/css")
    assert script.status_code == 200
    javascript_media_type = script.headers["content-type"].split(";", 1)[0]
    assert javascript_media_type in {"application/javascript", "text/javascript"}
    assert "handleInformationSubmit" in script.text
    assert "handleApprovalSubmit" in script.text


def test_primary_manual_scenario_reaches_approval_and_download(
    monkeypatch, tmp_path: Path
) -> None:
    client = build_client(monkeypatch, tmp_path)

    process_response = client.post(
        "/v1/process/text",
        json={
            "text": MAINTENANCE_TEXT,
            "source_name": "maintenance-arayuz-senaryosu.txt",
            "compile_pdf": False,
        },
    )
    assert process_response.status_code == 200
    initial = process_response.json()
    assert initial["analysis"]["document_type"] == "yol_bakim_talebi"
    assert initial["routing"]["unit_id"] == "ORKGM-YB-001"
    assert initial["template_decision"]["template_id"] == "ust_yazi_v1"
    assert initial["missing_information"] == ["sayi", "imzalayan", "unvan"]

    document_id = initial["document_id"]
    information_response = client.post(
        f"/v1/process/{document_id}/information",
        json={
            "fields": {
                "sayi": "2026/42",
                "imzalayan": "Mehmet Demir",
                "unvan": "Şube Müdürü",
            },
            "compile_pdf": False,
        },
    )
    assert information_response.status_code == 200
    ready = information_response.json()
    assert ready["status"] == "kullanici_onayi_bekleniyor"
    assert ready["missing_information"] == []
    assert ready["compliance"]["passed"] is True

    approval_response = client.post(
        f"/v1/process/{document_id}/approve",
        json={"approved_by": "Yetkili Demo Kullanıcısı"},
    )
    assert approval_response.status_code == 200
    completed = approval_response.json()
    assert completed["status"] == "tamamlandi"

    tex_response = client.get(completed["artifact"]["tex_download_url"])
    assert tex_response.status_code == 200
    assert tex_response.headers["content-type"].startswith("application/x-tex")
    assert "attachment" in tex_response.headers["content-disposition"]
    assert "\\documentclass" in tex_response.text


def test_file_upload_path_matches_primary_scenario(monkeypatch, tmp_path: Path) -> None:
    client = build_client(monkeypatch, tmp_path)
    source_path = ROOT / "examples" / "yol_bakim_talebi.txt"

    with source_path.open("rb") as source_file:
        response = client.post(
            "/v1/process/file",
            files={"file": (source_path.name, source_file, "text/plain")},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["analysis"]["document_type"] == "yol_bakim_talebi"
    assert payload["routing"]["unit_id"] == "ORKGM-YB-001"
