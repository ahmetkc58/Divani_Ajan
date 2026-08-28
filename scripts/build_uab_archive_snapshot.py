"""Build an explicitly unverified snapshot from every PDF in the UAB manifest.

This command does not grant legal/currentness approval.  It preserves source
hashes and page numbers, applies OCR only to pages without usable native text,
and writes a corpus accepted by the existing competition-snapshot safety mode.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import tempfile
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path

from karayol_agent.retrieval.contracts import (
    COMPETITION_SNAPSHOT_DATASET_NAME,
    COMPETITION_SNAPSHOT_NOTICE,
    COMPETITION_SNAPSHOT_STATUS,
    CorpusMode,
)
from karayol_agent.retrieval.repository import LegislationRepository
from karayol_agent.schemas import LegislationChunk
from karayol_agent.text_utils import normalize_whitespace


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = ROOT / "data" / "manifests" / "uab_legislation_manifest.json"
DEFAULT_OUTPUT = ROOT / "data" / "processed" / "uab_ministry_archive_snapshot.json"
DEFAULT_OCR_DIR = ROOT / "data" / "processed" / "uab_archive_ocr"
ARTICLE_PATTERN = re.compile(r"(?i)\b((?:(?:GEÇİCİ|EK)\s+)?MADDE\s+\d+[A-ZÇĞİÖŞÜ]?)")


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("Değer pozitif bir tam sayı olmalıdır.")
    return parsed


def _portable(path: Path) -> str:
    return path.resolve().relative_to(ROOT).as_posix()


def _decode_output(value: bytes) -> str:
    for encoding in ("utf-8", "cp1254", "cp1252"):
        try:
            return value.decode(encoding)
        except UnicodeDecodeError:
            continue
    return value.decode("utf-8", errors="replace")


def _ocr_page(page: object, *, dpi: int, timeout: int) -> str:
    pixmap = page.get_pixmap(dpi=dpi, alpha=False)
    with tempfile.TemporaryDirectory(prefix="uab-ocr-") as temp_dir:
        image_path = Path(temp_dir) / "page.png"
        output_base = Path(temp_dir) / "page-ocr"
        pixmap.save(image_path)
        result = subprocess.run(
            ["tesseract", str(image_path), str(output_base), "-l", "eng"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
            check=False,
        )
        output_path = output_base.with_suffix(".txt")
        if result.returncode == 0 and output_path.is_file():
            text = normalize_whitespace(_decode_output(output_path.read_bytes()))
            if len(text) >= 20:
                return text
    return ""


def _split_text(text: str, max_chars: int) -> list[str]:
    normalized = text.replace("\r\n", "\n").replace("\r", "\n").strip()
    if not normalized:
        return []
    blocks = [normalize_whitespace(item) for item in re.split(r"\n\s*\n", normalized)]
    blocks = [item for item in blocks if item]
    chunks: list[str] = []
    current = ""
    for block in blocks:
        pieces = [block[index : index + max_chars] for index in range(0, len(block), max_chars)]
        for piece in pieces:
            candidate = f"{current}\n\n{piece}".strip() if current else piece
            if len(candidate) <= max_chars:
                current = candidate
            else:
                chunks.append(current)
                current = piece
    if current:
        chunks.append(current)
    return chunks


def _page_chunks(
    *,
    text: str,
    page_number: int,
    max_chars: int,
    document_id: str,
    title: str,
    source_path: str,
    source_url: str | None,
    source_sha256: str,
    document_type: str,
    domain: str,
    subdomain: str,
    ocr_status: str,
    metadata_fallback: bool,
) -> list[dict[str, object]]:
    parts = _split_text(text, max_chars)
    if not parts:
        parts = [
            f"{title}. Belge türü: {document_type}. Alan: {domain}. "
            f"Alt alan: {subdomain}. Sayfa {page_number} için okunabilir metin "
            "çıkarılamadı; kaynak PDF insan incelemesi gerektirir."
        ]
        metadata_fallback = True
    result: list[dict[str, object]] = []
    for index, part in enumerate(parts, start=1):
        article_match = ARTICLE_PATTERN.search(part)
        digest = sha256(part.encode("utf-8")).hexdigest()[:12]
        chunk = LegislationChunk(
            chunk_id=f"{document_id}-p{page_number:04d}-c{index:03d}-{digest}",
            document_id=document_id,
            title=title,
            section=f"Sayfa {page_number}",
            article=article_match.group(1) if article_match else None,
            text=part,
            source=source_path,
            source_sha256=source_sha256,
            source_kind=CorpusMode.COMPETITION_SNAPSHOT.value,
            page=page_number,
            page_end=page_number,
            source_url=source_url,
            document_type=document_type,
            domain=domain,
            subdomain=subdomain,
            validity_status="needs_verification",
            approved_for_active_rag=False,
            ocr_status=ocr_status,
            context_text=(
                f"Belge: {title}\nTür: {document_type}\nAlan: {domain}\n"
                f"Alt alan: {subdomain}\nSayfa: {page_number}"
            ),
            status=COMPETITION_SNAPSHOT_STATUS,
            tags=[
                domain,
                subdomain,
                document_type,
                f"sayfa {page_number}",
                *( ["metadata_only_unreadable_page"] if metadata_fallback else [] ),
            ],
        )
        result.append(chunk.model_dump(mode="json"))
    return result


def build(args: argparse.Namespace) -> dict[str, object]:
    import pymupdf

    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    records = list(manifest["data"])
    if args.limit is not None:
        records = records[: args.limit]
    documents: list[dict[str, object]] = []
    chunks: list[dict[str, object]] = []
    ocr_document_count = 0
    ocr_page_count = 0
    metadata_fallback_page_count = 0
    args.ocr_dir.mkdir(parents=True, exist_ok=True)

    for position, record in enumerate(records, start=1):
        if len(record.get("local_pdfs") or []) != 1:
            raise ValueError(f"Kayıt {record.get('legislation_id')}: tekil PDF yolu yok.")
        source_file = (ROOT / record["local_pdfs"][0]).resolve()
        source_path = _portable(source_file)
        source_hash = sha256(source_file.read_bytes()).hexdigest()
        document_id = f"uab-{record['legislation_id']}"
        title = str(record.get("title") or source_file.stem).strip()
        document_type = str(record.get("document_type") or "unknown")
        domain = str(record.get("domain") or "unknown")
        subdomain = str(record.get("subdomain") or "unknown")
        source_url = record.get("source_url")
        page_texts: list[str] = []
        page_was_ocr: list[bool] = []

        pdf = pymupdf.open(source_file)
        try:
            for page in pdf:
                native = page.get_text("text").strip()
                usable = len(normalize_whitespace(native)) >= args.native_char_threshold
                ocr_text = ""
                if not usable and record.get("ocr_required") and not args.skip_ocr:
                    ocr_text = _ocr_page(page, dpi=args.ocr_dpi, timeout=args.ocr_timeout)
                selected = ocr_text or native
                page_texts.append(selected)
                page_was_ocr.append(bool(ocr_text))
        finally:
            pdf.close()

        document_uses_ocr = any(page_was_ocr)
        if document_uses_ocr:
            ocr_document_count += 1
            ocr_page_count += sum(page_was_ocr)
            ocr_status = "ocr_candidate_unverified"
            text_origin = "machine_ocr_candidate"
            derived_path = args.ocr_dir / f"{document_id}.txt"
            derived_text = "\n\n".join(
                f"--- SAYFA {index} ---\n{text}"
                for index, text in enumerate(page_texts, start=1)
            )
            derived_path.write_text(derived_text, encoding="utf-8")
            derived_hash: str | None = sha256(derived_path.read_bytes()).hexdigest()
            derived_file: str | None = _portable(derived_path)
        else:
            ocr_status = "text_layer_available"
            text_origin = "pdf_text_layer"
            derived_hash = None
            derived_file = None

        document_chunks: list[dict[str, object]] = []
        for page_number, page_text in enumerate(page_texts, start=1):
            fallback = not bool(normalize_whitespace(page_text))
            metadata_fallback_page_count += int(fallback)
            document_chunks.extend(
                _page_chunks(
                    text=page_text,
                    page_number=page_number,
                    max_chars=args.max_chars,
                    document_id=document_id,
                    title=title,
                    source_path=source_path,
                    source_url=source_url,
                    source_sha256=source_hash,
                    document_type=document_type,
                    domain=domain,
                    subdomain=subdomain,
                    ocr_status=ocr_status,
                    metadata_fallback=fallback,
                )
            )
        if not document_chunks:
            raise ValueError(f"{document_id}: hiçbir chunk üretilemedi.")
        chunks.extend(document_chunks)
        documents.append(
            {
                "document_id": document_id,
                "title": title,
                "source_path": source_path,
                "source_url": source_url,
                "source_sha256": source_hash,
                "source_chunk_count": len(document_chunks),
                "chunk_count": len(document_chunks),
                "exact_duplicate_rows_consolidated": 0,
                "text_origin": text_origin,
                "derived_text_sha256": derived_hash,
                **({"derived_text_file": derived_file} if derived_file else {}),
            }
        )
        if position % 25 == 0 or position == len(records):
            print(f"Hazırlanan PDF: {position}/{len(records)}; chunk: {len(chunks)}", flush=True)

    corpus = {
        "schema_version": "2.0",
        "dataset_name": COMPETITION_SNAPSHOT_DATASET_NAME,
        "corpus_mode": CorpusMode.COMPETITION_SNAPSHOT.value,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "currentness_verified": False,
        "legal_reliance_allowed": False,
        "approved_for_competition_use": True,
        "usage_notice": COMPETITION_SNAPSHOT_NOTICE,
        "document_count": len(documents),
        "source_chunk_count": len(chunks),
        "chunk_count": len(chunks),
        "exact_duplicate_rows_consolidated": 0,
        "documents": documents,
        "data": chunks,
    }
    LegislationRepository.validate_competition_snapshot_envelope(corpus)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(corpus, ensure_ascii=False), encoding="utf-8")
    return {
        "corpus": str(args.output),
        "document_count": len(documents),
        "chunk_count": len(chunks),
        "ocr_document_count": ocr_document_count,
        "ocr_page_count": ocr_page_count,
        "metadata_fallback_page_count": metadata_fallback_page_count,
    }


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    result.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    result.add_argument("--ocr-dir", type=Path, default=DEFAULT_OCR_DIR)
    result.add_argument("--max-chars", type=_positive_int, default=1800)
    result.add_argument("--native-char-threshold", type=_positive_int, default=20)
    result.add_argument("--ocr-dpi", type=_positive_int, default=150)
    result.add_argument("--ocr-timeout", type=_positive_int, default=60)
    result.add_argument("--skip-ocr", action="store_true")
    result.add_argument("--limit", type=_positive_int)
    return result


def main() -> int:
    args = parser().parse_args()
    args.manifest = args.manifest.resolve()
    args.output = args.output.resolve()
    args.ocr_dir = args.ocr_dir.resolve()
    print(json.dumps(build(args), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
