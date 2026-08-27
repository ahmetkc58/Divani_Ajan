import shutil
import subprocess
import time
from pathlib import Path

import pytest

from karayol_agent.documents import DocumentExtractor, ExtractionError
from karayol_agent.documents import extractor as extractor_module


def _make_blank_pdf(path: Path, *, page_count: int = 1) -> None:
    import pymupdf

    document = pymupdf.open()
    for _ in range(page_count):
        document.new_page()
    document.save(path)
    document.close()


def test_text_extractor_preserves_labeled_lines(tmp_path: Path) -> None:
    source = tmp_path / "evrak.txt"
    source.write_text("Adı Soyadı: Ayşe Yılmaz\nKonu: Yol bakım\n\nTalep metni", encoding="utf-8")

    text = DocumentExtractor().extract(source)

    assert "Ayşe Yılmaz\nKonu:" in text
    assert "\n\nTalep" in text


def test_text_extractor_rejects_oversized_text_instead_of_truncating(
    tmp_path: Path,
) -> None:
    source = tmp_path / "uzun.txt"
    source.write_text("Gönderen: Ayşe Yılmaz\n" + "x" * 80, encoding="utf-8")

    with pytest.raises(ExtractionError, match="sessiz kesme yapılmadı"):
        DocumentExtractor(max_chars=40).extract(source)


def test_text_extractor_repairs_only_safe_ocr_wrapped_words(tmp_path: Path) -> None:
    source = tmp_path / "ocr-evrak.txt"
    source.write_text(
        "\ufeffGönde-\nren:\u200b Ayşe Yılmaz\nD-100 bağlantı yolu\n\nTalep metni",
        encoding="utf-8",
    )

    text = DocumentExtractor().extract(source)

    assert text.startswith("Gönderen: Ayşe Yılmaz")
    assert "D-100 bağlantı yolu" in text
    assert "\n\nTalep metni" in text


def test_text_extractor_preserves_meaningful_cross_line_hyphen(tmp_path: Path) -> None:
    source = tmp_path / "konum-evrak.txt"
    source.write_text(
        "Gönderen: Ayşe Yılmaz\nKonum: Ankara-\nçevre yolu\nTalep metni",
        encoding="utf-8",
    )

    text = DocumentExtractor().extract(source)

    assert "Ankara-\nçevre yolu" in text


def test_mixed_pdf_pages_ocr_only_the_weak_page(
    monkeypatch, tmp_path: Path
) -> None:
    extractor = DocumentExtractor()
    path = tmp_path / "karma.pdf"
    page_texts = [
        "Konu: Yol bakım talebi. Bu sayfanın okunabilir bir metin katmanı var.",
        "",
    ]
    calls: list[set[int] | None] = []

    def fake_ocr_pages(
        _path: Path, *, page_numbers: set[int] | None
    ) -> dict[int, str]:
        calls.append(page_numbers)
        return {2: "Gönderen: Ayşe Yılmaz\nKonum: Ankara"}

    monkeypatch.setattr(extractor, "_ocr_pdf_pages", fake_ocr_pages)

    text = extractor._merge_pdf_page_texts(path, page_texts)

    assert calls == [{2}]
    assert page_texts[0] in text
    assert text.endswith("Gönderen: Ayşe Yılmaz\nKonum: Ankara")


def test_weak_page_with_empty_ocr_result_fails_closed(
    monkeypatch, tmp_path: Path
) -> None:
    extractor = DocumentExtractor()
    monkeypatch.setattr(
        extractor,
        "_ocr_pdf_pages",
        lambda _path, *, page_numbers: {2: ""},
    )

    with pytest.raises(ExtractionError, match="eksik sayfayla"):
        extractor._merge_pdf_page_texts(
            tmp_path / "karma.pdf",
            ["Konu: Okunabilir yol bakım başvurusu metni.", ""],
        )


def test_short_but_readable_text_page_does_not_require_ocr(
    monkeypatch, tmp_path: Path
) -> None:
    extractor = DocumentExtractor()

    def fail_ocr(*_args, **_kwargs):
        raise AssertionError("Okunabilir kısa metin sayfası OCR'a gönderilmemeli.")

    monkeypatch.setattr(extractor, "_ocr_pdf_pages", fail_ocr)

    text = extractor._merge_pdf_page_texts(
        tmp_path / "kisa.pdf", ["İmza\nAli Veli"]
    )

    assert text == "İmza\nAli Veli"


def test_short_watermark_text_layer_still_triggers_page_ocr(
    monkeypatch, tmp_path: Path
) -> None:
    extractor = DocumentExtractor()
    calls: list[set[int] | None] = []

    def fake_ocr_pages(
        _path: Path, *, page_numbers: set[int] | None
    ) -> dict[int, str]:
        calls.append(page_numbers)
        return {1: "Gönderen: Ayşe Yılmaz\nKonu: Yol bakım talebi"}

    monkeypatch.setattr(extractor, "_ocr_pdf_pages", fake_ocr_pages)

    text = extractor._merge_pdf_page_texts(tmp_path / "scan.pdf", ["Scan"])

    assert calls == [{1}]
    assert text.startswith("Gönderen: Ayşe Yılmaz")


def test_image_page_with_signature_like_watermark_still_triggers_ocr(
    monkeypatch, tmp_path: Path
) -> None:
    import pymupdf

    pdf_path = tmp_path / "watermark-scan.pdf"
    document = pymupdf.open()
    page = document.new_page()
    pixmap = pymupdf.Pixmap(
        pymupdf.csRGB,
        pymupdf.IRect(0, 0, 10, 10),
        False,
    )
    pixmap.clear_with(255)
    page.insert_image(page.rect, stream=pixmap.tobytes("png"))
    page.insert_text((72, 72), "Imza Adobe Scan")
    document.save(pdf_path)
    document.close()
    extractor = DocumentExtractor()
    calls: list[set[int] | None] = []

    def fake_ocr_pages(
        _path: Path, *, page_numbers: set[int] | None
    ) -> dict[int, str]:
        calls.append(page_numbers)
        return {1: "Gönderen: Ayşe Yılmaz\nKonu: Yol bakım talebi"}

    monkeypatch.setattr(extractor, "_ocr_pdf_pages", fake_ocr_pages)

    text = extractor._extract_pdf(pdf_path)

    assert calls == [{1}]
    assert text.startswith("Gönderen: Ayşe Yılmaz")


@pytest.mark.parametrize(
    "ocr_noise", ["aa", "OK", "...", "Imza Adobe Scan", "ADOBE SCAN"]
)
def test_partial_ocr_noise_fails_closed(
    monkeypatch, tmp_path: Path, ocr_noise: str
) -> None:
    extractor = DocumentExtractor()
    monkeypatch.setattr(
        extractor,
        "_ocr_pdf_pages",
        lambda _path, *, page_numbers: {1: ocr_noise},
    )

    with pytest.raises(ExtractionError, match="eksik sayfayla"):
        extractor._merge_pdf_page_texts(tmp_path / "scan.pdf", ["Scan"])


def test_short_scanned_signature_with_uppercase_surname_is_preserved(
    monkeypatch, tmp_path: Path
) -> None:
    extractor = DocumentExtractor()
    monkeypatch.setattr(
        extractor,
        "_ocr_pdf_pages",
        lambda _path, *, page_numbers: {2: "Ahmet\nYILMAZ"},
    )
    first_page = (
        "Konu: Yol bakım talebi. Konum: Ankara. "
        "Çukurun giderilmesini arz ederim."
    )

    text = extractor._merge_pdf_page_texts(
        tmp_path / "imza.pdf", [first_page, ""]
    )

    assert text.endswith("Ahmet\nYILMAZ")


def test_pdf_page_limit_is_enforced() -> None:
    extractor = DocumentExtractor(max_pdf_pages=2)

    with pytest.raises(ExtractionError, match="en fazla 2 sayfa"):
        extractor._validate_pdf_page_count(3)


def test_tesseract_timeout_is_sanitized(monkeypatch) -> None:
    extractor = DocumentExtractor()

    def timeout(*_args, **_kwargs):
        raise subprocess.TimeoutExpired(
            cmd=r"C:\Users\private\tesseract.exe",
            timeout=1,
            stderr=r"C:\Users\private\input.png",
        )

    monkeypatch.setattr(subprocess, "run", timeout)

    with pytest.raises(ExtractionError, match="süre sınırını") as captured:
        extractor._run_tesseract(
            ["tesseract", "input.png"],
            deadline=time.monotonic() + 10,
            page_number=1,
        )

    assert "Users" not in str(captured.value)


def test_tesseract_stderr_path_is_not_exposed(monkeypatch, tmp_path: Path) -> None:
    pdf_path = tmp_path / "ocr.pdf"
    _make_blank_pdf(pdf_path)
    monkeypatch.setattr("shutil.which", lambda _name: "tesseract")
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *_args, **_kwargs: subprocess.CompletedProcess(
            args=[],
            returncode=2,
            stdout="",
            stderr=r"fatal: C:\Users\private\input.png",
        ),
    )

    with pytest.raises(ExtractionError, match="çıkış kodu 2") as captured:
        DocumentExtractor()._ocr_pdf_pages(pdf_path, page_numbers={1})

    assert "Users" not in str(captured.value)


def test_ocr_per_page_pixel_limit_fails_closed(monkeypatch, tmp_path: Path) -> None:
    pdf_path = tmp_path / "buyuk-sayfa.pdf"
    _make_blank_pdf(pdf_path)
    monkeypatch.setattr("shutil.which", lambda _name: "tesseract")

    with pytest.raises(ExtractionError, match="sayfa 1 piksel sınırını"):
        DocumentExtractor(max_ocr_pixels_per_page=100)._ocr_pdf_pages(
            pdf_path, page_numbers={1}
        )


def test_ocr_total_pixel_limit_fails_closed(monkeypatch, tmp_path: Path) -> None:
    pdf_path = tmp_path / "toplam-piksel.pdf"
    _make_blank_pdf(pdf_path)
    monkeypatch.setattr("shutil.which", lambda _name: "tesseract")

    with pytest.raises(ExtractionError, match="toplam OCR piksel"):
        DocumentExtractor(
            max_ocr_pixels_per_page=20_000_000,
            max_ocr_total_pixels=100,
        )._ocr_pdf_pages(pdf_path, page_numbers={1})


def test_ocr_document_deadline_fails_closed() -> None:
    with pytest.raises(ExtractionError, match="toplam süre sınırını"):
        DocumentExtractor._remaining_timeout(time.monotonic() - 1, 1)


@pytest.mark.skipif(
    shutil.which("tesseract") is None,
    reason="Gerçek OCR entegrasyonu için Tesseract kurulu değil.",
)
def test_real_tesseract_scanned_pdf_extracts_sender_end_to_end(
    tmp_path: Path,
) -> None:
    import pymupdf

    from karayol_agent.agents import ClassificationAgent, ContentAnalysisAgent

    lines = [
        "GONDEREN: Ayse Yilmaz",
        "KONU: Asfalt bozulmasi",
        "KONUM: D-100 12. kilometre",
        "Yol bakim ve onarimi yapilmasini talep ediyorum.",
    ]
    source = pymupdf.open()
    source_page = source.new_page(width=900, height=550)
    for index, line in enumerate(lines):
        source_page.insert_text((50, 90 + index * 90), line, fontsize=30)
    image_bytes = source_page.get_pixmap(
        matrix=pymupdf.Matrix(2, 2)
    ).tobytes("png")
    source.close()

    pdf_path = tmp_path / "taranmis-gonderen.pdf"
    document = pymupdf.open()
    page = document.new_page(width=900, height=550)
    page.insert_image(page.rect, stream=image_bytes)
    document.save(pdf_path)
    document.close()

    text = DocumentExtractor().extract(pdf_path)
    classification = ClassificationAgent().run(text)
    analysis = ContentAnalysisAgent().run(text, classification)

    assert analysis.fields["gonderen"].value is not None
    assert "ayse" in analysis.fields["gonderen"].value.casefold()
    assert "yilmaz" in analysis.fields["gonderen"].value.casefold()


def test_text_extractor_does_not_join_uppercase_layout_lines(tmp_path: Path) -> None:
    source = tmp_path / "resmi-evrak.txt"
    source.write_text("T.C.-\nKGM\nKonu: Yol bakım", encoding="utf-8")

    text = DocumentExtractor().extract(source)

    assert text.startswith("T.C.-\nKGM")


@pytest.mark.parametrize("suffix", [".pdf", ".png", ".jpg", ".tiff"])
def test_binary_extension_with_wrong_magic_bytes_is_rejected(
    tmp_path: Path, suffix: str
) -> None:
    source = tmp_path / f"sahte{suffix}"
    source.write_bytes(b"not-the-declared-format")

    with pytest.raises(ExtractionError, match="magic-byte"):
        DocumentExtractor().extract(source)


def test_direct_png_is_ocrd_with_pixel_limits(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import pymupdf

    document = pymupdf.open()
    page = document.new_page(width=500, height=300)
    page.insert_text((40, 80), "GONDEREN: Ayse Yilmaz", fontsize=18)
    pixmap = page.get_pixmap(alpha=False)
    image_path = tmp_path / "basvuru.png"
    pixmap.save(image_path)
    document.close()
    monkeypatch.setattr("shutil.which", lambda _name: "tesseract")
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *_args, **_kwargs: subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout=(
                "GONDEREN: Ayse Yilmaz\nKONU: Asfalt bozulmasi\n"
                "Yol bakim yapilmasini talep ediyorum."
            ),
            stderr="",
        ),
    )

    text = DocumentExtractor(max_ocr_pixels_per_page=1_000_000).extract(image_path)

    assert "Ayse Yilmaz" in text


def test_resolve_tesseract_falls_back_when_path_binary_is_too_old(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    old_binary = tmp_path / "old" / "tesseract.exe"
    old_binary.parent.mkdir()
    old_binary.write_bytes(b"")
    good_binary = tmp_path / "good" / "tesseract.exe"
    good_binary.parent.mkdir()
    good_binary.write_bytes(b"")

    def fake_run(command, **_kwargs):
        binary = command[0]
        if binary == str(old_binary):
            stdout = "tesseract 3.02\n leptonica-1.68\n"
        elif binary == str(good_binary):
            stdout = "tesseract 5.3.3\n leptonica-1.83.1\n"
        else:
            raise AssertionError(f"unexpected binary probed: {binary}")
        return subprocess.CompletedProcess(
            args=command, returncode=0, stdout=stdout, stderr=""
        )

    monkeypatch.setattr(shutil, "which", lambda _name: str(old_binary))
    monkeypatch.setattr(
        extractor_module, "_KNOWN_TESSERACT_PATHS", (old_binary, good_binary)
    )
    monkeypatch.setattr(subprocess, "run", fake_run)

    resolved = extractor_module._resolve_tesseract()

    assert resolved == str(good_binary)


def test_resolve_tesseract_falls_back_to_which_result_when_nothing_qualifies(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(shutil, "which", lambda _name: "tesseract")
    monkeypatch.setattr(extractor_module, "_KNOWN_TESSERACT_PATHS", ())
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *_args, **_kwargs: subprocess.CompletedProcess(
            args=[], returncode=0, stdout="not a version string", stderr=""
        ),
    )

    assert extractor_module._resolve_tesseract() == "tesseract"


def test_resolve_tesseract_returns_none_when_nothing_is_found(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(shutil, "which", lambda _name: None)
    monkeypatch.setattr(extractor_module, "_KNOWN_TESSERACT_PATHS", ())

    assert extractor_module._resolve_tesseract() is None


def test_parse_tesseract_tsv_extracts_only_word_level_rows() -> None:
    tsv = (
        "level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\t"
        "width\theight\tconf\ttext\n"
        "1\t1\t0\t0\t0\t0\t0\t0\t100\t100\t-1\t\n"
        "5\t1\t1\t1\t1\t1\t10\t20\t30\t15\t92.5\tGönderen:\n"
        "5\t1\t1\t1\t1\t2\t45\t20\t20\t15\t88.1\tAyşe\n"
    )

    words = DocumentExtractor._parse_tesseract_tsv(tsv, page_number=1)

    assert [word.text for word in words] == ["Gönderen:", "Ayşe"]
    assert words[0].left == 10.0
    assert words[0].top == 20.0
    assert words[0].confidence == 92.5
    assert all(word.page_number == 1 for word in words)


def test_parse_tesseract_tsv_returns_empty_for_malformed_header() -> None:
    assert DocumentExtractor._parse_tesseract_tsv("not\ta\ttsv\theader", 1) == []
    assert DocumentExtractor._parse_tesseract_tsv("", 1) == []


def test_extract_with_layout_captures_native_pdf_word_positions(
    tmp_path: Path,
) -> None:
    import pymupdf

    document = pymupdf.open()
    page = document.new_page()
    page.insert_text((72, 72), "Gonderen: Test Kisi", fontsize=12)
    page.insert_text((72, 100), "Konu: Yol bakim talebi hakkinda", fontsize=12)
    pdf_path = tmp_path / "native.pdf"
    document.save(pdf_path)
    document.close()

    result = DocumentExtractor().extract_with_layout(pdf_path)

    assert "Gonderen" in result.text
    assert any(word.text == "Gonderen:" for word in result.words)
    assert all(word.page_number == 1 for word in result.words)


def test_extract_with_layout_returns_no_words_for_plain_text(tmp_path: Path) -> None:
    source = tmp_path / "evrak.txt"
    source.write_text("Konu: Yol bakım", encoding="utf-8")

    result = DocumentExtractor().extract_with_layout(source)

    assert result.text
    assert result.words == ()


def test_extract_with_layout_never_fails_when_word_capture_errors(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    source = tmp_path / "evrak.txt"
    source.write_text("Konu: Yol bakım", encoding="utf-8")
    extractor = DocumentExtractor()
    monkeypatch.setattr(
        extractor,
        "_extract_words",
        lambda _path: (_ for _ in ()).throw(RuntimeError("boom")),
    )

    result = extractor.extract_with_layout(source)

    assert result.text
    assert result.words == ()
