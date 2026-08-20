import io
import math
from dataclasses import dataclass
from pathlib import Path

import pymupdf as fitz
import pytesseract
from PIL import Image, ImageOps

from app.config import Settings


class DocumentValidationError(ValueError):
    pass


@dataclass
class ExtractionResult:
    text: str
    page_count: int
    method: str
    quality: float


ALLOWED_SUFFIXES = {".pdf", ".png", ".jpg", ".jpeg", ".txt"}


def validate_upload(filename: str, content_type: str | None, content: bytes, settings: Settings) -> str:
    suffix = Path(filename).suffix.lower()
    if suffix not in ALLOWED_SUFFIXES:
        raise DocumentValidationError("Yalnızca PDF, PNG, JPEG ve TXT dosyaları kabul edilir.")
    if not content:
        raise DocumentValidationError("Boş dosya yüklenemez.")
    if len(content) > settings.max_upload_mb * 1024 * 1024:
        raise DocumentValidationError(f"Dosya boyutu {settings.max_upload_mb} MB sınırını aşıyor.")

    if suffix == ".pdf" and not content.startswith(b"%PDF-"):
        raise DocumentValidationError("Dosya geçerli bir PDF değil.")
    if suffix in {".png", ".jpg", ".jpeg"}:
        try:
            image = Image.open(io.BytesIO(content))
            image.verify()
        except Exception as exc:
            raise DocumentValidationError("Dosya geçerli bir görüntü değil.") from exc
    if suffix == ".txt":
        try:
            content.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise DocumentValidationError("TXT dosyası UTF-8 kodlamasında olmalıdır.") from exc
    return suffix


def text_quality(text: str) -> float:
    stripped = text.strip()
    if not stripped:
        return 0.0
    length_score = min(len(stripped) / 250, 1.0)
    printable = sum(char.isprintable() and char not in "\x0b\x0c" for char in stripped)
    printable_score = printable / max(len(stripped), 1)
    word_count = len(stripped.split())
    word_score = min(word_count / 35, 1.0)
    replacement_penalty = min(stripped.count("�") / max(len(stripped), 1) * 20, 0.5)
    return max(0.0, min(1.0, 0.45 * length_score + 0.35 * printable_score + 0.2 * word_score - replacement_penalty))


def ocr_image(image: Image.Image) -> str:
    normalized = ImageOps.exif_transpose(image).convert("RGB")
    return pytesseract.image_to_string(normalized, lang="tur+eng", config="--psm 6")


def ocr_pdf_page(page: fitz.Page, dpi: int = 180) -> str:
    """PDF sayfasını yerel Tesseract ile, ağ erişimi olmadan metne dönüştürür."""
    matrix = fitz.Matrix(dpi / 72, dpi / 72)
    pixmap = page.get_pixmap(matrix=matrix, alpha=False)
    with Image.open(io.BytesIO(pixmap.tobytes("png"))) as image:
        return ocr_image(image).strip()


def extract_document(path: Path, settings: Settings) -> ExtractionResult:
    suffix = path.suffix.lower()
    if suffix == ".txt":
        text = path.read_text(encoding="utf-8")
        return ExtractionResult(text=text, page_count=1, method="direct_text", quality=text_quality(text))

    if suffix in {".png", ".jpg", ".jpeg"}:
        with Image.open(path) as image:
            text = ocr_image(image)
        return ExtractionResult(text=text, page_count=1, method="tesseract", quality=text_quality(text))

    try:
        document = fitz.open(path)
    except Exception as exc:
        raise DocumentValidationError(f"PDF açılamadı: {exc}") from exc

    if document.needs_pass:
        document.close()
        raise DocumentValidationError("Şifreli PDF dosyaları desteklenmiyor.")
    if document.page_count > settings.max_pdf_pages:
        count = document.page_count
        document.close()
        raise DocumentValidationError(
            f"PDF {count} sayfa; en fazla {settings.max_pdf_pages} sayfa kabul edilir."
        )

    pages: list[str] = []
    methods: list[str] = []
    for page_number, page in enumerate(document, start=1):
        direct = page.get_text("text").strip()
        if text_quality(direct) >= 0.62:
            page_text = direct
            method = "direct_pdf_text"
        else:
            page_text = ocr_pdf_page(page, dpi=300)
            method = "tesseract"
        pages.append(f"--- SAYFA {page_number} ---\n{page_text}")
        methods.append(method)
    page_count = document.page_count
    document.close()

    combined = "\n\n".join(pages)
    unique_methods = sorted(set(methods))
    method = unique_methods[0] if len(unique_methods) == 1 else "mixed:" + "+".join(unique_methods)
    quality_values = [text_quality(page) for page in pages]
    quality = sum(quality_values) / max(len(quality_values), 1)
    if not math.isfinite(quality):
        quality = 0.0
    return ExtractionResult(text=combined, page_count=page_count, method=method, quality=quality)
