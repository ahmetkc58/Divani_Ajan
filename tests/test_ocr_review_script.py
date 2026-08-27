from __future__ import annotations

import argparse
from pathlib import Path

import pytest

from scripts.ocr_review import (
    _assert_unique_document_ids,
    _candidate_output_path,
    _document_spec,
    _portable_path,
)


@pytest.mark.parametrize(
    "value",
    [
        "../escaped=file.pdf",
        "..\\escaped=file.pdf",
        "nested/name=file.pdf",
        "CON=file.pdf",
    ],
)
def test_document_spec_rejects_unsafe_output_identifiers(value: str) -> None:
    with pytest.raises(argparse.ArgumentTypeError):
        _document_spec(value)


def test_document_ids_are_unique_case_insensitively_on_windows() -> None:
    with pytest.raises(ValueError, match="yinelenen"):
        _assert_unique_document_ids(
            [("Guide", Path("a.pdf")), ("guide", Path("b.pdf"))]
        )


def test_candidate_output_path_stays_below_requested_directory(
    tmp_path: Path,
) -> None:
    output = _candidate_output_path(tmp_path, "official-writing-guide")

    assert output.parent == tmp_path.resolve()
    assert output.name == "official-writing-guide.ocr-candidate.txt"


def test_portable_path_is_relative_inside_root_and_name_only_outside(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "project"
    inside = project_root / "reports" / "result.json"
    outside = tmp_path / "external.pdf"

    assert _portable_path(inside, project_root) == "reports/result.json"
    assert _portable_path(outside, project_root) == "external.pdf"
