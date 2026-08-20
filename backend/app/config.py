from functools import lru_cache
from pathlib import Path

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    project_root: Path = Field(
        default_factory=lambda: Path(__file__).resolve().parents[2],
        validation_alias=AliasChoices("APP_PROJECT_ROOT", "PROJECT_ROOT"),
    )
    ollama_base_url: str = Field(
        default="http://127.0.0.1:11434",
        validation_alias=AliasChoices("OLLAMA_BASE_URL", "APP_OLLAMA_BASE_URL"),
    )
    cors_origins: str = Field(
        default="http://localhost:5173,http://localhost:8080",
        validation_alias=AliasChoices("APP_CORS_ORIGINS", "CORS_ORIGINS"),
    )
    max_upload_mb: int = Field(default=10, validation_alias="APP_MAX_UPLOAD_MB")
    max_pdf_pages: int = Field(default=20, validation_alias="APP_MAX_PDF_PAGES")
    job_timeout_seconds: float = Field(default=180, validation_alias="APP_JOB_TIMEOUT_SECONDS")
    log_level: str = Field(default="INFO", validation_alias="APP_LOG_LEVEL")

    @property
    def runtime_dir(self) -> Path:
        return self.project_root / "runtime"

    @property
    def uploads_dir(self) -> Path:
        return self.runtime_dir / "uploads"

    @property
    def exports_dir(self) -> Path:
        return self.runtime_dir / "exports"

    @property
    def index_dir(self) -> Path:
        return self.runtime_dir / "index"

    @property
    def database_path(self) -> Path:
        return self.runtime_dir / "app.sqlite3"

    @property
    def data_dir(self) -> Path:
        return self.project_root / "data"

    @property
    def resources_dir(self) -> Path:
        return self.project_root / "resources"

    @property
    def allowed_origins(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    def ensure_directories(self) -> None:
        for directory in (self.runtime_dir, self.uploads_dir, self.exports_dir, self.index_dir):
            directory.mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.ensure_directories()
    return settings
