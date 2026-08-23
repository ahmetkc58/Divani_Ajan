from __future__ import annotations

from karayol_agent.schemas import TextQualityReport


def assess_text_layer(page_texts: list[str]) -> TextQualityReport:
    page_count = len(page_texts)
    character_count = sum(len(text.strip()) for text in page_texts)
    average = character_count / page_count if page_count else 0.0
    readable_pages = sum(len(text.strip()) >= 80 for text in page_texts)
    ratio = readable_pages / page_count if page_count else 0.0
    reasons: list[str] = []
    if average < 200:
        reasons.append("Sayfa başına çıkarılan karakter sayısı çok düşük.")
    if ratio < 0.70:
        reasons.append("Okunabilir metin bulunan sayfa oranı yetersiz.")
    joined = " ".join(page_texts)
    if joined.count("�"):
        reasons.append("Metinde geçersiz/değiştirilmiş karakterler bulunuyor.")
    requires_ocr = bool(reasons)
    return TextQualityReport(
        character_count=character_count,
        page_count=page_count,
        average_characters_per_page=round(average, 2),
        readable_page_ratio=round(ratio, 3),
        quality="yetersiz" if requires_ocr else "uygun",
        requires_ocr=requires_ocr,
        reasons=reasons,
    )

