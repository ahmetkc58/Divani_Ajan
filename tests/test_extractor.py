from pathlib import Path

from karayol_agent.documents import DocumentExtractor


def test_text_extractor_preserves_labeled_lines(tmp_path: Path) -> None:
    source = tmp_path / "evrak.txt"
    source.write_text("Adı Soyadı: Ayşe Yılmaz\nKonu: Yol bakım\n\nTalep metni", encoding="utf-8")

    text = DocumentExtractor().extract(source)

    assert "Ayşe Yılmaz\nKonu:" in text
    assert "\n\nTalep" in text

