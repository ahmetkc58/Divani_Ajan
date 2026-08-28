from pathlib import Path
import tomllib


ROOT = Path(__file__).resolve().parents[1]


def test_unconditional_runtime_imports_are_core_dependencies() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))[
        "project"
    ]
    dependencies = {
        requirement.split("[", 1)[0].split(">", 1)[0].split("<", 1)[0]
        for requirement in project["dependencies"]
    }

    assert "httpx" in dependencies
    assert project["requires-python"] == ">=3.11,<3.13"


def test_uab_launcher_falls_back_when_external_credentials_are_missing() -> None:
    launcher = (ROOT / "scripts" / "start_local_uab.ps1").read_text(
        encoding="utf-8"
    )

    assert '[switch]$EnableExternalRetrieval' in launcher
    assert '[string]$EmbeddingDevice = "cpu"' in launcher
    assert '[string]$RetrievalMode = "bm25"' in launcher
    assert '$env:KARAYOL_RETRIEVAL_MODE = $RetrievalMode' in launcher
    assert '$missingExternalVariables.Count -eq 0' in launcher
    assert '$env:KARAYOL_EXTERNAL_RETRIEVAL_ENABLED = "true"' not in launcher
