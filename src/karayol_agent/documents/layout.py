from __future__ import annotations

import csv
import io
import shutil
import subprocess
import tempfile
from collections import defaultdict
from pathlib import Path

from karayol_agent.schemas import BoundingBox, DocumentLayout, DocumentLine
from karayol_agent.text_utils import normalize_whitespace


def plain_text_layout(text: str) -> DocumentLayout:
    lines = [
        DocumentLine(
            line_id=f"page-1-line-{index}",
            page=1,
            text=cleaned,
            source="plain_text",
        )
        for index, raw in enumerate(text.splitlines(), start=1)
        if (cleaned := normalize_whitespace(raw))
    ]
    return DocumentLayout(lines=lines, page_count=1, coordinate_system="unavailable")


def file_layout(path: Path, fallback_text: str) -> DocumentLayout:
    suffix = path.suffix.casefold()
    if suffix == ".pdf":
        return _pdf_layout(path, fallback_text)
    if suffix in {".png", ".jpg", ".jpeg", ".tif", ".tiff"}:
        return _image_layout(path, fallback_text)
    return plain_text_layout(fallback_text)


def _pdf_layout(path: Path, fallback_text: str) -> DocumentLayout:
    try:
        import pymupdf
    except ImportError:
        return plain_text_layout(fallback_text)

    document = pymupdf.open(path)
    lines: list[DocumentLine] = []
    try:
        for page_index, page in enumerate(document, start=1):
            words = page.get_text("words", sort=True)
            page_text = normalize_whitespace(page.get_text("text"))
            if words and len(page_text) >= 20:
                lines.extend(_text_layer_lines(words, page_index, page.rect.width, page.rect.height))
                continue
            lines.extend(_ocr_page_lines(page, page_index, scale=2))
        if not lines:
            fallback = plain_text_layout(fallback_text)
            return fallback.model_copy(update={"page_count": max(1, len(document))})
        return DocumentLayout(
            lines=lines,
            page_count=max(1, len(document)),
            coordinate_system="normalized_page",
        )
    finally:
        document.close()


def _image_layout(path: Path, fallback_text: str) -> DocumentLayout:
    try:
        import pymupdf
    except ImportError:
        return plain_text_layout(fallback_text)
    document = pymupdf.open(path)
    lines: list[DocumentLine] = []
    try:
        for page_index, page in enumerate(document, start=1):
            lines.extend(_ocr_page_lines(page, page_index, scale=1))
        if not lines:
            return plain_text_layout(fallback_text)
        return DocumentLayout(
            lines=lines,
            page_count=max(1, len(document)),
            coordinate_system="normalized_page",
        )
    finally:
        document.close()


def _text_layer_lines(
    words: list[tuple], page_number: int, width: float, height: float
) -> list[DocumentLine]:
    grouped: dict[tuple[int, int], list[tuple]] = defaultdict(list)
    for word in words:
        grouped[(int(word[5]), int(word[6]))].append(word)
    result: list[DocumentLine] = []
    for line_number, key in enumerate(sorted(grouped), start=1):
        items = sorted(grouped[key], key=lambda item: int(item[7]))
        text = normalize_whitespace(" ".join(str(item[4]) for item in items))
        if not text:
            continue
        result.append(
            DocumentLine(
                line_id=f"page-{page_number}-line-{line_number}",
                page=page_number,
                text=text,
                bbox=_normalized_bbox(
                    min(float(item[0]) for item in items),
                    min(float(item[1]) for item in items),
                    max(float(item[2]) for item in items),
                    max(float(item[3]) for item in items),
                    width,
                    height,
                ),
                confidence=1.0,
                source="text_layer",
            )
        )
    return result


def _ocr_page_lines(
    page: object,
    page_number: int,
    *,
    scale: int,
) -> list[DocumentLine]:
    import pymupdf

    tesseract = shutil.which("tesseract")
    if not tesseract:
        return []
    pixmap = page.get_pixmap(matrix=pymupdf.Matrix(scale, scale), alpha=False)
    with tempfile.TemporaryDirectory(prefix="karayol-layout-") as temp_dir:
        image_path = Path(temp_dir) / "page.png"
        pixmap.save(image_path)
        command = [tesseract, str(image_path), "stdout", "-l", "tur+eng", "tsv"]
        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=60,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            return []
        if result.returncode != 0:
            command[5] = "eng"
            try:
                result = subprocess.run(
                    command,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=60,
                    check=False,
                )
            except (OSError, subprocess.TimeoutExpired):
                return []
        if result.returncode != 0:
            return []
    return _tsv_lines(result.stdout, page_number, pixmap.width, pixmap.height)


def _tsv_lines(tsv: str, page_number: int, width: int, height: int) -> list[DocumentLine]:
    grouped: dict[tuple[int, int, int], list[dict[str, str]]] = defaultdict(list)
    for row in csv.DictReader(io.StringIO(tsv), delimiter="\t"):
        text = normalize_whitespace(row.get("text", ""))
        if text:
            grouped[(int(row["block_num"]), int(row["par_num"]), int(row["line_num"]))].append(row)
    result: list[DocumentLine] = []
    for line_number, key in enumerate(sorted(grouped), start=1):
        rows = grouped[key]
        left = min(int(row["left"]) for row in rows)
        top = min(int(row["top"]) for row in rows)
        right = max(int(row["left"]) + int(row["width"]) for row in rows)
        bottom = max(int(row["top"]) + int(row["height"]) for row in rows)
        confidences = [max(0.0, float(row["conf"])) for row in rows]
        result.append(
            DocumentLine(
                line_id=f"page-{page_number}-line-{line_number}",
                page=page_number,
                text=normalize_whitespace(" ".join(row["text"] for row in rows)),
                bbox=_normalized_bbox(left, top, right, bottom, width, height),
                confidence=round(sum(confidences) / len(confidences) / 100, 4),
                source="ocr",
            )
        )
    return result


def _normalized_bbox(
    x0: float, y0: float, x1: float, y1: float, width: float, height: float
) -> BoundingBox:
    return BoundingBox(
        x0=max(0.0, min(1.0, x0 / width)),
        y0=max(0.0, min(1.0, y0 / height)),
        x1=max(0.0, min(1.0, x1 / width)),
        y1=max(0.0, min(1.0, y1 / height)),
    )


__all__ = ["file_layout", "plain_text_layout"]
