from pathlib import Path
from types import SimpleNamespace

from app.schemas import DraftCore, DraftV1
from app.services.drafting import (
    _fallback_draft_core,
    create_draft,
    has_blocking_errors,
    validate_draft,
)
from app.services.exports import _turkish_upper, export_docx, export_pdf


def draft() -> DraftV1:
    return DraftV1(
        id="draft-1",
        analysis_id="analysis-1",
        document_id="document-1",
        recipient_unit_id="BRM-FEN",
        recipient_unit_name="Fen İşleri Müdürlüğü",
        letter_type="cevap_yazisi",
        date="20.08.2026",
        subject="Yol bakım talebi hakkında",
        body="Başvurunuz incelenmiş olup ilgili alanda teknik inceleme yapılması planlanmıştır.",
        references=[],
        attachments=[],
        distribution=[],
        validations=[],
        model_name="fake-model",
        created_at="2026-08-20T10:00:00+00:00",
        updated_at="2026-08-20T10:00:00+00:00",
    )


def test_valid_draft_has_no_blocking_error() -> None:
    value = draft()
    value.validations = validate_draft(value)
    assert not has_blocking_errors(value)


def test_short_body_blocks_approval() -> None:
    value = draft()
    value.body = "Kısa."
    value.validations = validate_draft(value)
    assert has_blocking_errors(value)


def test_docx_and_pdf_exports(tmp_path: Path) -> None:
    value = draft()
    docx_path = export_docx(value, tmp_path / "taslak.docx")
    pdf_path = export_pdf(value, tmp_path / "taslak.pdf")
    assert docx_path.stat().st_size > 1_000
    assert pdf_path.read_bytes().startswith(b"%PDF-")


def test_turkish_uppercase_is_used_for_official_headers() -> None:
    assert _turkish_upper("Örnekşehir Belediyesi") == "ÖRNEKŞEHİR BELEDİYESİ"
    assert _turkish_upper("Sosyal Yardım İşleri") == "SOSYAL YARDIM İŞLERİ"


def test_deterministic_fallback_requests_missing_information() -> None:
    analysis = SimpleNamespace(
        topic="Gıda Yardımı",
        summary="Başvuru gıda yardımı talebi içeriyor.",
        missing_fields=["iletisim"],
        regulations=[],
        routing=SimpleNamespace(
            alternatives=[SimpleNamespace(unit_name="Sosyal Yardım İşleri Müdürlüğü")]
        ),
    )

    core = _fallback_draft_core(analysis)  # type: ignore[arg-type]

    assert core.letter_type == "eksik_bilgi_talebi"
    assert "iletisim" in core.body


def test_draft_postprocessing_corrects_false_missing_information_claim() -> None:
    analysis = SimpleNamespace(
        id="analysis-1",
        document_id="document-1",
        document_type=SimpleNamespace(label="dilekce"),
        topic="Gıda Yardımı",
        summary="Başvuru gıda yardımı talebi içeriyor.",
        extracted_fields=[],
        missing_fields=[],
        regulations=[],
        routing=SimpleNamespace(
            alternatives=[SimpleNamespace(unit_name="Sosyal Yardım İşleri Müdürlüğü")]
        ),
    )

    class MisleadingOllama:
        def chat_structured(self, *args, **kwargs):  # noqa: ANN002, ANN003
            return DraftCore(
                letter_type="eksik_bilgi_talebi",
                subject="Gıda Yardımı",
                body=analysis.summary,
            )

    result = create_draft(
        analysis=analysis,  # type: ignore[arg-type]
        selected_unit_id="BRM-SOSYAL",
        chat_model="fake-model",
        ollama=MisleadingOllama(),  # type: ignore[arg-type]
    )

    assert result.letter_type == "cevap_yazisi"
    assert "değerlendirmeye alınacak" in result.body
