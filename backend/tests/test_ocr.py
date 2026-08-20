from pathlib import Path

import pytest

from app.config import Settings
from app.services.ocr import DocumentValidationError, text_quality, validate_upload


def settings(tmp_path: Path) -> Settings:
    return Settings(project_root=tmp_path, max_upload_mb=1, max_pdf_pages=2)


def test_text_quality_distinguishes_empty_and_readable_text() -> None:
    assert text_quality("") == 0
    readable = "Türkçe resmî yazışma metni " * 30
    assert text_quality(readable) > 0.8


def test_validate_utf8_text(tmp_path: Path) -> None:
    suffix = validate_upload("ornek.txt", "text/plain", "Türkçe evrak".encode(), settings(tmp_path))
    assert suffix == ".txt"


def test_rejects_unsupported_extension(tmp_path: Path) -> None:
    with pytest.raises(DocumentValidationError):
        validate_upload("ornek.exe", None, b"content", settings(tmp_path))


def test_rejects_fake_pdf(tmp_path: Path) -> None:
    with pytest.raises(DocumentValidationError):
        validate_upload("ornek.pdf", "application/pdf", b"not a pdf", settings(tmp_path))
