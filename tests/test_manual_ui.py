import json
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
PARAPHRASE_TEXT = """Gönderen: Selin Örnek
Tarih: 23.08.2026
Konu: Sürüş yüzeyindeki derin oyuklar
Konum: Örnek İlçe, sanayi kavşağı yaklaşımı

Araç tekerlerinin içine girdiği derin oyuklar oluşmuştur. Bu bölümün düzeltilmesini istiyorum."""


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
    assert 'id="environment-badge"' in page.text
    assert 'id="health-pill" role="status" aria-live="polite"' in page.text
    assert "Paraphrase sınır testi" in page.text
    assert stylesheet.status_code == 200
    assert stylesheet.headers["content-type"].startswith("text/css")
    assert script.status_code == 200
    javascript_media_type = script.headers["content-type"].split(";", 1)[0]
    assert javascript_media_type in {"application/javascript", "text/javascript"}
    assert "handleInformationSubmit" in script.text
    assert "handleApprovalSubmit" in script.text


def test_manual_ui_uses_real_readiness_and_exposes_safety_contract(
    monkeypatch, tmp_path: Path
) -> None:
    client = build_client(monkeypatch, tmp_path)

    script = client.get("/ui-assets/app.js")

    assert script.status_code == 200
    assert 'fetch("/ready"' in script.text
    assert 'requestJson("/health")' not in script.text
    assert "readiness.ready !== true" in script.text
    assert "corpusModeLabels[readiness.corpus_mode]" in script.text
    assert "RAG HAZIR DEĞİL" in script.text

    # Alanlar sekmesi yalnız analiz alanlarını değil, zorunlu taslak girdilerini
    # de kendi durum ve kaynak bilgileriyle birlikte göstermelidir.
    assert '["sayi", state.draft.number]' in script.text
    assert '["imzalayan", state.draft.signer]' in script.text
    assert '["unvan", state.draft.signer_title]' in script.text
    assert "fieldSourceText(field)" in script.text

    # Bir retrieval eşleşmesi, snapshot'ın güncel/yürürlükte olduğu anlamına
    # gelmez. Kart bu üç ayrı kararı kullanıcıya açıkça sunmalıdır.
    assert 'reference.corpus_mode === "competition_snapshot"' in script.text
    assert "reference.currentness_verified === true" in script.text
    assert "reference.legal_reliance_allowed === true" in script.text
    assert "Snapshot uyarısı" in script.text
    assert "reference.relevance_accepted === true" in script.text
    assert "Sorgu alakası" in script.text
    assert "Alaka gerekçesi" in script.text
    assert "Sorgu kapısı" in script.text
    assert "relevance_query_reasons" in script.text
    assert "Chunk: ${escapeHtml(reference.chunk_id)}" in script.text
    assert "Sayfa izi yok" in script.text


def test_manual_ui_exposes_llm_roles_and_outcomes_in_flow_tab(
    monkeypatch, tmp_path: Path
) -> None:
    client = build_client(monkeypatch, tmp_path)

    script = client.get("/ui-assets/app.js")

    assert script.status_code == 200
    assert 'document_understanding: "LLM Yapılandırılmış Anlama Ajanı"' in script.text
    assert 'adjudicator: "LLM Karar Ajanı (Adjudicator)"' in script.text
    assert "LLM orkestrasyon adımları" in script.text
    assert "llmTrace?.steps || []" in script.text
    assert "llmStatusLabels[step.status]" in script.text
    assert "step.provider || llmTrace.provider" in script.text
    assert "step.model || llmTrace.model" in script.text
    assert "step.data_classification" in script.text
    assert "step.external_data_allowed" in script.text
    assert "step.network_attempted" in script.text
    assert "step.failure_code" in script.text
    assert "step.retryable" in script.text
    assert "step.decision_applied === true" in script.text
    assert "step.decision_applied === false" in script.text
    assert "step.detail" in script.text
    assert "Ağ çağrısından önce veri güvenliği politikası uygulandı" in script.text


def test_ui_demo_texts_are_bound_to_server_attested_fixtures(
    monkeypatch, tmp_path: Path
) -> None:
    client = build_client(monkeypatch, tmp_path)
    script = client.get("/ui-assets/app.js")
    fixture_payload = json.loads(
        (ROOT / "data" / "synthetic_ui_fixtures.json").read_text("utf-8")
    )

    assert script.status_code == 200
    assert fixture_payload["data_classification"] == "synthetic"
    assert fixture_payload["records"][0]["text"] == MAINTENANCE_TEXT
    for record in fixture_payload["records"]:
        assert record["text"] in script.text


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
            "/v1/process/file?compile_pdf=false",
            files={"file": (source_path.name, source_file, "text/plain")},
        )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")
    payload = response.json()
    assert payload["document_id"].startswith("EVR-")
    assert payload["source_name"] == source_path.name
    assert payload["raw_text"] == source_path.read_text(encoding="utf-8").strip()
    assert payload["status"] == "eksik_bilgi_bekleniyor"
    assert payload["analysis"]["document_type"] == "yol_bakim_talebi"
    assert payload["routing"]["unit_id"] == "ORKGM-YB-001"
    assert payload["template_decision"]["template_id"] == "ust_yazi_v1"
    assert payload["artifact"]["compiled"] is False
    assert payload["artifact"]["pdf_path"] is None
    assert payload["artifact"]["tex_download_url"] == (
        f"/v1/process/{payload['document_id']}/artifacts/tex"
    )

    persisted = client.get(f"/v1/process/{payload['document_id']}")
    assert persisted.status_code == 200
    assert persisted.json() == payload


def test_paraphrase_scenario_preserves_known_rule_based_boundary(
    monkeypatch, tmp_path: Path
) -> None:
    client = build_client(monkeypatch, tmp_path)

    response = client.post(
        "/v1/process/text",
        json={
            "text": PARAPHRASE_TEXT,
            "source_name": "paraphrase-arayuz-senaryosu.txt",
            "compile_pdf": False,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    # This intentionally records scenario C's current lexical-MVP limitation.
    assert payload["analysis"]["document_type"] == "genel_basvuru"
    assert payload["routing"]["unit_id"] == "ORKGM-EB-001"
    assert payload["template_decision"]["template_id"] == "cevap_yazisi_v1"
