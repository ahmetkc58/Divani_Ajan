from __future__ import annotations

import re
from collections.abc import Callable
from hashlib import sha256

from karayol_agent.schemas import LegislationChunk
from karayol_agent.text_utils import normalize_whitespace


class StructureNotFoundError(ValueError):
    pass


PageResolver = Callable[[int, int], tuple[int | None, int | None]]

_TURKISH_LOWER = str.maketrans("IİŞĞÜÖÇ", "ıişğüöç")
_TURKISH_INITIAL_UPPER = {
    "ı": "I",
    "i": "İ",
    "ş": "Ş",
    "ğ": "Ğ",
    "ü": "Ü",
    "ö": "Ö",
    "ç": "Ç",
}


class LegalStructureChunker:
    """Türkçe mevzuatı Bölüm -> Madde -> Fıkra -> Bent yapısında parçalar."""

    ARTICLE_PATTERN = re.compile(
        r"(?i)\b(?P<label>(?:(?:GEÇİCİ|EK)\s+)?MADDE\s+"
        r"(?P<number>\d+[A-ZÇĞİÖŞÜ]?))\s*[-–—]"
    )
    PARAGRAPH_PATTERN = re.compile(r"(?<!\w)\((?P<number>\d+)\)\s*")
    CLAUSE_PATTERN = re.compile(
        r"(?<!\w)(?:\((?P<parenthesized>[a-zçğıöşü])\)|"
        r"(?P<plain>[a-zçğıöşü])\))\s*",
        re.I,
    )
    SECTION_PATTERN = re.compile(
        r"(?i)\b(?P<label>(?:BİRİNCİ|İKİNCİ|ÜÇÜNCÜ|DÖRDÜNCÜ|BEŞİNCİ|"
        r"ALTINCI|YEDİNCİ|SEKİZİNCİ|DOKUZUNCU|ONUNCU|\d+\.?)\s+BÖLÜM)\b"
        r"(?:\s*[-–—:]?\s*(?P<title>[^\n]{0,180}))?"
    )

    def __init__(self, max_chars: int = 1800) -> None:
        if max_chars < 1:
            raise ValueError("max_chars pozitif olmalıdır.")
        self.max_chars = max_chars

    def chunk(
        self,
        text: str,
        *,
        title: str,
        source: str,
        source_status: str,
        document_id: str | None = None,
        source_url: str | None = None,
        source_sha256: str | None = None,
        source_kind: str = "unknown",
        document_type: str = "unknown",
        domain: str = "unknown",
        subdomain: str = "unknown",
        validity_status: str = "needs_verification",
        approved_for_active_rag: bool = False,
        ocr_status: str = "not_inspected",
    ) -> list[LegislationChunk]:
        return self._chunk_text(
            text,
            title=title,
            source=source,
            source_status=source_status,
            document_id=document_id,
            source_url=source_url,
            source_sha256=source_sha256,
            source_kind=source_kind,
            document_type=document_type,
            domain=domain,
            subdomain=subdomain,
            validity_status=validity_status,
            approved_for_active_rag=approved_for_active_rag,
            ocr_status=ocr_status,
            page_resolver=None,
        )

    def chunk_pages(
        self,
        page_texts: list[str],
        *,
        title: str,
        source: str,
        source_status: str,
        document_id: str | None = None,
        source_url: str | None = None,
        source_sha256: str | None = None,
        source_kind: str = "unknown",
        document_type: str = "unknown",
        domain: str = "unknown",
        subdomain: str = "unknown",
        validity_status: str = "needs_verification",
        approved_for_active_rag: bool = False,
        ocr_status: str = "not_inspected",
    ) -> list[LegislationChunk]:
        """Sayfa sınırlarını koruyarak mevzuat parçaları üretir."""

        separator = "\n\f\n"
        starts: list[int] = []
        combined_parts: list[str] = []
        cursor = 0
        for index, page_text in enumerate(page_texts):
            if index:
                cursor += len(separator)
            starts.append(cursor)
            combined_parts.append(page_text)
            cursor += len(page_text)
        combined = separator.join(combined_parts)

        def resolve_pages(start: int, end: int) -> tuple[int | None, int | None]:
            if not starts:
                return None, None
            start_page = self._page_for_offset(starts, max(start, 0))
            last_offset = max(start, end - 1)
            end_page = self._page_for_offset(starts, last_offset)
            return start_page, end_page

        return self._chunk_text(
            combined,
            title=title,
            source=source,
            source_status=source_status,
            document_id=document_id,
            source_url=source_url,
            source_sha256=source_sha256,
            source_kind=source_kind,
            document_type=document_type,
            domain=domain,
            subdomain=subdomain,
            validity_status=validity_status,
            approved_for_active_rag=approved_for_active_rag,
            ocr_status=ocr_status,
            page_resolver=resolve_pages,
        )

    def _chunk_text(
        self,
        text: str,
        *,
        title: str,
        source: str,
        source_status: str,
        document_id: str | None,
        source_url: str | None,
        source_sha256: str | None,
        source_kind: str,
        document_type: str,
        domain: str,
        subdomain: str,
        validity_status: str,
        approved_for_active_rag: bool,
        ocr_status: str,
        page_resolver: PageResolver | None,
    ) -> list[LegislationChunk]:
        article_matches = list(self.ARTICLE_PATTERN.finditer(text))
        if not article_matches:
            raise StructureNotFoundError(
                "Metinde MADDE yapısı bulunamadı; OCR/metin kalitesi doğrulanmalıdır."
            )

        sections = list(self.SECTION_PATTERN.finditer(text))
        common = {
            "title": title,
            "source": source,
            "status": source_status,
            "document_id": document_id,
            "source_url": source_url,
            "source_sha256": source_sha256,
            "source_kind": source_kind,
            "document_type": document_type,
            "domain": domain,
            "subdomain": subdomain,
            "validity_status": validity_status,
            "approved_for_active_rag": approved_for_active_rag,
            "ocr_status": ocr_status,
            "page_resolver": page_resolver,
        }

        chunks: list[LegislationChunk] = []
        for index, match in enumerate(article_matches):
            body_start = match.end()
            body_end = (
                article_matches[index + 1].start()
                if index + 1 < len(article_matches)
                else len(text)
            )
            next_sections = [
                section.start()
                for section in sections
                if match.end() < section.start() < body_end
            ]
            if next_sections:
                body_end = min(next_sections)
            article_label = self._turkish_title(
                normalize_whitespace(match.group("label"))
            )
            section = self._section_for(sections, match.start(), article_label)
            body = text[body_start:body_end]
            paragraph_matches = list(self.PARAGRAPH_PATTERN.finditer(body))

            if not paragraph_matches:
                chunks.extend(
                    self._split_clauses_or_chunk(
                        body,
                        absolute_start=body_start,
                        article=article_label,
                        paragraph=None,
                        section=section,
                        **common,
                    )
                )
                continue

            preamble = body[: paragraph_matches[0].start()]
            if normalize_whitespace(preamble):
                chunks.extend(
                    self._bounded_chunks(
                        preamble,
                        absolute_start=body_start,
                        absolute_end=body_start + paragraph_matches[0].start(),
                        article=article_label,
                        paragraph=None,
                        clause=None,
                        context_hint=None,
                        section=section,
                        **common,
                    )
                )

            for paragraph_index, paragraph_match in enumerate(paragraph_matches):
                paragraph_start = paragraph_match.end()
                paragraph_end = (
                    paragraph_matches[paragraph_index + 1].start()
                    if paragraph_index + 1 < len(paragraph_matches)
                    else len(body)
                )
                paragraph_text = body[paragraph_start:paragraph_end]
                chunks.extend(
                    self._split_clauses_or_chunk(
                        paragraph_text,
                        absolute_start=body_start + paragraph_start,
                        article=article_label,
                        paragraph=paragraph_match.group("number"),
                        section=section,
                        **common,
                    )
                )
        return chunks

    def _split_clauses_or_chunk(
        self,
        text: str,
        *,
        absolute_start: int,
        article: str,
        paragraph: str | None,
        section: str,
        **common: object,
    ) -> list[LegislationChunk]:
        clause_matches = list(self.CLAUSE_PATTERN.finditer(text))
        if not clause_matches:
            return self._bounded_chunks(
                text,
                absolute_start=absolute_start,
                absolute_end=absolute_start + len(text),
                article=article,
                paragraph=paragraph,
                clause=None,
                context_hint=None,
                section=section,
                **common,
            )

        prefix = normalize_whitespace(text[: clause_matches[0].start()])
        chunks: list[LegislationChunk] = []
        for clause_index, clause_match in enumerate(clause_matches):
            content_start = clause_match.end()
            content_end = (
                clause_matches[clause_index + 1].start()
                if clause_index + 1 < len(clause_matches)
                else len(text)
            )
            content = normalize_whitespace(text[content_start:content_end])
            if not content:
                continue
            clause_marker = normalize_whitespace(clause_match.group(0))
            clause_text = f"{clause_marker} {content}".strip()
            clause = clause_match.group("parenthesized") or clause_match.group("plain")
            chunks.extend(
                self._bounded_chunks(
                    clause_text,
                    absolute_start=absolute_start + clause_match.start(),
                    absolute_end=absolute_start + content_end,
                    article=article,
                    paragraph=paragraph,
                    clause=clause.lower(),
                    context_hint=prefix or None,
                    section=section,
                    **common,
                )
            )
        return chunks

    def _bounded_chunks(
        self,
        text: str,
        *,
        absolute_start: int,
        absolute_end: int,
        title: str,
        source: str,
        status: str,
        document_id: str | None,
        source_url: str | None,
        source_sha256: str | None,
        source_kind: str,
        document_type: str,
        domain: str,
        subdomain: str,
        validity_status: str,
        approved_for_active_rag: bool,
        ocr_status: str,
        article: str,
        paragraph: str | None,
        clause: str | None,
        context_hint: str | None,
        section: str,
        page_resolver: PageResolver | None,
    ) -> list[LegislationChunk]:
        normalized = normalize_whitespace(text)
        if not normalized:
            return []
        parts = self._split_bounded(normalized)
        page, page_end = (
            page_resolver(absolute_start, absolute_end)
            if page_resolver
            else (None, None)
        )

        identity_source = document_id or source
        result: list[LegislationChunk] = []
        for part_index, part in enumerate(parts, start=1):
            identity = (
                f"{identity_source}|{section}|{article}|{paragraph}|{clause}|"
                f"{part_index}|{part}"
            )
            chunk_id = "MEV-" + sha256(identity.encode("utf-8")).hexdigest()[:16].upper()
            tags = [section, article]
            if paragraph:
                tags.append(f"fıkra {paragraph}")
            if clause:
                tags.append(f"bent {clause}")
            context_parts = [title, section, article]
            if paragraph:
                context_parts.append(f"Fıkra {paragraph}")
            if clause:
                context_parts.append(f"Bent {clause}")
            if context_hint:
                context_parts.append(
                    f"Yerel bağlam: {self._context_excerpt(context_hint)}"
                )
            result.append(
                LegislationChunk(
                    chunk_id=chunk_id,
                    document_id=document_id,
                    title=title,
                    section=section,
                    article=article,
                    paragraph=paragraph,
                    clause=clause,
                    text=part,
                    source=source,
                    source_sha256=source_sha256,
                    source_kind=source_kind,
                    page=page,
                    page_end=page_end,
                    source_url=source_url,
                    document_type=document_type,
                    domain=domain,
                    subdomain=subdomain,
                    validity_status=validity_status,
                    approved_for_active_rag=approved_for_active_rag,
                    ocr_status=ocr_status,
                    context_text=" > ".join(context_parts),
                    status=status,
                    tags=tags,
                )
            )
        return result

    def _split_bounded(self, text: str) -> list[str]:
        if len(text) <= self.max_chars:
            return [text]

        sentences = [
            normalize_whitespace(sentence)
            for sentence in re.split(r"(?<=[.!?;])\s+", text)
            if normalize_whitespace(sentence)
        ]
        parts: list[str] = []
        current = ""
        for sentence in sentences:
            if len(sentence) > self.max_chars:
                if current:
                    parts.append(current)
                    current = ""
                parts.extend(self._hard_split(sentence))
                continue
            candidate = f"{current} {sentence}".strip()
            if current and len(candidate) > self.max_chars:
                parts.append(current)
                current = sentence
            else:
                current = candidate
        if current:
            parts.append(current)
        return parts

    def _hard_split(self, text: str) -> list[str]:
        words = text.split()
        parts: list[str] = []
        current = ""
        for word in words:
            if len(word) > self.max_chars:
                if current:
                    parts.append(current)
                    current = ""
                parts.extend(
                    word[start : start + self.max_chars]
                    for start in range(0, len(word), self.max_chars)
                )
                continue
            candidate = f"{current} {word}".strip()
            if current and len(candidate) > self.max_chars:
                parts.append(current)
                current = word
            else:
                current = candidate
        if current:
            parts.append(current)
        return parts

    @staticmethod
    def _context_excerpt(value: str, max_chars: int = 480) -> str:
        normalized = normalize_whitespace(value)
        if len(normalized) <= max_chars:
            return normalized
        side = (max_chars - 3) // 2
        return f"{normalized[:side]}...{normalized[-side:]}"

    @staticmethod
    def _page_for_offset(starts: list[int], offset: int) -> int:
        page = 1
        for page_number, start in enumerate(starts, start=1):
            if start > offset:
                break
            page = page_number
        return page

    @staticmethod
    def _section_for(
        sections: list[re.Match[str]], article_offset: int, fallback: str
    ) -> str:
        previous = [section for section in sections if section.start() < article_offset]
        if not previous:
            return fallback
        match = previous[-1]
        label = LegalStructureChunker._turkish_title(
            normalize_whitespace(match.group("label"))
        )
        raw_title = match.group("title") or ""
        raw_title = re.split(
            r"(?i)\b(?:(?:GEÇİCİ|EK)\s+)?MADDE\b", raw_title, maxsplit=1
        )[0]
        section_title = normalize_whitespace(raw_title).strip(" -–—:")
        return f"{label} — {section_title}" if section_title else label

    @staticmethod
    def _turkish_title(value: str) -> str:
        lowered = value.translate(_TURKISH_LOWER).lower()
        parts = re.split(r"(\s+)", lowered)
        titled: list[str] = []
        for part in parts:
            if not part or part.isspace():
                titled.append(part)
                continue
            first = _TURKISH_INITIAL_UPPER.get(part[0], part[0].upper())
            titled.append(first + part[1:])
        return "".join(titled)
