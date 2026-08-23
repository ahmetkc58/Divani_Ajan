from __future__ import annotations

import json
from pathlib import Path

from karayol_agent.ingestion.chunker import LegalStructureChunker
from karayol_agent.ingestion.quality import assess_text_layer
from karayol_agent.schemas import IngestionReport


class LegislationIngestionService:
    def __init__(self, chunker: LegalStructureChunker | None = None) -> None:
        self.chunker = chunker or LegalStructureChunker()

    def ingest_pdf(
        self,
        path: Path,
        *,
        title: str,
        source_status: str,
        output_path: Path,
        allow_low_quality: bool = False,
    ) -> IngestionReport:
        page_texts = self._read_pages(path)
        quality = assess_text_layer(page_texts)
        if quality.requires_ocr and not allow_low_quality:
            return IngestionReport(
                source_file=str(path.resolve()),
                title=title,
                source_status=source_status,
                quality=quality,
                chunk_count=0,
            )

        text = "\n\n".join(page_texts)
        chunks = self.chunker.chunk(
            text,
            title=title,
            source=str(path.resolve()),
            source_status=source_status,
        )
        output_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "dataset_name": title,
            "source_file": str(path.resolve()),
            "source_status": source_status,
            "quality": quality.model_dump(mode="json"),
            "data": [chunk.model_dump(mode="json") for chunk in chunks],
        }
        output_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return IngestionReport(
            source_file=str(path.resolve()),
            title=title,
            source_status=source_status,
            quality=quality,
            chunk_count=len(chunks),
            output_file=str(output_path.resolve()),
        )

    @staticmethod
    def _read_pages(path: Path) -> list[str]:
        try:
            import pymupdf

            document = pymupdf.open(path)
            try:
                return [page.get_text("text") for page in document]
            finally:
                document.close()
        except ImportError:
            from pypdf import PdfReader

            reader = PdfReader(str(path))
            return [(page.extract_text() or "") for page in reader.pages]
