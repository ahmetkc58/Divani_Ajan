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
    assert all("arz/rica" not in paragraph for paragraph in state.draft.paragraphs)

