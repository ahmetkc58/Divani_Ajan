from pathlib import Path

from karayol_agent.config import Settings
from karayol_agent.orchestrator import EvrakOrchestrator


ROOT = Path(__file__).resolve().parents[1]


def test_draft_has_one_unambiguous_official_closing(tmp_path: Path) -> None:
    # Regression: ISSUE-006 - taslak "arz/rica" biçiminde iki kapanışı birlikte bırakıyordu.
    # Found by /qa on 2026-08-23
    # Report: .gstack/qa-reports/qa-report-localhost-2026-08-23.md
    orchestrator = EvrakOrchestrator(
        Settings(
            project_root=ROOT,
            data_dir=ROOT / "data",
            templates_dir=ROOT / "templates",
            output_dir=tmp_path / "output",
            runtime_dir=tmp_path / "runtime",
        )
    )

    state = orchestrator.process_file(ROOT / "examples" / "yol_bakim_talebi.txt")

    assert state.draft is not None
    assert state.draft.paragraphs[-1] == "Gereğini rica ederim."
    assert state.draft.closing == "Gereğini rica ederim."
    assert state.draft.authority_relation == "subordinate_internal"
    assert all("arz/rica" not in paragraph for paragraph in state.draft.paragraphs)


def test_official_sections_are_rendered_and_conflicting_closing_is_rejected(
    tmp_path: Path,
) -> None:
    orchestrator = EvrakOrchestrator(
        Settings(
            project_root=ROOT,
            data_dir=ROOT / "data",
            templates_dir=ROOT / "templates",
            output_dir=tmp_path / "output",
            runtime_dir=tmp_path / "runtime",
        )
    )
    state = orchestrator.process_file(ROOT / "examples" / "yol_bakim_talebi.txt")
    state = orchestrator.provide_information(
        state.document_id,
        {
            "sayi": "2026/42",
            "imzalayan": "Mehmet Demir",
            "unvan": "Şube Müdürü",
            "ilgi": "12.08.2026 tarihli başvuru",
            "ekler": "Konum krokisi;Fotoğraf",
            "dagitim": "Bakım Şefliği;Trafik Şefliği",
            "iletisim": "bilgi@example.test;0312 000 00 00",
            "paraf": "A. Uzman / 25.08.2026",
            "elektronik_imza": "Güvenli elektronik imza ile imzalanacaktır.",
        },
    )

    assert state.compliance is not None and state.compliance.passed
    assert state.draft is not None
    assert state.draft.attachments == ["Konum krokisi", "Fotoğraf"]
    rendered = Path(state.artifact.tex_path).read_text(encoding="utf-8")
    for heading in ("İlgi:", "Ekler", "Dağıtım", "Paraf/Koordinasyon"):
        assert heading in rendered
    assert "Belge üstverisi" not in rendered
    assert "Doğrulanan kaynaklar" not in rendered

    state.draft.authority_relation = "superior"
    result = orchestrator.compliance.run(state.draft, state.template_decision)
    assert result.passed is False
    assert any("kapanış" in error for error in result.errors)


def test_empty_optional_and_internal_sections_are_omitted(tmp_path: Path) -> None:
    orchestrator = EvrakOrchestrator(
        Settings(
            project_root=ROOT,
            data_dir=ROOT / "data",
            templates_dir=ROOT / "templates",
            output_dir=tmp_path / "output",
            runtime_dir=tmp_path / "runtime",
        )
    )

    state = orchestrator.process_file(ROOT / "examples" / "yol_bakim_talebi.txt")
    rendered = Path(state.artifact.tex_path).read_text(encoding="utf-8")

    for hidden_text in (
        "İlgi:",
        "Ekler",
        "Dağıtım",
        "Paraf/Koordinasyon",
        "Elektronik imza",
        "Belge üstverisi",
        "Doğrulanan kaynaklar",
        "Taslak hazırlanırken",
        "Kaynak izi olarak",
    ):
        assert hidden_text not in rendered
