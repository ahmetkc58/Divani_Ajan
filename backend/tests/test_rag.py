from app.services.rag import _article_hint, _reference_quality


def test_reference_quality_rejects_corrupt_table_of_contents() -> None:
    corrupt = "Belgenin Alınması .....................eeeeeee İİ 28.1 Elektronik Ortam"
    assert not _reference_quality(corrupt, 0.95)


def test_article_hint_prefers_numbered_legal_markers() -> None:
    assert _article_hint("MADDE 32- Belgenin doğrulanması") == "Madde 32"
    assert _article_hint("ÖRNEK 7\nİLGİ ÖRNEĞİ") == "Örnek 7"
