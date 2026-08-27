from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

from karayol_agent.revision_pins import (
    JINA_EMBEDDINGS_V3_CODE_REVISION,
    JINA_EMBEDDINGS_V3_REVISION,
    require_full_commit,
)

PACKAGE_DIR = Path(__file__).resolve().parent


def _default_project_root() -> Path:
    source_root = PACKAGE_DIR.parents[1]
    if (source_root / "data" / "synthetic_units.json").is_file() and (
        source_root / "templates"
    ).is_dir():
        return source_root
    installed_assets = Path(sys.prefix) / "share" / "karayol-agent"
    if (installed_assets / "data" / "synthetic_units.json").is_file():
        return installed_assets
    return source_root


_configured_project_root = os.getenv("KARAYOL_PROJECT_ROOT", "").strip()
PROJECT_ROOT = Path(_configured_project_root or _default_project_root()).resolve()

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


def _environment_csv(name: str, default: tuple[str, ...]) -> tuple[str, ...]:
    value = _environment(name)
    if value is None:
        return default
    return tuple(item.strip() for item in value.split(",") if item.strip())


@dataclass(frozen=True, slots=True)
class Settings:
    project_root: Path = PROJECT_ROOT
    data_dir: Path = PROJECT_ROOT / "data"
    organization_units_path: Path | None = None
    templates_dir: Path = PROJECT_ROOT / "templates"
    output_dir: Path = PROJECT_ROOT / "output"
    runtime_dir: Path = PROJECT_ROOT / "runtime"
    cors_allowed_origins: tuple[str, ...] = field(
        default_factory=lambda: _environment_csv(
            "KARAYOL_CORS_ALLOWED_ORIGINS",
            ("http://127.0.0.1:3000", "http://localhost:3000"),
        )
    )
    max_upload_bytes: int = 20 * 1024 * 1024
    max_text_chars: int = 200_000
    max_pdf_pages: int = field(
        default_factory=lambda: _environment_int("KARAYOL_MAX_PDF_PAGES", 50)
    )
    max_ocr_pixels_per_page: int = field(
        default_factory=lambda: _environment_int(
            "KARAYOL_MAX_OCR_PIXELS_PER_PAGE", 20_000_000
        )
    )
    max_ocr_total_pixels: int = field(
        default_factory=lambda: _environment_int(
            "KARAYOL_MAX_OCR_TOTAL_PIXELS", 100_000_000
        )
    )
    ocr_document_timeout_seconds: float = field(
        default_factory=lambda: _environment_float(
            "KARAYOL_OCR_DOCUMENT_TIMEOUT_SECONDS", 120
        )
    )
    ocr_page_timeout_seconds: float = field(
        default_factory=lambda: _environment_float(
            "KARAYOL_OCR_PAGE_TIMEOUT_SECONDS", 60
        )
    )
    retrieval_top_k: int = 5
    # Jina cosine için mutlak kanıt kabul eşiği. RRF skoru göreli sıralama
    # içindir ve tek başına hukuki kanıt doğrulaması yapamaz.
    min_retrieval_score: float = field(
        default_factory=lambda: _environment_float(
            "KARAYOL_MIN_RETRIEVAL_SCORE",
            0.20,
        )
    )
    min_relevance_score: float = field(
        default_factory=lambda: _environment_float(
            "KARAYOL_MIN_RELEVANCE_SCORE",
            0.75,
        )
    )
    relevance_candidate_top_k: int = field(
        default_factory=lambda: _environment_int(
            "KARAYOL_RELEVANCE_CANDIDATE_TOP_K",
            40,
        )
    )
    snapshot_relevance_policy: str = field(
        default_factory=lambda: (
            _environment("KARAYOL_SNAPSHOT_RELEVANCE_POLICY", "reviewed_only")
            or "reviewed_only"
        )
    )
    low_confidence_threshold: float = 0.60
    latex_timeout_seconds: int = 30
    evidence_graph_enabled: bool = field(
        default_factory=lambda: _environment_bool(
            "KARAYOL_EVIDENCE_GRAPH_ENABLED", True
        )
    )
    evidence_graph_path: Path = field(
        default_factory=lambda: Path(
            _environment(
                "KARAYOL_EVIDENCE_GRAPH_PATH",
                str(
                    PROJECT_ROOT
                    / "reports"
                    / "synthetic_evidence_graph_2026-08-24.json"
                ),
            )
            or PROJECT_ROOT / "reports" / "synthetic_evidence_graph_2026-08-24.json"
        )
    )
    retrieval_mode: str = field(
        default_factory=lambda: _environment("KARAYOL_RETRIEVAL_MODE", "bm25") or "bm25"
    )
    corpus_mode: str = field(
        default_factory=lambda: (
            _environment("KARAYOL_CORPUS_MODE", "verified_public") or "verified_public"
        )
    )
    embedding_model: str = "jinaai/jina-embeddings-v3"
    embedding_revision: str = field(
        default_factory=lambda: (
            _environment("KARAYOL_EMBEDDING_REVISION", JINA_EMBEDDINGS_V3_REVISION)
            or JINA_EMBEDDINGS_V3_REVISION
        )
    )
    embedding_code_revision: str = field(
        default_factory=lambda: (
            _environment(
                "KARAYOL_EMBEDDING_CODE_REVISION",
                JINA_EMBEDDINGS_V3_CODE_REVISION,
            )
            or JINA_EMBEDDINGS_V3_CODE_REVISION
        )
    )
    embedding_dimension: int = field(
        default_factory=lambda: _environment_int("KARAYOL_EMBEDDING_DIMENSION", 1024)
    )
    embedding_batch_size: int = field(
        default_factory=lambda: _environment_int("KARAYOL_EMBEDDING_BATCH_SIZE", 16)
    )
    embedding_backend: str = field(
        default_factory=lambda: (
            _environment("KARAYOL_EMBEDDING_BACKEND", "transformers") or "transformers"
        )
    )
    embedding_local_files_only: bool = field(
        default_factory=lambda: _environment_bool(
            "KARAYOL_EMBEDDING_LOCAL_FILES_ONLY", False
        )
    )
    embedding_device: str | None = field(
        default_factory=lambda: _environment("KARAYOL_EMBEDDING_DEVICE")
    )
    qdrant_url: str | None = field(default_factory=lambda: _environment("QDRANT_URL"))
    qdrant_path: Path | None = field(
        default_factory=lambda: (
            Path(value)
            if (value := _environment("KARAYOL_QDRANT_PATH")) is not None
            else None
        )
    )
    qdrant_api_key: str | None = field(
        default_factory=lambda: _environment("QDRANT_API_KEY"),
        repr=False,
    )
    qdrant_collection: str = field(
        default_factory=lambda: (
            _environment("KARAYOL_QDRANT_COLLECTION", "legal_chunks_v1")
            or "legal_chunks_v1"
        )
    )
    qdrant_vector_name: str | None = field(
        default_factory=lambda: _environment("KARAYOL_QDRANT_VECTOR_NAME")
    )
    qdrant_timeout_seconds: float = field(
        default_factory=lambda: _environment_float(
            "KARAYOL_QDRANT_TIMEOUT_SECONDS", 10.0
        )
    )
    external_retrieval_enabled: bool = field(
        default_factory=lambda: _environment_bool(
            "KARAYOL_EXTERNAL_RETRIEVAL_ENABLED", False
        )
    )
    external_qdrant_url: str = field(
        default_factory=lambda: _environment(
            "EVREN_QDRANT_URL", "https://evren-vektor.ssyz.org.tr"
        )
        or "https://evren-vektor.ssyz.org.tr"
    )
    external_qdrant_prefix: str | None = field(
        default_factory=lambda: _environment("EVREN_QDRANT_TEAM_PREFIX")
    )
    external_qdrant_api_key: str | None = field(
        default_factory=lambda: _environment("EVREN_QDRANT_API_KEY"), repr=False
    )
    external_qdrant_collection: str = field(
        default_factory=lambda: _environment(
            "KARAYOL_EXTERNAL_QDRANT_COLLECTION", "legal_chunks_direct"
        )
        or "legal_chunks_direct"
    )
    external_corpus_fingerprint: str | None = field(
        default_factory=lambda: _environment("KARAYOL_EXTERNAL_CORPUS_FINGERPRINT")
    )
    external_embedding_base_url: str | None = field(
        default_factory=lambda: _environment("EVREN_EMBEDDING_BASE_URL")
    )
    external_embedding_api_key: str | None = field(
        default_factory=lambda: _environment("EVREN_LLM_API_KEY"), repr=False
    )
    external_embedding_model: str = field(
        default_factory=lambda: _environment(
            "EVREN_EMBEDDING_MODEL", "bge-m3-embed"
        )
        or "bge-m3-embed"
    )
    hybrid_candidate_top_k: int = field(
        default_factory=lambda: _environment_int("KARAYOL_HYBRID_CANDIDATE_TOP_K", 20)
    )
    rrf_k: int = field(default_factory=lambda: _environment_int("KARAYOL_RRF_K", 60))
    reranker_model: str = "jinaai/jina-reranker-v2-base-multilingual"
    reranker_revision: str = field(
        default_factory=lambda: (
            _environment("KARAYOL_RERANKER_REVISION", JINA_RERANKER_V2_REVISION)
            or JINA_RERANKER_V2_REVISION
        )
    )
    reranker_code_revision: str = field(
        default_factory=lambda: (
            _environment("KARAYOL_RERANKER_CODE_REVISION", JINA_RERANKER_V2_REVISION)
            or JINA_RERANKER_V2_REVISION
        )
    )
    reranker_batch_size: int = field(
        default_factory=lambda: _environment_int("KARAYOL_RERANKER_BATCH_SIZE", 8)
    )
    reranker_candidate_top_k: int = field(
        default_factory=lambda: _environment_int("KARAYOL_RERANKER_CANDIDATE_TOP_K", 30)
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
    competition_snapshot_path: Path = field(
        default_factory=lambda: Path(
            _environment(
                "KARAYOL_COMPETITION_SNAPSHOT_PATH",
                str(PROJECT_ROOT / "data" / "processed" / "competition_snapshot.json"),
            )
            or PROJECT_ROOT / "data" / "processed" / "competition_snapshot.json"
        )
    )

    def __post_init__(self) -> None:
        normalized_origins: list[str] = []
        for origin in self.cors_allowed_origins:
            parsed = urlsplit(origin)
            if (
                origin == "*"
                or parsed.scheme not in {"http", "https"}
                or not parsed.netloc
                or parsed.path not in {"", "/"}
                or parsed.query
                or parsed.fragment
                or parsed.username
                or parsed.password
            ):
                raise ValueError(
                    "KARAYOL_CORS_ALLOWED_ORIGINS yalnız açık http(s) origin "
                    "adresleri içermelidir; joker, yol ve kimlik bilgisi kullanılamaz."
                )
            normalized_origins.append(f"{parsed.scheme}://{parsed.netloc}")
        if not normalized_origins:
            raise ValueError("En az bir frontend CORS origin adresi tanımlanmalıdır.")
        object.__setattr__(
            self, "cors_allowed_origins", tuple(dict.fromkeys(normalized_origins))
        )
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
            raise ValueError(
                "KARAYOL_RETRIEVAL_MODE yalnızca 'bm25' veya 'hybrid' olabilir."
            )
        object.__setattr__(self, "retrieval_mode", mode)
        corpus_mode = self.corpus_mode.casefold()
        if corpus_mode not in {"verified_public", "competition_snapshot"}:
            raise ValueError(
                "KARAYOL_CORPUS_MODE yalnız 'verified_public' veya "
                "'competition_snapshot' olabilir."
            )
        object.__setattr__(self, "corpus_mode", corpus_mode)
        relevance_policy = self.snapshot_relevance_policy.casefold()
        if relevance_policy not in {"reviewed_only", "lexical_overlap"}:
            raise ValueError(
                "KARAYOL_SNAPSHOT_RELEVANCE_POLICY yalnız 'reviewed_only' "
                "veya 'lexical_overlap' olabilir."
            )
        object.__setattr__(
            self,
            "snapshot_relevance_policy",
            relevance_policy,
        )
        if (
            corpus_mode == "competition_snapshot"
            and self.qdrant_collection == "legal_chunks_v1"
        ):
            object.__setattr__(
                self,
                "qdrant_collection",
                "competition_snapshot_chunks_v1",
            )
        if self.qdrant_url is not None and self.qdrant_path is not None:
            raise ValueError(
                "QDRANT_URL ve KARAYOL_QDRANT_PATH aynı anda kullanılamaz."
            )
        if self.external_retrieval_enabled:
            missing = [
                name
                for name, value in (
                    ("EVREN_QDRANT_TEAM_PREFIX", self.external_qdrant_prefix),
                    ("EVREN_QDRANT_API_KEY", self.external_qdrant_api_key),
                    (
                        "KARAYOL_EXTERNAL_CORPUS_FINGERPRINT",
                        self.external_corpus_fingerprint,
                    ),
                    ("EVREN_EMBEDDING_BASE_URL", self.external_embedding_base_url),
                    ("EVREN_LLM_API_KEY", self.external_embedding_api_key),
                )
                if not value
            ]
            if missing:
                raise ValueError(
                    "Dış korpus retrieval yapılandırması eksik: " + ", ".join(missing)
                )
        if self.qdrant_path is not None and not self.qdrant_path.is_absolute():
            object.__setattr__(
                self,
                "qdrant_path",
                (self.project_root / self.qdrant_path).resolve(),
            )
        if not self.active_legislation_path.is_absolute():
            object.__setattr__(
                self,
                "active_legislation_path",
                self.project_root / self.active_legislation_path,
            )
        if not self.competition_snapshot_path.is_absolute():
            object.__setattr__(
                self,
                "competition_snapshot_path",
                self.project_root / self.competition_snapshot_path,
            )
        if not self.evidence_graph_path.is_absolute():
            object.__setattr__(
                self,
                "evidence_graph_path",
                self.project_root / self.evidence_graph_path,
            )
        if self.embedding_dimension not in {32, 64, 128, 256, 512, 768, 1024}:
            raise ValueError(
                "Jina embedding boyutu desteklenen Matryoshka "
                "boyutlarından biri olmalı."
            )
        if (
            min(
                self.max_upload_bytes,
                self.max_text_chars,
                self.max_pdf_pages,
                self.max_ocr_pixels_per_page,
                self.max_ocr_total_pixels,
                self.ocr_document_timeout_seconds,
                self.ocr_page_timeout_seconds,
            )
            <= 0
        ):
            raise ValueError("Belge/OCR kaynak sınırları pozitif olmalıdır.")
        if self.embedding_batch_size < 1:
            raise ValueError("Embedding batch boyutu en az 1 olmalı.")
        if (
            isinstance(self.min_retrieval_score, bool)
            or not 0 <= self.min_retrieval_score <= 1
        ):
            raise ValueError("KARAYOL_MIN_RETRIEVAL_SCORE 0 ile 1 arasında olmalıdır.")
        if (
            isinstance(self.min_relevance_score, bool)
            or not 0 <= self.min_relevance_score <= 1
        ):
            raise ValueError("KARAYOL_MIN_RELEVANCE_SCORE 0 ile 1 arasında olmalıdır.")
        if self.relevance_candidate_top_k < self.retrieval_top_k:
            raise ValueError(
                "Relevance aday sayısı nihai retrieval top-k değerinden küçük olamaz."
            )
        if self.embedding_backend not in {
            "transformers",
            "sentence-transformers",
            "sentence_transformers",
        }:
            raise ValueError("Desteklenmeyen Jina embedding backend'i.")
        if self.embedding_device is not None:
            device = self.embedding_device.casefold()
            if (
                device != "cpu"
                and device != "cuda"
                and not (device.startswith("cuda:") and device[5:].isdigit())
            ):
                raise ValueError(
                    "KARAYOL_EMBEDDING_DEVICE 'cpu', 'cuda' veya 'cuda:N' olmalıdır."
                )
            object.__setattr__(self, "embedding_device", device)
        if self.hybrid_candidate_top_k < self.retrieval_top_k:
            raise ValueError(
                "Hibrit aday sayısı nihai retrieval top-k değerinden küçük olamaz."
            )
        if self.rrf_k < 1:
            raise ValueError("RRF k sabiti en az 1 olmalı.")
        if self.reranker_batch_size < 1:
            raise ValueError("Reranker batch boyutu en az 1 olmalı.")
        if self.reranker_candidate_top_k < self.retrieval_top_k:
            raise ValueError(
                "Reranker aday sayısı retrieval top-k değerinden küçük olamaz."
            )

    def ensure_runtime_dirs(self) -> None:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.runtime_dir.mkdir(parents=True, exist_ok=True)

    @property
    def retrieval_corpus_path(self) -> Path:
        if self.corpus_mode == "competition_snapshot":
            return self.competition_snapshot_path
        return self.active_legislation_path


settings = Settings()
