from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import re
import unicodedata

from karayol_agent.documents.text_normalization import normalize_document_text
from karayol_agent.schemas import (
    ClassificationResult,
    DocumentAnalysis,
    ExtractedField,
    FieldStatus,
)
from karayol_agent.text_utils import (
    normalize_whitespace,
    truncate,
    turkish_lower,
)


_LABEL_ALIASES: dict[str, tuple[str, ...]] = {
    "gonderen": (
        "adı soyadı",
        "ad soyad",
        "gönderen",
        "gonderen",
        "gönderici",
        "gonderici",
        "gönderici adı",
        "gönderici adı soyadı",
        "gönderen kişi",
        "gönderen kurum",
        "gönderen makam",
        "gönderenin adı soyadı",
        "başvuran",
        "basvuran",
        "başvuru sahibi",
        "müracaatçı",
        "müracaat sahibi",
        "dilekçe sahibi",
    ),
    "konu": ("konu", "başvuru konusu", "talep konusu"),
    "konum": (
        "konum",
        "adres",
        "mevki",
        "lokasyon",
        "olay yeri",
        "talep yeri",
    ),
    "tarih": ("tarih", "başvuru tarihi", "düzenleme tarihi"),
}
_ASCII_FOLD = str.maketrans(
    {
        "ç": "c",
        "ğ": "g",
        "ı": "i",
        "ö": "o",
        "ş": "s",
        "ü": "u",
    }
)
_OCR_GLYPH_REPAIR = str.maketrans({"0": "o", "1": "i", "|": "i", "!": "i"})
_LABEL_TOKEN = re.compile(r"[0-9A-Za-zÇĞİÖŞÜçğıöşü|!]+")
_LABEL_SEPARATOR = re.compile(r"[:：=;]|[–—]|\s-\s")
_LABEL_ONLY_SUFFIX = re.compile(r"\s*(?:[:：=;]|[–—-])?\s*$")
_SEPARATOR_ONLY = re.compile(r"^(?:[:：=;]|[–—-])$")
_DATE_PATTERN = re.compile(r"\b\d{1,2}[./-]\d{1,2}[./-]\d{4}\b")
_OCR_DATE_PATTERN = re.compile(
    r"\b[0-9OoIl|]{1,2}[./-][0-9OoIl|]{1,2}[./-][0-9OoIl|]{4}\b"
)
_EMAIL_PATTERN = re.compile(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}")
_PHONE_PATTERN = re.compile(
    r"(?:\+?90\s*)?(?:0?5\d{2})[\s.-]?\d{3}[\s.-]?\d{2}[\s.-]?\d{2}"
)
_SUMMARY_AUXILIARY_LABEL = re.compile(
    r"^(?:telefon|e-?posta)\s*[:=;–—-]", re.IGNORECASE
)
_PLACEHOLDER_VALUES = {
    "-",
    "...",
    "belirsiz",
    "bilinmiyor",
    "bulunmuyor",
    "mevcut degil",
    "yok",
}
_REQUEST_MARKERS = (
    "talep ediyorum",
    "arz ederim",
    "rica ederim",
    "gereğini",
    "bildiriyorum",
)
_ORGANIZATION_SUFFIXES = (
    "başkanlığı",
    "başkanliği",
    "başkanligi",
    "dairesi",
    "genel müdürlüğü",
    "il müdürlüğü",
    "müdürlüğü",
    "mudurlugu",
    "şube müdürlüğü",
)
_SIGNATURE_NAME = re.compile(
    r"^(?:[A-ZÇĞİÖŞÜ][a-zçğıöşü]{1,24}|[A-ZÇĞİÖŞÜ]{2,25}|"
    r"[A-ZÇĞİÖŞÜ]\.)"
    r"(?:\s+(?:[A-ZÇĞİÖŞÜ][a-zçğıöşü]{1,24}|[A-ZÇĞİÖŞÜ]{2,25}|"
    r"[A-ZÇĞİÖŞÜ]\.)){1,3}$"
)
_SIGNATURE_NON_NAME_LINES = {
    "açıklamalar",
    "belge sonu",
    "ek bilgiler",
    "ekler",
    "iletişim bilgileri",
    "notlar",
}
_SIGNATURE_ROLE_MARKERS = (
    "başkan",
    "müdür",
    "uzman",
    "mühendis",
    "avukat",
    "koordinatör",
)
_SIGNATURE_HEADING_TOKENS = {
    "açıklamalar",
    "adresi",
    "belge",
    "bilgi",
    "bölümü",
    "dağıtım",
    "ek",
    "gereği",
    "iletişim",
    "listesi",
    "notu",
    "sonu",
    "sonuç",
}


def _compact_label(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", turkish_lower(value))
    return "".join(character for character in normalized if character.isalnum())


def _folded_label(value: str) -> str:
    return _compact_label(value).translate(_ASCII_FOLD)


_EXACT_LABELS = {
    _compact_label(alias): field_name
    for field_name, aliases in _LABEL_ALIASES.items()
    for alias in aliases
}
_FOLDED_LABELS = {
    _folded_label(alias): field_name
    for field_name, aliases in _LABEL_ALIASES.items()
    for alias in aliases
}


@dataclass(frozen=True)
class _LabelMatch:
    field_name: str
    normalized_by_ocr: bool


@dataclass(frozen=True)
class _LabelMarker:
    start: int
    value_start: int
    field_name: str
    normalized_by_ocr: bool


@dataclass(frozen=True)
class _FieldCandidate:
    value: str
    source: str
    priority: int


def _match_label(value: str) -> _LabelMatch | None:
    value = value.strip(" \t-*•#[](){}")
    if not value:
        return None
    exact = _compact_label(value)
    field_name = _EXACT_LABELS.get(exact)
    tokens = _LABEL_TOKEN.findall(value)
    spaced_letters = len(tokens) >= 4 and all(len(token) == 1 for token in tokens)
    if field_name:
        return _LabelMatch(field_name, normalized_by_ocr=spaced_letters)

    folded = _folded_label(value)
    repaired = folded.translate(_OCR_GLYPH_REPAIR)
    for candidate in (folded, repaired, repaired.replace("l", "i")):
        field_name = _FOLDED_LABELS.get(candidate)
        if field_name:
            return _LabelMatch(field_name, normalized_by_ocr=True)
    return None


def _label_markers(line: str) -> list[_LabelMarker]:
    markers: list[_LabelMarker] = []
    for separator in _LABEL_SEPARATOR.finditer(line):
        prefix = line[: separator.start()]
        tokens = list(_LABEL_TOKEN.finditer(prefix))
        if not tokens:
            continue
        matched_marker: _LabelMarker | None = None
        for token_index in range(max(0, len(tokens) - 12), len(tokens)):
            start = tokens[token_index].start()
            label = _match_label(prefix[start:])
            if label is None:
                continue
            matched_marker = _LabelMarker(
                start=start,
                value_start=separator.end(),
                field_name=label.field_name,
                normalized_by_ocr=label.normalized_by_ocr,
            )
            break
        if matched_marker and all(
            marker.start != matched_marker.start for marker in markers
        ):
            markers.append(matched_marker)

    if not markers:
        return []
    markers.sort(key=lambda marker: marker.start)
    leading = line[: markers[0].start].strip(" \t-*•#[](){}")
    return markers if not leading else []


def _unseparated_label(line: str) -> tuple[_LabelMatch, str] | None:
    """Accept a missing OCR separator only for a visibly uppercase label."""

    tokens = list(_LABEL_TOKEN.finditer(line))
    if not tokens:
        return None
    first_start = tokens[0].start()
    if line[:first_start].strip(" \t-*•#[](){}"):
        return None
    best: tuple[_LabelMatch, str, str] | None = None
    for token_index in range(min(len(tokens), 12)):
        end = tokens[token_index].end()
        raw_label = line[first_start:end]
        label = _match_label(raw_label)
        remainder = line[end:].strip()
        if label is not None and remainder:
            best = (label, remainder, raw_label)
    if best is None:
        return None
    label, remainder, raw_label = best
    letters = "".join(character for character in raw_label if character.isalpha())
    if not letters or letters != letters.upper():
        return None
    tokens = _LABEL_TOKEN.findall(raw_label)
    visibly_ocr = any(character in raw_label for character in "01|!") or (
        len(tokens) >= 4 and all(len(token) == 1 for token in tokens)
    )
    if label.field_name == "gonderen" and not visibly_ocr:
        normalized_remainder = turkish_lower(remainder)
        if not _SIGNATURE_NAME.fullmatch(remainder) and not any(
            suffix in normalized_remainder for suffix in _ORGANIZATION_SUFFIXES
        ):
            return None
    elif label.field_name == "tarih":
        if _OCR_DATE_PATTERN.fullmatch(remainder) is None:
            return None
    elif not visibly_ocr:
        return None
    return _LabelMatch(label.field_name, normalized_by_ocr=True), remainder


class ContentAnalysisAgent:
    name = "İçerik Analizi Ajanı"

    REQUIRED_FIELDS: dict[str, tuple[str, ...]] = {
        "yol_bakim_talebi": ("gonderen", "konu", "konum", "talep"),
        "trafik_guvenligi_bildirimi": ("gonderen", "konu", "konum", "talep"),
        "hasar_bildirimi": ("gonderen", "konu", "konum", "talep"),
        "bilgi_talebi": ("gonderen", "konu", "talep"),
        "sikayet": ("gonderen", "konu", "talep"),
        "dilekce": ("gonderen", "konu", "talep"),
        "ust_yazi": ("gonderen", "konu", "tarih"),
        "genel_basvuru": ("gonderen", "konu", "talep"),
    }

    def run(
        self, text: str, classification: ClassificationResult
    ) -> DocumentAnalysis:
        normalized_text = normalize_document_text(text)
        candidates = self._extract_labeled_fields(normalized_text)
        fields = {
            field_name: self._field(candidate.value, candidate.source)
            for field_name, candidate in candidates.items()
        }
        for field_name in _LABEL_ALIASES:
            fields.setdefault(field_name, self._field(None, None))

        if fields["tarih"].value is None:
            fallback_date = self._find_date(normalized_text)
            fields["tarih"] = self._field(
                fallback_date, "metin:tarih" if fallback_date else None
            )

        email_match = _EMAIL_PATTERN.search(normalized_text)
        fields["eposta"] = self._field(
            email_match.group(0) if email_match else None,
            "metin:eposta" if email_match else None,
        )
        phone_match = _PHONE_PATTERN.search(normalized_text)
        fields["telefon"] = self._field(
            phone_match.group(0) if phone_match else None,
            "metin:telefon" if phone_match else None,
        )

        if fields["gonderen"].value is None:
            signature_sender = self._infer_signature_sender(normalized_text)
            if signature_sender:
                fields["gonderen"] = self._field(
                    signature_sender, "metin:imza-bloku"
                )

        request = self._find_request_sentence(normalized_text)
        fields["talep"] = self._field(
            request, "metin:talep" if request else None
        )
        if fields["konu"].value is None:
            fields["konu"] = self._field(
                self._infer_subject(normalized_text, classification.document_type),
                "metin:konu",
            )

        required = self.REQUIRED_FIELDS.get(
            classification.document_type, self.REQUIRED_FIELDS["genel_basvuru"]
        )
        missing = [
            name for name in required if not fields.get(name) or not fields[name].value
        ]
        for name in missing:
            fields.setdefault(
                name,
                ExtractedField(value=None, status=FieldStatus.USER_REQUIRED),
            )

        keywords = list(
            dict.fromkeys(
                classification.matched_keywords
                + self._domain_keywords(normalized_text)
            )
        )
        return DocumentAnalysis(
            document_type=classification.document_type,
            # OCR normalization must never inflate the classifier's confidence.
            confidence=classification.confidence,
            summary=self._summarize(normalized_text),
            # Retrieval provenance stays bound to the submitted text, not to
            # label repairs used only by structured field extraction.
            retrieval_evidence_text=truncate(normalize_whitespace(text), 4000),
            fields=fields,
            missing_fields=missing,
            keywords=keywords,
        )

    def _extract_labeled_fields(self, text: str) -> dict[str, _FieldCandidate]:
        lines = text.splitlines()
        candidates: dict[str, _FieldCandidate] = {}
        for line_index, line in enumerate(lines):
            if not line:
                continue
            segments = self._segments_from_line(line)
            for segment_index, (label, raw_value) in enumerate(segments):
                value = self._clean_value(raw_value)
                joined_lines = False
                if not value:
                    value = self._next_line_value(
                        lines, line_index, label.field_name
                    )
                    joined_lines = bool(value)
                elif segment_index == len(segments) - 1:
                    continuation = self._continuation_value(
                        lines, line_index, label.field_name, value
                    )
                    if continuation != value:
                        value = continuation
                        joined_lines = True

                value = self._validated_value(label.field_name, value)
                if not value:
                    continue
                source, priority = self._candidate_provenance(
                    label.field_name,
                    normalized_by_ocr=label.normalized_by_ocr,
                    joined_lines=joined_lines,
                )
                candidate = _FieldCandidate(value, source, priority)
                current = candidates.get(label.field_name)
                if current is None or candidate.priority > current.priority:
                    candidates[label.field_name] = candidate
        return candidates

    @staticmethod
    def _segments_from_line(line: str) -> list[tuple[_LabelMatch, str]]:
        markers = _label_markers(line)
        if markers:
            segments: list[tuple[_LabelMatch, str]] = []
            for index, marker in enumerate(markers):
                value_end = (
                    markers[index + 1].start
                    if index + 1 < len(markers)
                    else len(line)
                )
                segments.append(
                    (
                        _LabelMatch(
                            marker.field_name, marker.normalized_by_ocr
                        ),
                        line[marker.value_start:value_end],
                    )
                )
            return segments

        stripped = _LABEL_ONLY_SUFFIX.sub("", line)
        label = _match_label(stripped)
        if label is not None:
            return [(label, "")]
        unseparated = _unseparated_label(line)
        return [unseparated] if unseparated else []

    @classmethod
    def _next_line_value(
        cls, lines: list[str], line_index: int, field_name: str
    ) -> str | None:
        next_index = line_index + 1
        if next_index >= len(lines) or not lines[next_index]:
            return None
        if _SEPARATOR_ONLY.fullmatch(lines[next_index].strip()):
            next_index += 1
        if next_index >= len(lines) or not lines[next_index]:
            return None
        if cls._segments_from_line(lines[next_index]):
            return None
        value = cls._clean_value(lines[next_index])
        if not value:
            return None
        return cls._append_safe_continuation(
            lines, next_index, field_name, value
        )

    @classmethod
    def _continuation_value(
        cls, lines: list[str], line_index: int, field_name: str, value: str
    ) -> str:
        return cls._append_safe_continuation(
            lines, line_index, field_name, value
        )

    @classmethod
    def _append_safe_continuation(
        cls, lines: list[str], line_index: int, field_name: str, value: str
    ) -> str:
        next_index = line_index + 1
        if next_index >= len(lines):
            return value
        following = lines[next_index]
        if (
            not following
            or cls._segments_from_line(following)
            or not cls._should_join_continuation(field_name, value, following)
        ):
            return value
        return normalize_whitespace(f"{value} {following}")

    @staticmethod
    def _should_join_continuation(
        field_name: str, value: str, following: str
    ) -> bool:
        if len(value) + len(following) + 1 > 180:
            return False
        normalized_following = turkish_lower(following)
        if any(marker in normalized_following for marker in _REQUEST_MARKERS):
            return False
        if field_name == "gonderen":
            if value.rstrip().endswith((",", "/", "-")):
                return True
            if any(
                suffix in normalized_following
                for suffix in _ORGANIZATION_SUFFIXES
            ):
                return True
            combined = f"{value} {following}"
            return bool(_SIGNATURE_NAME.fullmatch(combined))
        if field_name in {"konu", "konum"}:
            return value.rstrip().endswith((",", "/", "-")) or bool(
                re.match(r"^[a-zçğıöşü]", following)
            )
        return False

    @staticmethod
    def _candidate_provenance(
        field_name: str,
        *,
        normalized_by_ocr: bool,
        joined_lines: bool,
    ) -> tuple[str, int]:
        if joined_lines:
            return f"etiket:{field_name}:ocr-line-join", (
                65 if normalized_by_ocr else 75
            )
        if normalized_by_ocr:
            return f"etiket:{field_name}:ocr-normalized", 85
        return f"etiket:{field_name}", 100

    @staticmethod
    def _clean_value(value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = normalize_whitespace(value).strip(" \t:;=-–—•|")
        return cleaned or None

    @classmethod
    def _validated_value(
        cls, field_name: str, value: str | None
    ) -> str | None:
        value = cls._clean_value(value)
        if value is None:
            return None
        folded = _folded_label(value)
        if folded in {_folded_label(item) for item in _PLACEHOLDER_VALUES}:
            return None
        if field_name == "tarih":
            return cls._normalize_date(value)
        if field_name == "eposta":
            return value if _EMAIL_PATTERN.fullmatch(value) else None
        if field_name == "telefon":
            return value if _PHONE_PATTERN.fullmatch(value) else None
        if len(value) < 2 or len(value) > (180 if field_name == "gonderen" else 300):
            return None
        if field_name == "gonderen":
            normalized = turkish_lower(value)
            if len(value.split()) > 18 or any(
                marker in normalized for marker in _REQUEST_MARKERS
            ):
                return None
            if len(re.findall(r"[A-Za-zÇĞİÖŞÜçğıöşü]", value)) < 2:
                return None
        if field_name == "talep" and not any(
            marker in turkish_lower(value)
            for marker in (*_REQUEST_MARKERS, "istiyorum")
        ):
            return None
        return value

    @classmethod
    def validate_external_candidate(
        cls, field_name: str, value: str | None
    ) -> str | None:
        """Apply the same field semantics to evidence-bound external candidates."""
        return cls._validated_value(field_name, value)

    @staticmethod
    def _field(value: str | None, source: str | None) -> ExtractedField:
        return ExtractedField(
            value=value,
            status=FieldStatus.INFERRED if value else FieldStatus.USER_REQUIRED,
            source=source,
        )

    @classmethod
    def _normalize_date(cls, value: str) -> str | None:
        match = _OCR_DATE_PATTERN.fullmatch(value.strip())
        if match is None:
            return None
        normalized = match.group(0).translate(
            str.maketrans(
                {
                    "O": "0",
                    "o": "0",
                    "I": "1",
                    "l": "1",
                    "|": "1",
                }
            )
        )
        day_text, month_text, year_text = re.split(r"[./-]", normalized)
        try:
            date(int(year_text), int(month_text), int(day_text))
        except ValueError:
            return None
        separator = "." if "." in normalized else "/" if "/" in normalized else "-"
        return separator.join((day_text, month_text, year_text))

    @classmethod
    def _find_date(cls, text: str) -> str | None:
        for match in _DATE_PATTERN.finditer(text):
            normalized = cls._normalize_date(match.group(0))
            if normalized:
                return normalized
        return None

    @staticmethod
    def _find_request_sentence(text: str) -> str | None:
        sentences = re.split(r"(?<=[.!?])\s+|\n+", text)
        markers = (
            "talep",
            "arz eder",
            "rica eder",
            "gereğini",
            "istiyorum",
            "bildiriyorum",
        )
        for sentence in sentences:
            if any(marker in turkish_lower(sentence) for marker in markers):
                return truncate(sentence, 400)
        return None

    @staticmethod
    def _infer_signature_sender(text: str) -> str | None:
        lines = text.splitlines()
        for index, line in enumerate(lines):
            normalized = turkish_lower(line)
            if not any(
                marker in normalized
                for marker in ("saygılarımla", "arz ederim", "rica ederim")
            ):
                continue
            candidate_lines = [
                candidate
                for candidate in lines[index + 1 : index + 4]
                if candidate
            ]
            if not candidate_lines:
                continue
            first = normalize_whitespace(candidate_lines[0])
            if len(candidate_lines) >= 2:
                second = normalize_whitespace(candidate_lines[1])
                second_letters = "".join(
                    character for character in second if character.isalpha()
                )
                combined = normalize_whitespace(f"{first} {second}")
                if (
                    len(second.split()) == 1
                    and second_letters
                    and second_letters == second_letters.upper()
                    and len(combined) <= 100
                    and _SIGNATURE_NAME.fullmatch(combined)
                    and ContentAnalysisAgent._is_signature_name_candidate(combined)
                ):
                    return combined
            normalized_first = turkish_lower(first)
            if (
                len(first) <= 100
                and _SIGNATURE_NAME.fullmatch(first)
                and ContentAnalysisAgent._is_signature_name_candidate(first)
                and (
                    ContentAnalysisAgent._has_uppercase_signature_surname(first)
                    or (
                        len(candidate_lines) >= 2
                        and ContentAnalysisAgent._is_signature_role_line(
                            candidate_lines[1]
                        )
                    )
                )
                and not any(
                    suffix in normalized_first
                    for suffix in _ORGANIZATION_SUFFIXES
                )
            ):
                return first
        return None

    @staticmethod
    def _is_signature_name_candidate(value: str) -> bool:
        normalized = turkish_lower(normalize_whitespace(value)).strip(" .:")
        if normalized in _SIGNATURE_NON_NAME_LINES:
            return False
        tokens = set(re.findall(r"[a-zçğıöşü]+", normalized))
        if tokens & _SIGNATURE_HEADING_TOKENS:
            return False
        return not any(marker in normalized for marker in _SIGNATURE_ROLE_MARKERS)

    @staticmethod
    def _has_uppercase_signature_surname(value: str) -> bool:
        words = value.split()
        if len(words) < 2:
            return False
        surname_letters = "".join(
            character for character in words[-1] if character.isalpha()
        )
        return (
            len(surname_letters) >= 2
            and surname_letters == surname_letters.upper()
        )

    @staticmethod
    def _is_signature_role_line(value: str) -> bool:
        normalized = turkish_lower(normalize_whitespace(value))
        return any(marker in normalized for marker in _SIGNATURE_ROLE_MARKERS)

    @staticmethod
    def _infer_subject(text: str, document_type: str) -> str:
        labels = {
            "yol_bakim_talebi": "Yol bakım talebi",
            "trafik_guvenligi_bildirimi": "Trafik güvenliği bildirimi",
            "hasar_bildirimi": "Karayolu hasar bildirimi",
            "bilgi_talebi": "Bilgi talebi",
            "sikayet": "Şikâyet başvurusu",
            "dilekce": "Başvuru talebi",
            "ust_yazi": "Resmî yazışma",
            "genel_basvuru": "Genel başvuru",
        }
        return labels.get(document_type, truncate(text, 80))

    @classmethod
    def _summarize(cls, text: str) -> str:
        parts = [
            part.strip()
            for part in re.split(r"(?<=[.!?])\s+|\n+", text)
            if part.strip()
        ]
        sentences = [
            part
            for part in parts
            if not cls._segments_from_line(part)
            and not _SUMMARY_AUXILIARY_LABEL.match(part)
        ] or parts
        return truncate(" ".join(sentences[:2]), 360)

    @staticmethod
    def _domain_keywords(text: str) -> list[str]:
        normalized = turkish_lower(text)
        candidates = (
            "karayolu",
            "otoyol",
            "asfalt",
            "çukur",
            "bariyer",
            "trafik",
            "bakım",
            "onarım",
            "hasar",
            "levha",
            "köprü",
        )
        return [keyword for keyword in candidates if keyword in normalized]
