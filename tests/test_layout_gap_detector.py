from __future__ import annotations

from karayol_agent.agents.layout import LayoutGapDetector
from karayol_agent.documents.extractor import OcrWord


def _word(text: str, left: float, top: float, page_number: int = 1) -> OcrWord:
    return OcrWord(
        text=text,
        left=left,
        top=top,
        width=40.0,
        height=16.0,
        confidence=90.0,
        page_number=page_number,
    )


def test_detects_a_label_with_nothing_to_its_right_or_below() -> None:
    words = [
        _word("Gönderen:", left=72, top=72),
        _word("Ayşe", left=132, top=72),
        _word("İmza:", left=72, top=200),
    ]

    candidates = LayoutGapDetector().detect(words)

    assert len(candidates) == 1
    assert candidates[0].nearby_label == "İmza:"


def test_does_not_flag_a_label_with_a_value_on_the_same_line() -> None:
    words = [
        _word("Tarih:", left=72, top=72),
        _word("01.01.2026", left=132, top=72),
    ]

    candidates = LayoutGapDetector().detect(words)

    assert candidates == []


def test_does_not_flag_a_label_with_content_directly_below_it() -> None:
    words = [
        _word("İmza:", left=72, top=72),
        _word("AhmetYilmaz", left=72, top=90),
    ]

    candidates = LayoutGapDetector().detect(words)

    assert candidates == []


def test_ascii_i_variant_is_recognized_via_turkish_case_folding() -> None:
    # "Imza" (ASCII capital I, common in OCR/typed docs) case-folds to "ımza"
    # under this project's Turkish-aware lowering, not "imza".
    words = [_word("Imza:", left=72, top=72)]

    candidates = LayoutGapDetector().detect(words)

    assert len(candidates) == 1


def test_non_label_words_are_never_flagged() -> None:
    words = [_word("Merhaba", left=72, top=72)]

    assert LayoutGapDetector().detect(words) == []


def test_candidates_from_different_pages_get_distinct_ids() -> None:
    words = [
        _word("İmza:", left=72, top=72, page_number=1),
        _word("İmza:", left=72, top=72, page_number=2),
    ]

    candidates = LayoutGapDetector().detect(words)

    assert len(candidates) == 2
    assert len({candidate.candidate_id for candidate in candidates}) == 2
