from __future__ import annotations

import re

from karayol_agent.schemas import (
    ClassificationResult,
    DocumentAnalysis,
    ExtractedField,
    FieldStatus,
)
from karayol_agent.text_utils import normalize_whitespace, truncate


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

    _LABELED_PATTERNS = {
        "gonderen": re.compile(
            r"(?:ad[ıi]\s*soyad[ıi]|gönderen|başvuran)\s*[:\-]\s*([^\n,;]+)", re.I
        ),
        "konu": re.compile(r"(?:konu)\s*[:\-]\s*([^\n]+)", re.I),
        "konum": re.compile(
            r"(?:konum|adres|mevki|lokasyon)\s*[:\-]\s*([^\n;]+)", re.I
        ),
        "tarih": re.compile(
            r"(?:tarih)\s*[:\-]\s*(\d{1,2}[./-]\d{1,2}[./-]\d{4})", re.I
        ),
    }
    _DATE_PATTERN = re.compile(r"\b\d{1,2}[./-]\d{1,2}[./-]\d{4}\b")
    _EMAIL_PATTERN = re.compile(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}")
    _PHONE_PATTERN = re.compile(r"(?:\+?90\s*)?(?:0?5\d{2})[\s.-]?\d{3}[\s.-]?\d{2}[\s.-]?\d{2}")

    def run(
        self, text: str, classification: ClassificationResult
    ) -> DocumentAnalysis:
        fields: dict[str, ExtractedField] = {}
        for field_name, pattern in self._LABELED_PATTERNS.items():
            match = pattern.search(text)
            fields[field_name] = self._field(
                normalize_whitespace(match.group(1)) if match else None,
                source=f"etiket:{field_name}" if match else None,
            )

        if fields["tarih"].value is None:
            match = self._DATE_PATTERN.search(text)
            fields["tarih"] = self._field(match.group(0) if match else None, "metin:tarih")

        email_match = self._EMAIL_PATTERN.search(text)
        fields["eposta"] = self._field(
            email_match.group(0) if email_match else None, "metin:eposta"
        )
        phone_match = self._PHONE_PATTERN.search(text)
        fields["telefon"] = self._field(
            phone_match.group(0) if phone_match else None, "metin:telefon"
        )

        request = self._find_request_sentence(text)
        fields["talep"] = self._field(request, "metin:talep" if request else None)
        if fields["konu"].value is None:
            fields["konu"] = self._field(
                self._infer_subject(text, classification.document_type), "metin:konu"
            )

        required = self.REQUIRED_FIELDS.get(
            classification.document_type, self.REQUIRED_FIELDS["genel_basvuru"]
        )
        missing = [name for name in required if not fields.get(name) or not fields[name].value]
        for name in missing:
            fields.setdefault(
                name,
                ExtractedField(value=None, status=FieldStatus.USER_REQUIRED),
            )

        keywords = list(dict.fromkeys(classification.matched_keywords + self._domain_keywords(text)))
        return DocumentAnalysis(
            document_type=classification.document_type,
            confidence=classification.confidence,
            summary=self._summarize(text),
            fields=fields,
            missing_fields=missing,
            keywords=keywords,
        )

    @staticmethod
    def _field(value: str | None, source: str | None) -> ExtractedField:
        return ExtractedField(
            value=value,
            status=FieldStatus.INFERRED if value else FieldStatus.USER_REQUIRED,
            source=source,
        )

    @staticmethod
    def _find_request_sentence(text: str) -> str | None:
        sentences = re.split(r"(?<=[.!?])\s+|\n+", text)
        markers = ("talep", "arz eder", "rica eder", "gereğini", "istiyorum", "bildiriyorum")
        for sentence in sentences:
            if any(marker in sentence.lower() for marker in markers):
                return truncate(sentence, 400)
        return None

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

    @staticmethod
    def _summarize(text: str) -> str:
        parts = [part.strip() for part in re.split(r"(?<=[.!?])\s+|\n+", text) if part.strip()]
        labeled = re.compile(
            r"^(?:adı\s*soyadı|gönderen|başvuran|tarih|konu|konum|adres|mevki|lokasyon|telefon|e-?posta)\s*[:\-]",
            re.I,
        )
        sentences = [part for part in parts if not labeled.match(part)] or parts
        return truncate(" ".join(sentences[:2]), 360)

    @staticmethod
    def _domain_keywords(text: str) -> list[str]:
        normalized = text.lower()
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
