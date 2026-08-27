"""Deterministic OCR-koordinat tabanlı boşluk/eksik alan adayı tespiti.

Bu, LLM2'nin (``LLMRequiredDataAgent``) "neyin nerede eksik olduğunu"
algılaması için kullandığı ham malzemeyi üretir. Tamamen sezgisel bir aday
üreticidir — yanlış pozitif üretmesi kabul edilebilir (LLM son kararı verir);
yanlış negatif ise sadece o alan için LLM2'nin salt metin tabanlı akıl
yürütmeye düşmesi anlamına gelir.
"""

from __future__ import annotations

from collections.abc import Sequence

from karayol_agent.documents.extractor import OcrWord
from karayol_agent.text_utils import normalize_for_search

from .llm_layer1 import LayoutGapCandidate

_FIELD_LABELS = frozenset(
    {
        "imza",
        # ``turkish_lower`` maps ASCII "I" to dotless "ı" (correct Turkish
        # case-folding), so a document typed/OCR'd with plain ASCII "Imza"
        # instead of the correct "İmza" normalizes to "ımza", not "imza" —
        # both spellings are accepted defensively.
        "ımza",
        "tarih",
        "kase",
        "muhur",
        "kimlik no",
        "tc kimlik no",
        "ad soyad",
        "unvan",
        "sayi",
    }
)

# Aynı koordinat uzayında (bkz. DocumentExtractor.extract_with_layout), etiket
# civarında "içerik var" kabul edilecek pencere genişliği/yüksekliği. Alt
# pencere kasıtlı olarak dar tutulur (~yarım satır boşluğu) — aksi halde bir
# sonraki paragrafın herhangi bir cümlesi yanlışlıkla "doldurulmuş" sayılır.
_LABEL_RIGHT_WINDOW = 400.0
_LABEL_BELOW_WINDOW = 8.0


class LayoutGapDetector:
    def detect(self, words: Sequence[OcrWord]) -> list[LayoutGapCandidate]:
        by_page: dict[int, list[OcrWord]] = {}
        for word in words:
            by_page.setdefault(word.page_number, []).append(word)

        candidates: list[LayoutGapCandidate] = []
        candidate_index = 0
        for page_number, page_words in sorted(by_page.items()):
            for word in page_words:
                label = normalize_for_search(word.text).rstrip(":：").strip()
                if label not in _FIELD_LABELS:
                    continue
                if self._has_nearby_content(word, page_words):
                    continue
                candidate_index += 1
                candidates.append(
                    LayoutGapCandidate(
                        candidate_id=f"layout-{page_number}-{candidate_index}",
                        nearby_label=word.text,
                        region_description=(
                            f"Sayfa {page_number}, '{word.text}' etiketinin "
                            "sağında/altında beklenen içerik bulunamadı."
                        ),
                    )
                )
        return candidates

    @staticmethod
    def _has_nearby_content(label_word: OcrWord, page_words: Sequence[OcrWord]) -> bool:
        for other in page_words:
            if other is label_word:
                continue
            same_line = (
                abs(other.top - label_word.top) <= label_word.height
                and label_word.left
                < other.left
                <= label_word.left + label_word.width + _LABEL_RIGHT_WINDOW
            )
            below = (
                label_word.top
                < other.top
                <= label_word.top + label_word.height + _LABEL_BELOW_WINDOW
                and abs(other.left - label_word.left) <= _LABEL_RIGHT_WINDOW
            )
            if same_line or below:
                return True
        return False


__all__ = ["LayoutGapDetector"]
