from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

from pypdf import PdfReader

from karayol_agent.text_utils import normalize_whitespace


class ExtractionError(RuntimeError):
    pass


class DocumentExtractor:
    SUPPORTED_SUFFIXES = {".txt", ".md", ".pdf"}

    def __init__(self, *, max_chars: int = 200_000) -> None:
        self.max_chars = max_chars

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
        return text[: self.max_chars]

    @staticmethod
    def _clean_document_text(text: str) -> str:
        """Alan etiketleri için satır sınırlarını koruyarak metni temizler."""
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        lines = [normalize_whitespace(line) for line in text.split("\n")]
        cleaned: list[str] = []
        previous_blank = False
        for line in lines:
            if not line:
                if not previous_blank:
                    cleaned.append("")
                previous_blank = True
            else:
                cleaned.append(line)
                previous_blank = False
        return "\n".join(cleaned).strip()

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
                page_texts = [page.get_text("text").strip() for page in document]
            except Exception as exc:
                raise ExtractionError("PDF sayfalarındaki metin okunamadı.") from exc
            finally:
                document.close()
        except ImportError:
            try:
                reader = PdfReader(str(path))
                page_texts = [
                    (page.extract_text() or "").strip() for page in reader.pages
                ]
            except Exception as exc:
                raise ExtractionError(
                    "PDF dosyası açılamadı; dosya bozuk veya geçerli bir PDF değil."
                ) from exc
        text = "\n\n".join(page_texts)
        if self._has_usable_text_layer(page_texts):
            return text
        return self._ocr_pdf(path)

    @staticmethod
    def _has_usable_text_layer(page_texts: list[str]) -> bool:
        """Kısa kullanıcı evraklarını mevzuat kalite eşiğine tabi tutmaz."""
        if not page_texts:
            return False
        normalized_pages = [normalize_whitespace(text) for text in page_texts]
        joined = " ".join(normalized_pages)
        if len(joined) < 40:
            return False
        readable_ratio = sum(len(text) >= 20 for text in normalized_pages) / len(
            normalized_pages
        )
        replacement_ratio = joined.count("�") / max(len(joined), 1)
        return readable_ratio >= 0.50 and replacement_ratio < 0.01

    def _ocr_pdf(self, path: Path) -> str:
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

        extracted: list[str] = []
        with tempfile.TemporaryDirectory(prefix="karayol-ocr-") as temp_dir:
            document = pymupdf.open(path)
            try:
                for page_number, page in enumerate(document, start=1):
                    image_path = Path(temp_dir) / f"page-{page_number}.png"
                    page.get_pixmap(matrix=pymupdf.Matrix(2, 2), alpha=False).save(image_path)
                    command = [tesseract, str(image_path), "stdout", "-l", "tur+eng"]
                    result = subprocess.run(
                        command,
                        capture_output=True,
                        text=True,
                        encoding="utf-8",
                        errors="replace",
                        timeout=60,
                        check=False,
                    )
                    if result.returncode != 0 and "tur" in result.stderr:
                        command = [tesseract, str(image_path), "stdout", "-l", "eng"]
                        result = subprocess.run(
                            command,
                            capture_output=True,
                            text=True,
                            encoding="utf-8",
                            errors="replace",
                            timeout=60,
                            check=False,
                        )
                    if result.returncode != 0:
                        raise ExtractionError(
                            f"OCR sayfa {page_number} için başarısız: {result.stderr.strip()}"
                        )
                    extracted.append(result.stdout)
            finally:
                document.close()
        return "\n\n".join(extracted)
