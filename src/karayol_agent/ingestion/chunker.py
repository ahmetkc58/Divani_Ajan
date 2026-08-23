from __future__ import annotations

import re
from hashlib import sha256

from karayol_agent.schemas import LegislationChunk
from karayol_agent.text_utils import normalize_whitespace


class StructureNotFoundError(ValueError):
    pass


class LegalStructureChunker:
    """Türkçe mevzuatı öncelikle Madde -> Fıkra yapısında parçalar."""

    ARTICLE_PATTERN = re.compile(
        r"(?i)\b(?P<label>(?:GEÇİCİ\s+)?MADDE\s+(?P<number>\d+[A-ZÇĞİÖŞÜ]?))\s*[-–—]"
    )
    PARAGRAPH_PATTERN = re.compile(r"(?<!\w)\((?P<number>\d+)\)\s*")

    def __init__(self, max_chars: int = 1800) -> None:
        self.max_chars = max_chars

    def chunk(
        self,
        text: str,
        *,
        title: str,
        source: str,
        source_status: str,
    ) -> list[LegislationChunk]:
        article_matches = list(self.ARTICLE_PATTERN.finditer(text))
        if not article_matches:
            raise StructureNotFoundError(
                "Metinde MADDE yapısı bulunamadı; OCR/metin kalitesi doğrulanmalıdır."
            )

        chunks: list[LegislationChunk] = []
        for index, match in enumerate(article_matches):
            start = match.end()
            end = (
                article_matches[index + 1].start()
                if index + 1 < len(article_matches)
                else len(text)
            )
            body = normalize_whitespace(text[start:end])
            article_label = normalize_whitespace(match.group("label")).title()
            if not body:
                continue
            paragraph_matches = list(self.PARAGRAPH_PATTERN.finditer(body))
            if paragraph_matches:
                for paragraph_index, paragraph_match in enumerate(paragraph_matches):
                    paragraph_start = paragraph_match.end()
                    paragraph_end = (
                        paragraph_matches[paragraph_index + 1].start()
                        if paragraph_index + 1 < len(paragraph_matches)
                        else len(body)
                    )
                    paragraph_text = normalize_whitespace(
                        body[paragraph_start:paragraph_end]
                    )
                    if paragraph_text:
                        chunks.extend(
                            self._bounded_chunks(
                                paragraph_text,
                                title=title,
                                source=source,
                                status=source_status,
                                article=article_label,
                                paragraph=paragraph_match.group("number"),
                            )
                        )
            else:
                chunks.extend(
                    self._bounded_chunks(
                        body,
                        title=title,
                        source=source,
                        status=source_status,
                        article=article_label,
                        paragraph=None,
                    )
                )
        return chunks

    def _bounded_chunks(
        self,
        text: str,
        *,
        title: str,
        source: str,
        status: str,
        article: str,
        paragraph: str | None,
    ) -> list[LegislationChunk]:
        if len(text) <= self.max_chars:
            parts = [text]
        else:
            sentences = re.split(r"(?<=[.!?;])\s+", text)
            parts: list[str] = []
            current = ""
            for sentence in sentences:
                candidate = f"{current} {sentence}".strip()
                if current and len(candidate) > self.max_chars:
                    parts.append(current)
                    current = sentence
                else:
                    current = candidate
            if current:
                parts.append(current)

        result: list[LegislationChunk] = []
        for part_index, part in enumerate(parts, start=1):
            identity = f"{source}|{article}|{paragraph}|{part_index}|{part}"
            chunk_id = "MEV-" + sha256(identity.encode("utf-8")).hexdigest()[:16].upper()
            result.append(
                LegislationChunk(
                    chunk_id=chunk_id,
                    title=title,
                    section=article,
                    article=article,
                    paragraph=paragraph,
                    text=part,
                    source=source,
                    status=status,
                    tags=[article, f"fıkra {paragraph}" if paragraph else ""],
                )
            )
        return result

