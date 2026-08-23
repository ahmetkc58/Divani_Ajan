from karayol_agent.ingestion import LegalStructureChunker
from karayol_agent.ingestion.quality import assess_text_layer


def test_quality_report_flags_sparse_pdf_text() -> None:
    report = assess_text_layer(["MADDE 1- kısa", "", "MADDE 2-"])

    assert report.requires_ocr
    assert report.quality == "yetersiz"
    assert report.readable_page_ratio == 0


def test_legal_chunker_preserves_article_and_paragraph() -> None:
    text = (
        "BİRİNCİ BÖLÜM Amaç ve kapsam "
        "MADDE 1- (1) Bu sentetik kural yol bakım başvurularını düzenler. "
        "(2) Başvuruda konum belirtilir. "
        "MADDE 2- (1) Trafik güvenliği bildirimleri ayrı değerlendirilir."
    )

    chunks = LegalStructureChunker().chunk(
        text,
        title="Sentetik Yönetmelik",
        source="test",
        source_status="sentetik_demo_kurali",
    )

    assert len(chunks) == 3
    assert chunks[0].article == "Madde 1"
    assert chunks[0].paragraph == "1"
    assert chunks[1].paragraph == "2"
    assert chunks[2].article == "Madde 2"

