from __future__ import annotations

import pytest

from karayol_agent.agents import ContentAnalysisAgent
from karayol_agent.schemas import ClassificationResult, FieldStatus


def _classification(
    document_type: str = "yol_bakim_talebi",
    *,
    confidence: float = 0.73,
) -> ClassificationResult:
    return ClassificationResult(
        document_type=document_type,
        confidence=confidence,
        matched_keywords=["asfalt"],
    )


def test_ocr_label_glyphs_and_spaced_letters_are_normalized_conservatively() -> None:
    text = """G Ö N D E R E N : Ayşe Yılmaz
K0NU: Asfalt bozulması
K0NUM: D-100 12. kilometre
TARlH: 23.O8.2026

Yol yüzeyindeki çukurların onarılmasını talep ediyorum."""

    analysis = ContentAnalysisAgent().run(text, _classification())

    assert analysis.fields["gonderen"].value == "Ayşe Yılmaz"
    assert analysis.fields["konu"].value == "Asfalt bozulması"
    assert analysis.fields["konum"].value == "D-100 12. kilometre"
    assert analysis.fields["tarih"].value == "23.08.2026"
    assert analysis.fields["gonderen"].source == "etiket:gonderen:ocr-normalized"
    assert analysis.fields["konu"].source == "etiket:konu:ocr-normalized"
    assert analysis.confidence == 0.73


def test_gonderici_alias_is_recognized_for_person_and_institution() -> None:
    personal = ContentAnalysisAgent().run(
        "Gönderici: Ayşe Yılmaz\nKonu: Yol bakım\nTalep ediyorum.",
        _classification(),
    )
    institution = ContentAnalysisAgent().run(
        "GÖNDERlCl ADI: Karayolları Genel Müdürlüğü\n"
        "Konu: Yol bakım\nTalep ediyorum.",
        _classification(),
    )

    assert personal.fields["gonderen"].value == "Ayşe Yılmaz"
    assert personal.fields["gonderen"].source == "etiket:gonderen"
    assert institution.fields["gonderen"].value == (
        "Karayolları Genel Müdürlüğü"
    )
    assert institution.fields["gonderen"].source == (
        "etiket:gonderen:ocr-normalized"
    )


def test_label_only_lines_join_short_values_without_swallowing_body() -> None:
    text = """BAŞVURU SAHİBİ:
Ayşe
YILMAZ
KONU:
D-100 bağlantı yolundaki
asfalt bozulması
OLAY YERİ:
Ankara,
Çankaya ilçesi

Belirtilen kesimin onarılmasını talep ediyorum."""

    analysis = ContentAnalysisAgent().run(text, _classification())

    assert analysis.fields["gonderen"].value == "Ayşe YILMAZ"
    assert analysis.fields["konu"].value == (
        "D-100 bağlantı yolundaki asfalt bozulması"
    )
    assert analysis.fields["konum"].value == "Ankara, Çankaya ilçesi"
    assert analysis.fields["gonderen"].source == "etiket:gonderen:ocr-line-join"
    assert "Belirtilen" not in analysis.fields["konum"].value


def test_flattened_ocr_line_is_split_at_known_labels() -> None:
    text = (
        "Gönderen: Ahmet Yılmaz Konu: Bariyer hasarı "
        "Konum: O-4 18. kilometre Tarih: 24.08.2026\n"
        "Hasarlı bariyerin yenilenmesini talep ediyorum."
    )

    analysis = ContentAnalysisAgent().run(text, _classification())

    assert analysis.fields["gonderen"].value == "Ahmet Yılmaz"
    assert analysis.fields["konu"].value == "Bariyer hasarı"
    assert analysis.fields["konum"].value == "O-4 18. kilometre"
    assert analysis.fields["tarih"].value == "24.08.2026"


def test_exact_sender_label_wins_over_ocr_normalized_duplicate() -> None:
    text = """G0NDEREN: Gürültülü Aday
Gönderen: Ayşe Yılmaz
Konu: Yol bakım
Konum: Ankara
Yol bakımının yapılmasını talep ediyorum."""

    analysis = ContentAnalysisAgent().run(text, _classification())

    assert analysis.fields["gonderen"].value == "Ayşe Yılmaz"
    assert analysis.fields["gonderen"].source == "etiket:gonderen"


def test_sender_like_prose_and_request_sentence_are_not_sender_values() -> None:
    text = """Bu dosyayı gönderen kurum: Karayolları Genel Müdürlüğüdür.
GÖNDEREN yol bakım çalışmasının yapılmasını talep ediyorum
Konu: Asfalt bozulması
Konum: Ankara
Çukurların onarılmasını talep ediyorum."""

    analysis = ContentAnalysisAgent().run(text, _classification())

    assert analysis.fields["gonderen"].value is None
    assert analysis.fields["gonderen"].status == FieldStatus.USER_REQUIRED
    assert "gonderen" in analysis.missing_fields


def test_signature_block_provides_low_assumption_sender_fallback() -> None:
    text = """Konu: D-100 yolundaki çukur
Konum: Ankara
Çukurun giderilmesini arz ederim.

Ahmet
YILMAZ"""

    analysis = ContentAnalysisAgent().run(text, _classification())

    assert analysis.fields["gonderen"].value == "Ahmet YILMAZ"
    assert analysis.fields["gonderen"].source == "metin:imza-bloku"


@pytest.mark.parametrize(
    "heading",
    [
        "Ek Bilgiler",
        "Dağıtım Listesi",
        "İletişim Adresi",
        "Sonuç Bölümü",
        "Dağıtım Gereği",
        "Bilgi Notu",
        "Ek Listesi",
    ],
)
def test_signature_fallback_rejects_document_section_heading(heading: str) -> None:
    text = f"""Konu: D-100 yolundaki çukur
Konum: Ankara
Çukurun giderilmesini arz ederim.

{heading}
Belge sonu"""

    analysis = ContentAnalysisAgent().run(text, _classification())

    assert analysis.fields["gonderen"].value is None
    assert analysis.fields["gonderen"].status == FieldStatus.USER_REQUIRED


def test_signature_fallback_accepts_single_line_name_with_uppercase_surname() -> None:
    text = """Konu: D-100 yolundaki çukur
Konum: Ankara
Çukurun giderilmesini arz ederim.

Ahmet YILMAZ"""

    analysis = ContentAnalysisAgent().run(text, _classification())

    assert analysis.fields["gonderen"].value == "Ahmet YILMAZ"


def test_invalid_labeled_date_is_not_promoted_to_a_field() -> None:
    text = """Gönderen: Evrak Birimi
Konu: Üst yazı
Tarih: 99.99.2026
Bilgilerinize arz ederim."""

    analysis = ContentAnalysisAgent().run(text, _classification("ust_yazi"))

    assert analysis.fields["tarih"].value is None
    assert "tarih" in analysis.missing_fields


def test_retrieval_evidence_remains_bound_to_submitted_text() -> None:
    text = "G0NDEREN: Ayşe Yılmaz\nKonu: Yol bakımı\nTalep ediyorum."

    analysis = ContentAnalysisAgent().run(text, _classification())

    assert analysis.retrieval_evidence_text == (
        "G0NDEREN: Ayşe Yılmaz Konu: Yol bakımı Talep ediyorum."
    )
    assert "G0NDEREN" in analysis.retrieval_evidence_text
