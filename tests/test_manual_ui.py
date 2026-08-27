import json
from pathlib import Path

from fastapi.testclient import TestClient

import karayol_agent.api as api_module
from karayol_agent.config import Settings
from karayol_agent.orchestrator import EvrakOrchestrator

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"
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

    page = (FRONTEND / "index.html").read_text(encoding="utf-8")
    stylesheet = (FRONTEND / "static" / "app.css").read_text(encoding="utf-8")
    script = (FRONTEND / "static" / "app.js").read_text(encoding="utf-8")

    backend_root = client.get("/")
    assert backend_root.status_code == 200
    assert backend_root.json()["service"] == "karayol-evrak-agent-backend"
    assert client.get("/ui-assets/app.js").status_code == 404
    assert "YolYaz — Evrak Test Masası" in page
    assert 'id="process-form"' in page
    assert 'id="environment-badge"' in page
    assert 'id="health-pill" role="status" aria-live="polite"' in page
    assert "Paraphrase sınır testi" in page
    assert "Standalone frontend styles" in stylesheet
    assert "handleInformationSubmit" in script
    assert "handleApprovalSubmit" in script
    assert "PDF taslağını indir" in script
    assert "LaTeX taslağını indir" not in script
    assert 'id="compile-pdf"' not in page
    assert "compile_pdf: true" in script


def test_manual_ui_uses_real_readiness_and_exposes_safety_contract(
    monkeypatch, tmp_path: Path
) -> None:
    script = (FRONTEND / "static" / "app.js").read_text(encoding="utf-8")

    assert 'apiUrl("/api/v1/system/readiness")' in script
    assert 'requestJson("/health")' not in script
    assert "readiness.ready !== true" in script
    assert "corpusModeLabels[readiness.corpus_mode]" in script
    assert "RAG HAZIR DEĞİL" in script

    # Alanlar sekmesi yalnız analiz alanlarını değil, zorunlu taslak girdilerini
    # de kendi durum ve kaynak bilgileriyle birlikte göstermelidir.
    assert '["sayi", state.draft.number]' in script
    assert '["imzalayan", state.draft.signer]' in script
    assert '["unvan", state.draft.signer_title]' in script
    assert "fieldSourceText(field)" in script

    # Bir retrieval eşleşmesi, snapshot'ın güncel/yürürlükte olduğu anlamına
    # gelmez. Kart bu üç ayrı kararı kullanıcıya açıkça sunmalıdır.
    assert 'reference.corpus_mode === "competition_snapshot"' in script
    assert "reference.currentness_verified === true" in script
    assert "reference.legal_reliance_allowed === true" in script
    assert "Snapshot uyarısı" in script
    assert "reference.relevance_accepted === true" in script
    assert "Sorgu alakası" in script
    assert "Alaka gerekçesi" in script
    assert "Sorgu kapısı" in script
    assert "relevance_query_reasons" in script
    assert "Chunk: ${escapeHtml(reference.chunk_id)}" in script
    assert "Sayfa izi yok" in script


def test_manual_ui_exposes_llm_roles_and_outcomes_in_flow_tab(
    monkeypatch, tmp_path: Path
) -> None:
    script = (FRONTEND / "static" / "app.js").read_text(encoding="utf-8")

    assert 'llm1_classification: "LLM1 — Sınıflandırma Ajanı"' in script
    assert 'llm2_required_data: "LLM2 — Eksik Veri Ajanı"' in script
    assert 'adjudicator: "LLM Karar Ajanı (Adjudicator)"' in script
    assert "LLM orkestrasyon adımları" in script
    assert "llmTrace?.steps || []" in script
    assert "llmStatusLabels[step.status]" in script
    assert "step.provider || llmTrace.provider" in script
    assert "step.model || llmTrace.model" in script
    assert "step.data_classification" in script
    assert "step.external_data_allowed" in script
    assert "step.local_execution" in script
    assert "yerel Ollama (cihaz dışına veri çıkışı yok)" in script
    assert "step.network_attempted" in script
    assert "step.failure_code" in script
    assert "step.retryable" in script
    assert "step.decision_applied === true" in script
    assert "step.decision_applied === false" in script
    assert "step.detail" in script
    assert "Ağ çağrısından önce veri güvenliği politikası uygulandı" in script


def test_ui_demo_texts_are_bound_to_server_attested_fixtures(
    monkeypatch, tmp_path: Path
) -> None:
    script = (FRONTEND / "static" / "app.js").read_text(encoding="utf-8")
    fixture_payload = json.loads(
        (ROOT / "data" / "synthetic_ui_fixtures.json").read_text("utf-8")
    )

    assert fixture_payload["data_classification"] == "synthetic"
    assert fixture_payload["records"][0]["text"] == MAINTENANCE_TEXT
    for record in fixture_payload["records"]:
        assert record["text"] in script


def test_primary_manual_scenario_reaches_approval_and_download(
    monkeypatch, tmp_path: Path
) -> None:
    client = build_client(monkeypatch, tmp_path)

    process_response = client.post(
        "/api/v1/processes/text",
        json={
            "text": MAINTENANCE_TEXT,
            "source_name": "maintenance-arayuz-senaryosu.txt",
            "compile_pdf": True,
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
        f"/api/v1/processes/{document_id}/information",
        json={
            "fields": {
                "sayi": "E-67915368-903.07.02-42",
                "imzalayan": "Mehmet Demir",
                "unvan": "Şube Müdürü",
            },
            "compile_pdf": True,
        },
    )
    assert information_response.status_code == 200
    ready = information_response.json()
    assert ready["status"] == "yanit_stratejisi_bekleniyor"
    assert ready["missing_information"] == []
    assert ready["compliance"]["passed"] is True
    assert ready["response_strategy_options"]

    strategy_response = client.post(
        f"/api/v1/processes/{document_id}/response-strategy",
        json={
            "option_id": ready["response_strategy_options"][0]["option_id"],
            "compile_pdf": True,
        },
    )
    assert strategy_response.status_code == 200
    ready = strategy_response.json()
    assert ready["status"] == "kullanici_onayi_bekleniyor"

    approval_response = client.post(
        f"/api/v1/processes/{document_id}/approval",
        json={"approved_by": "Yetkili Demo Kullanıcısı"},
    )
    assert approval_response.status_code == 200
    completed = approval_response.json()
    assert completed["status"] == "tamamlandi"

    assert completed["artifact"]["compiled"] is True
    assert completed["artifact"]["pdf_download_url"]
    pdf_response = client.get(completed["artifact"]["pdf_download_url"])
    assert pdf_response.status_code == 200
    assert pdf_response.headers["content-type"].startswith("application/pdf")
    assert "attachment" in pdf_response.headers["content-disposition"]
    assert pdf_response.content.startswith(b"%PDF")


def test_file_upload_path_matches_primary_scenario(monkeypatch, tmp_path: Path) -> None:
    client = build_client(monkeypatch, tmp_path)
    source_path = ROOT / "examples" / "yol_bakim_talebi.txt"

    with source_path.open("rb") as source_file:
        response = client.post(
            "/api/v1/processes/file?compile_pdf=false",
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
        f"/api/v1/processes/{payload['document_id']}/artifacts/tex"
    )

    persisted = client.get(f"/api/v1/processes/{payload['document_id']}")
    assert persisted.status_code == 200
    assert persisted.json() == payload


def test_paraphrase_scenario_uses_concept_signals_for_road_maintenance(
    monkeypatch, tmp_path: Path
) -> None:
    client = build_client(monkeypatch, tmp_path)

    response = client.post(
        "/api/v1/processes/text",
        json={
            "text": PARAPHRASE_TEXT,
            "source_name": "paraphrase-arayuz-senaryosu.txt",
            "compile_pdf": False,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["analysis"]["document_type"] == "yol_bakim_talebi"
    assert payload["routing"]["unit_id"] == "ORKGM-YB-001"
    assert payload["template_decision"]["template_id"] == "ust_yazi_v1"
