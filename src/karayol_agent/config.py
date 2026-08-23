from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


PACKAGE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = PACKAGE_DIR.parents[1]


@dataclass(frozen=True, slots=True)
class Settings:
    project_root: Path = PROJECT_ROOT
    data_dir: Path = PROJECT_ROOT / "data"
    templates_dir: Path = PROJECT_ROOT / "templates"
    output_dir: Path = PROJECT_ROOT / "output"
    runtime_dir: Path = PROJECT_ROOT / "runtime"
    max_upload_bytes: int = 20 * 1024 * 1024
    max_text_chars: int = 200_000
    retrieval_top_k: int = 5
    min_retrieval_score: float = 0.05
    low_confidence_threshold: float = 0.60
    latex_timeout_seconds: int = 30

    def ensure_runtime_dirs(self) -> None:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.runtime_dir.mkdir(parents=True, exist_ok=True)


settings = Settings()

