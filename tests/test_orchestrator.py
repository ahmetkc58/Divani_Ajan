from pathlib import Path

import pytest

from karayol_agent.config import Settings
from karayol_agent.orchestrator import EvrakOrchestrator, ProcessValidationError
from karayol_agent.schemas import ComplianceResult, ProcessStatus


ROOT = Path(__file__).resolve().parents[1]


def build_test_orchestrator(tmp_path: Path) -> EvrakOrchestrator:
    app_settings = Settings(
        project_root=ROOT,
        data_dir=ROOT / "data",
        templates_dir=ROOT / "templates",
        output_dir=tmp_path / "output",
        runtime_dir=tmp_path / "runtime",
    )
    return EvrakOrchestrator(app_settings)


def test_complete_multi_agent_flow_and_approval(tmp_path: Path) -> None:
    orchestrator = build_test_orchestrator(tmp_path)
    state = orchestrator.process_file(ROOT / "examples" / "yol_bakim_talebi.txt")

    assert state.status == ProcessStatus.WAITING_FOR_INFO
    assert state.analysis is not None
    assert state.analysis.document_type == "talep"
    assert state.analysis.fields["gonderen"].value == "Ayşe Yılmaz"
    assert state.analysis.fields["konu"].value == "D-100 bağlantı yolundaki asfalt bozulması"
    assert state.analysis.fields["konum"].value == (
        "Örnek İl, Örnek İlçe, D-100 bağlantı yolu 12. kilometre"
    )
    assert state.routing is not None
    assert state.routing.unit_id == "ORKGM-YB-001"
    assert state.template_decision is not None
    assert state.template_decision.template_id == "ust_yazi_v1"
    assert state.artifact is not None
    assert Path(state.artifact.tex_path).exists()
    assert state.missing_information == ["sayi", "imzalayan", "unvan"]

    state = orchestrator.provide_information(
        state.document_id,
        {
            "sayi": "E-67915368-903.07.02-42",
            "imzalayan": "Mehmet Demir",
            "unvan": "Şube Müdürü",
        },
    )
    assert state.status == ProcessStatus.WAITING_FOR_APPROVAL
    assert state.draft is not None
    assert state.draft.missing_fields == []
    assert state.compliance is not None and state.compliance.passed

    state = orchestrator.approve(state.document_id, "Yetkili Test Kullanıcısı")
    assert state.status == ProcessStatus.COMPLETED
    assert not state.pending_actions


def test_missing_source_fields_selects_information_request(tmp_path: Path) -> None:
    orchestrator = build_test_orchestrator(tmp_path)
    state = orchestrator.process_file(ROOT / "examples" / "eksik_trafik_bildirimi.txt")

    assert state.analysis is not None
    assert state.analysis.document_type == "talep"
    assert state.analysis.missing_fields == ["gonderen", "konum"]
    assert state.routing is not None
    assert state.routing.unit_id == "ORKGM-TG-001"
    assert state.template_decision is not None
    assert state.template_decision.template_id == "eksik_bilgi_talebi_v1"
    assert state.status == ProcessStatus.WAITING_FOR_INFO
    assert state.missing_information == [
        "sayi",
        "imzalayan",
        "unvan",
        "tarih",
    ]

    state = orchestrator.provide_information(
        state.document_id,
        {
            "sayi": "E-67915368-903.07.02-77",
            "imzalayan": "Mert Demir",
            "unvan": "Şube Müdürü",
            "tarih": "24.08.2026",
        },
    )

    assert state.analysis.missing_fields == ["gonderen", "konum"]
    assert state.missing_information == []
    assert state.template_decision is not None
    assert state.template_decision.template_id == "eksik_bilgi_talebi_v1"
    assert state.status == ProcessStatus.WAITING_FOR_APPROVAL
    assert state.draft is not None
    assert state.draft.missing_fields == []
    assert state.compliance is not None and state.compliance.passed


def test_latex_user_content_is_escaped(tmp_path: Path) -> None:
    orchestrator = build_test_orchestrator(tmp_path)
    state = orchestrator.process_file(ROOT / "examples" / "yol_bakim_talebi.txt")
    state = orchestrator.provide_information(
        state.document_id,
        {
            "konu": r"Deneme \input{gizli} & yüzde %",
            "sayi": "2026_42",
            "imzalayan": "Ali & Veli",
            "unvan": "Müdür",
        },
    )

    assert state.artifact is not None
    rendered = Path(state.artifact.tex_path).read_text(encoding="utf-8")
    assert r"\input{gizli}" not in rendered
    assert r"\textbackslash{}input\{gizli\}" in rendered
    assert r"Ali \& Veli" in rendered
    assert r"2026\_42" in rendered


def test_failed_compliance_is_not_presented_for_approval(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    orchestrator = build_test_orchestrator(tmp_path)
    state = orchestrator.process_file(ROOT / "examples" / "yol_bakim_talebi.txt")
    compliance_error = "Seçilen şablon ile taslak şablonu uyuşmuyor."
    monkeypatch.setattr(
        orchestrator.compliance,
        "run",
        lambda *_args: ComplianceResult(
            passed=False,
            score=0.72,
            errors=[compliance_error],
        ),
    )

    state = orchestrator.provide_information(
        state.document_id,
        {
            "sayi": "E-67915368-903.07.02-42",
            "imzalayan": "Mehmet Demir",
            "unvan": "Şube Müdürü",
        },
    )

    assert state.status == ProcessStatus.ERROR
    assert state.missing_information == []
    assert "onayla" not in state.possible_actions
    assert state.possible_actions == ["taslagi_duzenle", "reddet"]
    assert compliance_error in " ".join(state.pending_actions)
    assert "uygunluk" in state.next_step.casefold()
    assert "onay" in state.events[-1].message.casefold()

    with pytest.raises(ProcessValidationError, match="Uygunluk denetimini geçmeyen"):
        orchestrator.approve(state.document_id, "Yetkili Test Kullanıcısı")
