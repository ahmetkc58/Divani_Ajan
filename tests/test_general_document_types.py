from __future__ import annotations

import csv
from collections import Counter
from pathlib import Path

import pytest
from pypdf import PdfReader

from karayol_agent.agents.classifier import ClassificationAgent
from karayol_agent.document_types import GENERAL_DOCUMENT_TYPES


ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize(
    ("text", "expected_type"),
    [
        ("Dilekçemin incelenmesini arz ederim.", "dilekce"),
        ("Yaşanan rahatsızlık hakkında şikâyette bulunuyorum.", "sikayet"),
        ("Bildirilen işleme itiraz ediyor, yeniden incelenmesini istiyorum.", "itiraz"),
        ("Yol bakım çalışmasının yapılmasını talep ediyorum.", "talep"),
        ("Planlanan çalışma için gerekli iznin verilmesini istiyorum.", "izin"),
        ("Bilgi ve belge örneğinin tarafıma verilmesini istiyorum.", "belge"),
        ("Hasarlı trafik levhasını bildiriyorum.", "bildirim"),
        ("İlgi: 2026/1\nDağıtım: İlgili birimler\nGereğini rica ederim.", "ust_yazi"),
    ],
)
def test_classifier_exposes_broad_document_type(
    text: str,
    expected_type: str,
) -> None:
    result = ClassificationAgent().run(text)

    assert result.general_document_type == expected_type
    assert result.general_document_type in GENERAL_DOCUMENT_TYPES


def test_synthetic_document_manifest_is_balanced_and_general() -> None:
    manifest = ROOT / "data" / "synthetic_documents" / "manifest.csv"
    with manifest.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))

    counts = Counter(row["general_document_type"] for row in rows)
    assert len(rows) == 120
    assert counts == {
        "dilekce": 20,
        "sikayet": 20,
        "itiraz": 20,
        "talep": 20,
        "izin": 20,
        "belge": 20,
    }
    assert sum(row["scanned"] == "true" for row in rows) == 30


@pytest.mark.parametrize(
    "expected_type",
    ["dilekce", "sikayet", "itiraz", "talep", "izin", "belge"],
)
def test_text_pdf_requires_content_understanding_without_label_leakage(
    expected_type: str,
) -> None:
    path = (
        ROOT
        / "data"
        / "synthetic_documents"
        / "pdf"
        / f"{expected_type}_tam_01.pdf"
    )
    text = "\n".join(page.extract_text() or "" for page in PdfReader(path).pages)

    assert "TEST EVRAKI" not in text
    assert ClassificationAgent().run(text).general_document_type == expected_type


def test_scanned_pdf_has_no_hidden_text_label() -> None:
    path = (
        ROOT
        / "data"
        / "synthetic_documents"
        / "pdf"
        / "itiraz_eksik_02.pdf"
    )

    assert "".join(page.extract_text() or "" for page in PdfReader(path).pages) == ""
