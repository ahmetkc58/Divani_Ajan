from __future__ import annotations

import math
import re
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

from pypdf import PdfReader

from karayol_agent.documents.text_normalization import normalize_document_text
from karayol_agent.text_utils import normalize_whitespace


class ExtractionError(RuntimeError):
    pass


class DocumentExtractor:
    SUPPORTED_SUFFIXES = {".txt", ".md", ".pdf"}
    _SHORT_TEXT_LAYER_PATTERNS = (
        re.compile(r"^ek\s*[-:]?\s*\d+(?:\s*/\s*\d+)?$", re.IGNORECASE),
        re.compile(
            r"^imza\s*[:：]?\s+"
            r"[A-ZÇĞİÖŞÜ][A-Za-zÇĞİÖŞÜçğıöşü]{1,24}"
            r"(?:\s+[A-ZÇĞİÖŞÜ][A-Za-zÇĞİÖŞÜçğıöşü]{1,24}){1,3}$",
            re.IGNORECASE,
        ),
    )
    _SHORT_OCR_SIGNATURE_PATTERNS = (
        re.compile(
            r"^imza\s*[:：]?\s+"
            r"[A-ZÇĞİÖŞÜ][A-Za-zÇĞİÖŞÜçğıöşü]{1,24}"
            r"(?:\s+[A-ZÇĞİÖŞÜ][A-Za-zÇĞİÖŞÜçğıöşü]{1,24}){1,3}$",
            re.IGNORECASE,
        ),
        re.compile(
            r"^[A-ZÇĞİÖŞÜ][a-zçğıöşü]{1,24}"
            r"(?:\s+[A-ZÇĞİÖŞÜ][a-zçğıöşü]{1,24}){0,2}"
            r"\s+[A-ZÇĞİÖŞÜ]{2,25}$"
        ),
    )
    _OCR_WATERMARK_TOKENS = {
        "adobe",
        "camscanner",
        "lens",
        "office",
        "scan",
        "scanned",
        "scanner",
    }

    def __init__(
        self,
        *,
        max_chars: int = 200_000,
        max_pdf_pages: int = 50,
        max_ocr_pixels_per_page: int = 20_000_000,
        max_ocr_total_pixels: int = 100_000_000,
        ocr_document_timeout_seconds: float = 120,
        ocr_page_timeout_seconds: float = 60,
    ) -> None:
        self.max_chars = max_chars
        self.max_pdf_pages = max_pdf_pages
        self.max_ocr_pixels_per_page = max_ocr_pixels_per_page
        self.max_ocr_total_pixels = max_ocr_total_pixels
        self.ocr_document_timeout_seconds = ocr_document_timeout_seconds
        self.ocr_page_timeout_seconds = ocr_page_timeout_seconds
        if min(
            max_chars,
            max_pdf_pages,
            max_ocr_pixels_per_page,
            max_ocr_total_pixels,
            ocr_document_timeout_seconds,
            ocr_page_timeout_seconds,
        ) <= 0:
            raise ValueError("Belge/OCR kaynak sınırları pozitif olmalıdır.")

    def extract(self, path: Path) -> str:
        suffix = path.suffix.lower()
        if suffix not in self.SUPPORTED_SUFFIXES:
            raise ExtractionError(
                f"Desteklenmeyen dosya türü: {suffix}. Desteklenenler: "
                f"{', '.join(sorted(self.SUPPORTED_SUFFIXES))}"
            )
        if suffix in {".txt", ".md"}:
            try:
                text = path.read_text(encoding="utf-8-sig")
            except UnicodeDecodeError as exc:
                raise ExtractionError(
                    "Metin dosyası UTF-8 biçiminde değil veya geçersiz karakter içeriyor."
                ) from exc
            except OSError as exc:
                raise ExtractionError("Metin dosyası okunamadı.") from exc
        else:
            text = self._extract_pdf(path)
        text = self._clean_document_text(text)
        if not normalize_whitespace(text):
            raise ExtractionError("Belgeden okunabilir metin çıkarılamadı.")
        if len(text) > self.max_chars:
            raise ExtractionError(
                f"Belge metni en fazla {self.max_chars} karakter olabilir; "
                "sessiz kesme yapılmadı."
            )
        return text

    @staticmethod
    def _clean_document_text(text: str) -> str:
        """Alan etiketleri için satır sınırlarını koruyarak metni temizler."""
        return normalize_document_text(text)

    def _extract_pdf(self, path: Path) -> str:
        try:
            import pymupdf

            try:
                document = pymupdf.open(stream=path.read_bytes(), filetype="pdf")
            except Exception as exc:
                raise ExtractionError(
                    "PDF dosyası açılamadı; dosya bozuk veya geçerli bir PDF değil."
                ) from exc
            try:
                self._validate_pdf_page_count(len(document))
                page_texts: list[str] = []
                page_has_raster_images: list[bool] = []
                for page in document:
                    page_texts.append(page.get_text("text").strip())
                    try:
                        page_has_raster_images.append(bool(page.get_images(full=True)))
                    except Exception:
                        page_has_raster_images.append(True)
            except ExtractionError:
                raise
            except Exception as exc:
                raise ExtractionError("PDF sayfalarındaki metin okunamadı.") from exc
            finally:
                document.close()
        except ImportError:
            try:
                reader = PdfReader(str(path))
                self._validate_pdf_page_count(len(reader.pages))
                page_texts = [
                    (page.extract_text() or "").strip() for page in reader.pages
                ]
                page_has_raster_images = [
                    self._pypdf_page_has_raster_image(page)
                    for page in reader.pages
                ]
            except ExtractionError:
                raise
            except Exception as exc:
                raise ExtractionError(
                    "PDF dosyası açılamadı; dosya bozuk veya geçerli bir PDF değil."
                ) from exc
        return self._merge_pdf_page_texts(
            path,
            page_texts,
            page_has_raster_images=page_has_raster_images,
        )

    def _merge_pdf_page_texts(
        self,
        path: Path,
        page_texts: list[str],
        *,
        page_has_raster_images: list[bool] | None = None,
    ) -> str:
        """OCR only weak pages and preserve the original PDF page order."""
        raster_flags = page_has_raster_images or [False] * len(page_texts)
        if len(raster_flags) != len(page_texts):
            raise ExtractionError("PDF sayfa kalite metadata'sı tutarsız.")
        weak_page_numbers = {
            page_number
            for page_number, (text, has_raster_image) in enumerate(
                zip(page_texts, raster_flags, strict=True), start=1
            )
            if not self._has_usable_page_text(
                text, has_raster_image=has_raster_image
            )
        }
        if not weak_page_numbers:
            return "\n\n".join(page_texts)

        ocr_pages = self._ocr_pdf_pages(path, page_numbers=weak_page_numbers)
        for page_number in sorted(weak_page_numbers):
            if not self._has_usable_ocr_text(ocr_pages.get(page_number, "")):
                raise ExtractionError(
                    f"OCR sayfa {page_number} için okunabilir metin üretemedi; "
                    "eksik sayfayla işleme devam edilmedi."
                )
        merged: list[str] = []
        for page_number, text in enumerate(page_texts, start=1):
            if page_number not in weak_page_numbers:
                merged.append(text)
                continue
            merged.append(ocr_pages[page_number].strip())
        return "\n\n".join(merged)

    def _validate_pdf_page_count(self, page_count: int) -> None:
        if page_count < 1:
            raise ExtractionError("PDF dosyası sayfa içermiyor.")
        if page_count > self.max_pdf_pages:
            raise ExtractionError(
                f"PDF en fazla {self.max_pdf_pages} sayfa olabilir."
            )

    @staticmethod
    def _pypdf_page_has_raster_image(page: object) -> bool:
        try:
            resources = page.get("/Resources")  # type: ignore[attr-defined]
            if resources is None:
                return False
            resources = resources.get_object()
            xobjects = resources.get("/XObject")
            if xobjects is None:
                return False
            for candidate in xobjects.get_object().values():
                if candidate.get_object().get("/Subtype") == "/Image":
                    return True
            return False
        except Exception:
            return True

    @staticmethod
    def _has_usable_text_layer(page_texts: list[str]) -> bool:
        """Return true only when every PDF page has a usable text layer."""
        return bool(page_texts) and all(
            DocumentExtractor._has_usable_page_text(text) for text in page_texts
        )

    @staticmethod
    def _has_usable_page_text(
        text: str,
        *,
        has_raster_image: bool = False,
    ) -> bool:
        """Accept robust text layers plus a narrow set of short legal markers."""
        normalized = normalize_whitespace(text)
        if not has_raster_image and any(
            pattern.fullmatch(normalized)
            for pattern in DocumentExtractor._SHORT_TEXT_LAYER_PATTERNS
        ):
            return True
        if len(normalized) < 20:
            return False
        replacement_ratio = normalized.count("�") / max(len(normalized), 1)
        alpha_count = sum(character.isalpha() for character in normalized)
        alpha_ratio = alpha_count / max(len(normalized), 1)
        return alpha_count >= 8 and alpha_ratio >= 0.25 and replacement_ratio < 0.01

    @staticmethod
    def _has_usable_ocr_text(text: str) -> bool:
        """Reject blank, partial and watermark-only OCR output fail-closed."""
        normalized = normalize_whitespace(text)
        normalized_tokens = {
            token.casefold()
            for token in re.findall(r"[A-Za-zÇĞİÖŞÜçğıöşü]+", normalized)
        }
        if (
            not normalized_tokens & DocumentExtractor._OCR_WATERMARK_TOKENS
            and any(
                pattern.fullmatch(normalized)
                for pattern in DocumentExtractor._SHORT_OCR_SIGNATURE_PATTERNS
            )
        ):
            return True
        if len(normalized) < 20:
            return False
        replacement_ratio = normalized.count("�") / max(len(normalized), 1)
        alpha_count = sum(character.isalpha() for character in normalized)
        alpha_ratio = alpha_count / max(len(normalized), 1)
        return alpha_count >= 8 and alpha_ratio >= 0.25 and replacement_ratio < 0.01

    def _ocr_pdf(self, path: Path) -> str:
        pages = self._ocr_pdf_pages(path, page_numbers=None)
        return "\n\n".join(pages[page_number] for page_number in sorted(pages))

    def _ocr_pdf_pages(
        self,
        path: Path,
        *,
        page_numbers: set[int] | None,
    ) -> dict[int, str]:
        tesseract = shutil.which("tesseract")
        if not tesseract:
            raise ExtractionError(
                "PDF metin katmanı yetersiz ve Tesseract bulunamadı; OCR yapılamadı."
            )
        try:
            import pymupdf
        except ImportError as exc:
            raise ExtractionError(
                "PDF metin katmanı yetersiz ve PyMuPDF bulunamadı; OCR yapılamadı."
            ) from exc

        requested_pages = set(page_numbers) if page_numbers is not None else None
        extracted: dict[int, str] = {}
        deadline = time.monotonic() + self.ocr_document_timeout_seconds
        total_pixels = 0
        with tempfile.TemporaryDirectory(prefix="karayol-ocr-") as temp_dir:
            try:
                document = pymupdf.open(path)
            except Exception:
                raise ExtractionError("PDF OCR için açılamadı.") from None
            try:
                self._validate_pdf_page_count(len(document))
                for page_number, page in enumerate(document, start=1):
                    if requested_pages is not None and page_number not in requested_pages:
                        continue
                    pixel_width = math.ceil(abs(float(page.rect.width)) * 2)
                    pixel_height = math.ceil(abs(float(page.rect.height)) * 2)
                    page_pixels = pixel_width * pixel_height
                    if page_pixels <= 0 or page_pixels > self.max_ocr_pixels_per_page:
                        raise ExtractionError(
                            f"OCR sayfa {page_number} piksel sınırını aşıyor."
                        )
                    total_pixels += page_pixels
                    if total_pixels > self.max_ocr_total_pixels:
                        raise ExtractionError(
                            "PDF toplam OCR piksel sınırını aşıyor."
                        )
                    self._remaining_timeout(deadline, page_number)
                    image_path = Path(temp_dir) / f"page-{page_number}.png"
                    try:
                        pixmap = page.get_pixmap(
                            matrix=pymupdf.Matrix(2, 2), alpha=False
                        )
                        if pixmap.width * pixmap.height > self.max_ocr_pixels_per_page:
                            raise ExtractionError(
                                f"OCR sayfa {page_number} piksel sınırını aşıyor."
                            )
                        pixmap.save(image_path)
                    except ExtractionError:
                        raise
                    except Exception:
                        raise ExtractionError(
                            f"OCR sayfa {page_number} görüntüye dönüştürülemedi."
                        ) from None
                    command = [tesseract, str(image_path), "stdout", "-l", "tur+eng"]
                    result = self._run_tesseract(
                        command, deadline=deadline, page_number=page_number
                    )
                    if result.returncode != 0 and "tur" in (
                        result.stderr or ""
                    ).casefold():
                        command = [tesseract, str(image_path), "stdout", "-l", "eng"]
                        result = self._run_tesseract(
                            command,
                            deadline=deadline,
                            page_number=page_number,
                        )
                    if result.returncode != 0:
                        raise ExtractionError(
                            f"OCR sayfa {page_number} için başarısız oldu "
                            f"(çıkış kodu {result.returncode})."
                        )
                    extracted[page_number] = result.stdout
            finally:
                document.close()
        return extracted

    def _run_tesseract(
        self,
        command: list[str],
        *,
        deadline: float,
        page_number: int,
    ) -> subprocess.CompletedProcess[str]:
        timeout = min(
            self.ocr_page_timeout_seconds,
            self._remaining_timeout(deadline, page_number),
        )
        try:
            return subprocess.run(
                command,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
                check=False,
            )
        except subprocess.TimeoutExpired:
            raise ExtractionError(
                f"OCR sayfa {page_number} süre sınırını aştı."
            ) from None
        except OSError:
            raise ExtractionError(
                f"OCR motoru sayfa {page_number} için çalıştırılamadı."
            ) from None

    @staticmethod
    def _remaining_timeout(deadline: float, page_number: int) -> float:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise ExtractionError(
                f"PDF OCR toplam süre sınırını sayfa {page_number} öncesinde aştı."
            )
        return remaining
