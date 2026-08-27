import json
import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_cli_missing_file_returns_clean_json_error() -> None:
    # Regression: ISSUE-008 - beklenen dosya hatası kullanıcıya traceback gösteriyordu.
    # Found by /qa on 2026-08-23
    # Report: .gstack/qa-reports/qa-report-localhost-2026-08-23.md
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(ROOT / "src")
    environment["PYTHONUTF8"] = "1"
    environment["PYTHONIOENCODING"] = "utf-8"

    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "karayol_agent.cli",
            "process",
            "--file",
            "examples/yok.txt",
        ],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )

    payload = json.loads(completed.stderr)
    assert completed.returncode == 2
    assert completed.stdout == ""
    assert payload["error_type"] == "ExtractionError"
    assert "okunamadı" in payload["error"]
    assert "Traceback" not in completed.stderr
