from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from karayol_agent.revision_pins import (
    JINA_EMBEDDINGS_V3_CODE_REVISION,
    JINA_EMBEDDINGS_V3_REVISION,
    require_full_commit,
)


PACKAGE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = PACKAGE_DIR.parents[1]

JINA_RERANKER_V2_REVISION = "9cfeff2df7d40d1b78e75e5e9cebec92a99813c9"


def _environment(name: str, default: str | None = None) -> str | None:
    value = os.getenv(name)
    if value is None:
        return default
    stripped = value.strip()
    return stripped or default


def _environment_int(name: str, default: int) -> int:
    value = _environment(name)
    return int(value) if value is not None else default


def _environment_float(name: str, default: float) -> float:
    value = _environment(name)
    return float(value) if value is not None else default


def _environment_bool(name: str, default: bool) -> bool:
    value = _environment(name)
    if value is None:
        return default
    normalized = value.casefold()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{name} bir boolean değer olmalıdır.")


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
    # Jina cosine için mutlak kanıt kabul eşiği. RRF skoru göreli sıralama
    # içindir ve tek başına hukuki kanıt doğrulaması yapamaz.
    min_retrieval_score: float = field(
        default_factory=lambda: _environment_float(
            "KARAYOL_MIN_RETRIEVAL_SCORE",
            0.20,
        )
    )
    low_confidence_threshold: float = 0.60
    latex_timeout_seconds: int = 30
    llm_backend: str = field(
        default_factory=lambda: _environment("KARAYOL_LLM_BACKEND", "none") or "none"
    )
    ollama_url: str = field(
        default_factory=lambda: _environment(
            "KARAYOL_OLLAMA_URL", "http://localhost:11434"
        ) or "http://localhost:11434"
    )
    ollama_model: str = field(
        default_factory=lambda: _environment("KARAYOL_OLLAMA_MODEL", "llama3.2:3b")
        or "llama3.2:3b"
    )
    ollama_timeout_seconds: float = field(
        default_factory=lambda: _environment_float("KARAYOL_OLLAMA_TIMEOUT_SECONDS", 60.0)
    )
    retrieval_mode: str = field(
        default_factory=lambda: _environment("KARAYOL_RETRIEVAL_MODE", "bm25") or "bm25"
    )
    embedding_model: str = "jinaai/jina-embeddings-v3"
    embedding_revision: str = field(
        default_factory=lambda: _environment(
            "KARAYOL_EMBEDDING_REVISION", JINA_EMBEDDINGS_V3_REVISION
        )
        or JINA_EMBEDDINGS_V3_REVISION
    )
    embedding_code_revision: str = field(
        default_factory=lambda: _environment(
            "KARAYOL_EMBEDDING_CODE_REVISION",
            JINA_EMBEDDINGS_V3_CODE_REVISION,
        )
        or JINA_EMBEDDINGS_V3_CODE_REVISION
    )
    embedding_dimension: int = field(
        default_factory=lambda: _environment_int("KARAYOL_EMBEDDING_DIMENSION", 1024)
    )
    embedding_batch_size: int = field(
        default_factory=lambda: _environment_int("KARAYOL_EMBEDDING_BATCH_SIZE", 16)
    )
    embedding_backend: str = field(
        default_factory=lambda: _environment(
            "KARAYOL_EMBEDDING_BACKEND", "transformers"
        )
        or "transformers"
    )
    embedding_local_files_only: bool = field(
        default_factory=lambda: _environment_bool(
            "KARAYOL_EMBEDDING_LOCAL_FILES_ONLY", False
        )
    )
    qdrant_url: str | None = field(
        default_factory=lambda: _environment("QDRANT_URL")
    )
    qdrant_api_key: str | None = field(
        default_factory=lambda: _environment("QDRANT_API_KEY"),
        repr=False,
    )
    qdrant_collection: str = field(
        default_factory=lambda: _environment(
            "KARAYOL_QDRANT_COLLECTION", "legal_chunks_v1"
        )
        or "legal_chunks_v1"
    )
    qdrant_timeout_seconds: float = field(
        default_factory=lambda: _environment_float("KARAYOL_QDRANT_TIMEOUT_SECONDS", 10.0)
    )
    hybrid_candidate_top_k: int = field(
        default_factory=lambda: _environment_int("KARAYOL_HYBRID_CANDIDATE_TOP_K", 20)
    )
    rrf_k: int = field(
        default_factory=lambda: _environment_int("KARAYOL_RRF_K", 60)
    )
    reranker_model: str = "jinaai/jina-reranker-v2-base-multilingual"
    reranker_revision: str = field(
        default_factory=lambda: _environment(
            "KARAYOL_RERANKER_REVISION", JINA_RERANKER_V2_REVISION
        )
        or JINA_RERANKER_V2_REVISION
    )
    reranker_code_revision: str = field(
        default_factory=lambda: _environment(
            "KARAYOL_RERANKER_CODE_REVISION", JINA_RERANKER_V2_REVISION
        )
        or JINA_RERANKER_V2_REVISION
    )
    reranker_batch_size: int = field(
        default_factory=lambda: _environment_int("KARAYOL_RERANKER_BATCH_SIZE", 8)
    )
    reranker_candidate_top_k: int = field(
        default_factory=lambda: _environment_int(
            "KARAYOL_RERANKER_CANDIDATE_TOP_K", 30
        )
    )
    index_version: str = field(
        default_factory=lambda: _environment("KARAYOL_INDEX_VERSION", "1.0") or "1.0"
    )
    active_legislation_path: Path = field(
        default_factory=lambda: Path(
            _environment(
                "KARAYOL_ACTIVE_LEGISLATION_PATH",
                str(PROJECT_ROOT / "data" / "processed" / "active_legislation.json"),
            )
            or PROJECT_ROOT / "data" / "processed" / "active_legislation.json"
        )
    )

    def __post_init__(self) -> None:
        for attribute, environment_name in (
            ("embedding_revision", "KARAYOL_EMBEDDING_REVISION"),
            ("embedding_code_revision", "KARAYOL_EMBEDDING_CODE_REVISION"),
            ("reranker_revision", "KARAYOL_RERANKER_REVISION"),
            ("reranker_code_revision", "KARAYOL_RERANKER_CODE_REVISION"),
        ):
            object.__setattr__(
                self,
                attribute,
                require_full_commit(
                    getattr(self, attribute),
                    field_name=environment_name,
                ),
            )
        mode = self.retrieval_mode.casefold()
        if mode not in {"bm25", "hybrid"}:
            raise ValueError("KARAYOL_RETRIEVAL_MODE yalnızca 'bm25' veya 'hybrid' olabilir.")
        object.__setattr__(self, "retrieval_mode", mode)
        llm_backend = self.llm_backend.casefold()
        if llm_backend not in {"none", "ollama"}:
            raise ValueError("KARAYOL_LLM_BACKEND yalnızca 'none' veya 'ollama' olabilir.")
        object.__setattr__(self, "llm_backend", llm_backend)
        if self.ollama_timeout_seconds <= 0:
            raise ValueError("KARAYOL_OLLAMA_TIMEOUT_SECONDS sıfırdan büyük olmalı.")
        if not self.active_legislation_path.is_absolute():
            object.__setattr__(
                self,
                "active_legislation_path",
                self.project_root / self.active_legislation_path,
            )
        if self.embedding_dimension not in {32, 64, 128, 256, 512, 768, 1024}:
            raise ValueError(
                "Jina embedding boyutu desteklenen Matryoshka "
                "boyutlarından biri olmalı."
            )
        if self.embedding_batch_size < 1:
            raise ValueError("Embedding batch boyutu en az 1 olmalı.")
        if (
            isinstance(self.min_retrieval_score, bool)
            or not 0 <= self.min_retrieval_score <= 1
        ):
            raise ValueError(
                "KARAYOL_MIN_RETRIEVAL_SCORE 0 ile 1 arasında olmalıdır."
            )
        if self.embedding_backend not in {
            "transformers",
            "sentence-transformers",
            "sentence_transformers",
        }:
            raise ValueError("Desteklenmeyen Jina embedding backend'i.")
        if self.hybrid_candidate_top_k < self.retrieval_top_k:
            raise ValueError("Hibrit aday sayısı nihai retrieval top-k değerinden küçük olamaz.")
        if self.rrf_k < 1:
            raise ValueError("RRF k sabiti en az 1 olmalı.")
        if self.reranker_batch_size < 1:
            raise ValueError("Reranker batch boyutu en az 1 olmalı.")
        if self.reranker_candidate_top_k < self.retrieval_top_k:
            raise ValueError("Reranker aday sayısı retrieval top-k değerinden küçük olamaz.")

    def ensure_runtime_dirs(self) -> None:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.runtime_dir.mkdir(parents=True, exist_ok=True)


settings = Settings()
