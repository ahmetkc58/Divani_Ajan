from __future__ import annotations

import math
import re
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

from pypdf import PdfReader

from karayol_agent.documents.text_normalization import normalize_document_text
from karayol_agent.text_utils import normalize_whitespace


class ExtractionError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class OcrWord:
    """One recognized word's text and page position, in PDF/pixel points."""

    text: str
    left: float
    top: float
    width: float
    height: float
    confidence: float | None
    page_number: int


@dataclass(frozen=True, slots=True)
class ExtractedDocument:
    """Extracted text plus a best-effort word/position layout overlay.

    ``words`` is empty whenever layout capture isn't applicable (plain text
    files) or fails for any reason — it is never required for ``text`` to be
    valid, and callers must treat it as optional enrichment.
    """

    text: str
    words: tuple[OcrWord, ...] = ()


# Two Tesseract line completions in the wild on this project's Windows
# checkouts: an ancient 32-bit 3.02 install (no TSV/hOCR support, frequently
# still first on PATH) and a modern 5.x install. ``shutil.which`` alone is
# not reliable here, so every caller resolves through ``_resolve_tesseract``
# instead of using ``shutil.which("tesseract")`` directly.
_MIN_TESSERACT_MAJOR_VERSION = 4
_KNOWN_TESSERACT_PATHS = (
    Path(r"C:\Program Files\Tesseract-OCR\tesseract.exe"),
    Path(r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe"),
)
_TESSERACT_VERSION_PATTERN = re.compile(r"tesseract\s+v?(\d+)\.(\d+)(?:\.(\d+))?", re.IGNORECASE)


def _tesseract_version(binary: str) -> tuple[int, ...] | None:
    try:
        result = subprocess.run(
            [binary, "--version"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    match = _TESSERACT_VERSION_PATTERN.search(f"{result.stdout}\n{result.stderr}")
    if not match:
        return None
    return tuple(int(part) for part in match.groups() if part is not None)


def _resolve_tesseract() -> str | None:
    """Return a usable (>=4.0) Tesseract binary path, preferring PATH order.

    Falls back to known Windows install locations when the first binary on
    PATH is too old to support TSV output (a real split-install seen on this
    project's Windows checkouts: an ancient 32-bit 3.02 build ahead of a
    modern 5.x build on PATH). Deliberately uncached: this runs once per
    document (not per page), and caching process-wide made the result
    order-dependent on whatever ``shutil.which``/env state an earlier caller
    (including other tests in the same process) last observed.
    """

    candidates: list[Path] = []
    which_result = shutil.which("tesseract")
    if which_result:
        candidates.append(Path(which_result))
    candidates.extend(path for path in _KNOWN_TESSERACT_PATHS if path.is_file())

    seen: set[str] = set()
    for candidate in candidates:
        resolved = str(candidate)
        if resolved in seen:
            continue
        seen.add(resolved)
        version = _tesseract_version(resolved)
        if version is not None and version[0] >= _MIN_TESSERACT_MAJOR_VERSION:
            return resolved
    return which_result


class DocumentExtractor:
    SUPPORTED_SUFFIXES = {".txt", ".md", ".pdf", ".png", ".jpg", ".jpeg", ".tif", ".tiff"}
    IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".tif", ".tiff"}
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
        self._validate_file_signature(path, suffix)
        if suffix in {".txt", ".md"}:
            try:
                text = path.read_text(encoding="utf-8-sig")
            except UnicodeDecodeError as exc:
                raise ExtractionError(
                    "Metin dosyası UTF-8 biçiminde değil veya geçersiz karakter içeriyor."
                ) from exc
            except OSError as exc:
                raise ExtractionError("Metin dosyası okunamadı.") from exc
        elif suffix == ".pdf":
            text = self._extract_pdf(path)
        else:
            text = self._extract_image(path)
        text = self._clean_document_text(text)
        if not normalize_whitespace(text):
            raise ExtractionError("Belgeden okunabilir metin çıkarılamadı.")
        if len(text) > self.max_chars:
            raise ExtractionError(
                f"Belge metni en fazla {self.max_chars} karakter olabilir; "
                "sessiz kesme yapılmadı."
            )
        return text

    def extract_with_layout(self, path: Path) -> ExtractedDocument:
        """Return ``extract(path)``'s text plus a best-effort word overlay.

        ``text`` is exactly what ``extract(path)`` would return — same
        validation, same errors. Word/position capture is a separate,
        independent pass that never turns an otherwise-successful extraction
        into a failure: any internal error there just yields ``words=()``.
        """

        text = self.extract(path)
        try:
            words = self._extract_words(path)
        except Exception:
            words = ()
        return ExtractedDocument(text=text, words=words)

    def _extract_words(self, path: Path) -> tuple[OcrWord, ...]:
        suffix = path.suffix.lower()
        if suffix in {".txt", ".md"}:
            return ()
        try:
            import pymupdf
        except ImportError:
            return ()

        resolved = _resolve_tesseract()
        words: list[OcrWord] = []
        with tempfile.TemporaryDirectory(prefix="karayol-layout-ocr-") as temp_dir:
            if suffix == ".pdf":
                document = pymupdf.open(stream=path.read_bytes(), filetype="pdf")
                try:
                    for page_number, page in enumerate(document, start=1):
                        native_words = page.get_text("words")
                        page_text = page.get_text("text").strip()
                        if native_words and self._has_usable_page_text(page_text):
                            words.extend(
                                OcrWord(
                                    text=str(word_text),
                                    left=float(x0),
                                    top=float(y0),
                                    width=float(x1) - float(x0),
                                    height=float(y1) - float(y0),
                                    confidence=None,
                                    page_number=page_number,
                                )
                                for x0, y0, x1, y1, word_text, *_ in native_words
                            )
                        elif resolved is not None:
                            words.extend(
                                self._ocr_words_for_page(
                                    page, page_number, temp_dir, resolved, scale=2.0
                                )
                            )
                finally:
                    document.close()
            elif resolved is not None:
                document = pymupdf.open(path)
                try:
                    for page_number, page in enumerate(document, start=1):
                        words.extend(
                            self._ocr_words_for_page(
                                page, page_number, temp_dir, resolved, scale=1.0
                            )
                        )
                finally:
                    document.close()
        return tuple(words)

    def _ocr_words_for_page(
        self,
        page: object,
        page_number: int,
        temp_dir: str,
        tesseract: str,
        *,
        scale: float,
    ) -> list[OcrWord]:
        import pymupdf

        pixmap = page.get_pixmap(  # type: ignore[attr-defined]
            matrix=pymupdf.Matrix(scale, scale), alpha=False
        )
        if pixmap.width * pixmap.height > self.max_ocr_pixels_per_page:
            return []
        image_path = Path(temp_dir) / f"layout-page-{page_number}.png"
        pixmap.save(image_path)
        command = self._tesseract_command(
            tesseract, image_path, "tur+eng", tsv=True
        )
        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=self.ocr_page_timeout_seconds,
                check=False,
            )
        except (subprocess.TimeoutExpired, OSError):
            return []
        if result.returncode != 0:
            return []
        # Normalize back to PDF-point space so native and OCR-derived words
        # share one coordinate system regardless of the render scale used.
        return [
            OcrWord(
                text=word.text,
                left=word.left / scale,
                top=word.top / scale,
                width=word.width / scale,
                height=word.height / scale,
                confidence=word.confidence,
                page_number=word.page_number,
            )
            for word in self._parse_tesseract_tsv(result.stdout, page_number)
        ]

    _TSV_WORD_LEVEL = "5"

    @classmethod
    def _parse_tesseract_tsv(cls, tsv_output: str, page_number: int) -> list[OcrWord]:
        lines = tsv_output.splitlines()
        if not lines:
            return []
        header = lines[0].split("\t")
        required = ("level", "left", "top", "width", "height", "conf", "text")
        try:
            indices = {name: header.index(name) for name in required}
        except ValueError:
            return []
        words: list[OcrWord] = []
        for line in lines[1:]:
            columns = line.split("\t")
            if len(columns) <= max(indices.values()):
                continue
            if columns[indices["level"]] != cls._TSV_WORD_LEVEL:
                continue
            text = columns[indices["text"]].strip()
            if not text:
                continue
            try:
                left = float(columns[indices["left"]])
                top = float(columns[indices["top"]])
                width = float(columns[indices["width"]])
                height = float(columns[indices["height"]])
                confidence = float(columns[indices["conf"]])
            except ValueError:
                continue
            words.append(
                OcrWord(
                    text=text,
                    left=left,
                    top=top,
                    width=width,
                    height=height,
                    confidence=confidence if confidence >= 0 else None,
                    page_number=page_number,
                )
            )
        return words

    @staticmethod
    def _validate_file_signature(path: Path, suffix: str) -> None:
        try:
            with path.open("rb") as source:
                header = source.read(16)
        except OSError as exc:
            raise ExtractionError("Dosya okunamadı.") from exc
        valid = True
        if suffix == ".pdf":
            valid = header.startswith(b"%PDF-")
        elif suffix == ".png":
            valid = header.startswith(b"\x89PNG\r\n\x1a\n")
        elif suffix in {".jpg", ".jpeg"}:
            valid = header.startswith(b"\xff\xd8\xff")
        elif suffix in {".tif", ".tiff"}:
            valid = header.startswith((b"II*\x00", b"MM\x00*"))
        elif suffix in {".txt", ".md"}:
            valid = b"\x00" not in header
        if not valid:
            raise ExtractionError(
                "Dosya içeriği uzantısıyla uyuşmuyor; magic-byte doğrulaması başarısız."
            )

    def _extract_image(self, path: Path) -> str:
        tesseract = _resolve_tesseract()
        if tesseract is None:
            raise ExtractionError("Görsel belge için Tesseract bulunamadı; OCR yapılamadı.")
        try:
            import pymupdf
        except ImportError as exc:
            raise ExtractionError("Görsel belge için PyMuPDF bulunamadı; OCR yapılamadı.") from exc

        try:
            document = pymupdf.open(path)
        except Exception as exc:
            raise ExtractionError("Görsel dosya açılamadı veya bozuk.") from exc
        deadline = time.monotonic() + self.ocr_document_timeout_seconds
        total_pixels = 0
        extracted: list[str] = []
        with tempfile.TemporaryDirectory(prefix="karayol-image-ocr-") as temp_dir:
            try:
                self._validate_pdf_page_count(len(document))
                for page_number, page in enumerate(document, start=1):
                    try:
                        pixmap = page.get_pixmap(alpha=False)
                    except Exception as exc:
                        raise ExtractionError(
                            f"Görsel sayfa {page_number} çözümlenemedi."
                        ) from exc
                    page_pixels = pixmap.width * pixmap.height
                    if page_pixels <= 0 or page_pixels > self.max_ocr_pixels_per_page:
                        raise ExtractionError(
                            f"OCR sayfa {page_number} piksel sınırını aşıyor."
                        )
                    total_pixels += page_pixels
                    if total_pixels > self.max_ocr_total_pixels:
                        raise ExtractionError("Görsel toplam OCR piksel sınırını aşıyor.")
                    image_path = Path(temp_dir) / f"page-{page_number}.png"
                    pixmap.save(image_path)
                    result = self._run_tesseract(
                        self._tesseract_command(tesseract, image_path, "tur+eng"),
                        deadline=deadline,
                        page_number=page_number,
                    )
                    if result.returncode != 0 and "tur" in (result.stderr or "").casefold():
                        result = self._run_tesseract(
                            self._tesseract_command(tesseract, image_path, "eng"),
                            deadline=deadline,
                            page_number=page_number,
                        )
                    if result.returncode != 0:
                        raise ExtractionError(
                            f"OCR sayfa {page_number} için başarısız oldu "
                            f"(çıkış kodu {result.returncode})."
                        )
                    if not self._has_usable_ocr_text(result.stdout):
                        raise ExtractionError(
                            f"OCR sayfa {page_number} için okunabilir metin üretemedi."
                        )
                    extracted.append(result.stdout)
            finally:
                document.close()
        return "\n\n".join(extracted)

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
        tesseract = _resolve_tesseract()
        if tesseract is None:
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
                    command = self._tesseract_command(
                        tesseract, image_path, "tur+eng"
                    )
                    result = self._run_tesseract(
                        command, deadline=deadline, page_number=page_number
                    )
                    if result.returncode != 0 and "tur" in (
                        result.stderr or ""
                    ).casefold():
                        command = self._tesseract_command(
                            tesseract, image_path, "eng"
                        )
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

    @staticmethod
    def _tesseract_command(
        tesseract: str,
        image_path: Path,
        lang: str,
        *,
        tsv: bool = False,
    ) -> list[str]:
        command = [tesseract, str(image_path), "stdout", "-l", lang]
        if tsv:
            # A direct config *variable* rather than the trailing ``tsv``
            # config *file* — the latter requires locating
            # ``<tessdata>/configs/tsv`` relative to whatever tessdata
            # directory Tesseract resolves (TESSDATA_PREFIX or its own
            # install folder), which is not reliable across split installs
            # where language data and config files live in different
            # places. This variable form only needs the language data.
            command += ["-c", "tessedit_create_tsv=1"]
        return command

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
