from __future__ import annotations

import re
import unicodedata

from karayol_agent.text_utils import normalize_whitespace, turkish_lower


_INVISIBLE_FORMATTING = str.maketrans(
    {
        "\u00ad": None,  # soft hyphen
        "\u200b": None,  # zero-width space
        "\u200c": None,
        "\u200d": None,
        "\u2060": None,  # word joiner
        "\ufeff": None,  # byte-order mark inside OCR output
        "\u202a": None,
        "\u202b": None,
        "\u202c": None,
        "\u202d": None,
        "\u202e": None,
    }
)
_LOWERCASE_LETTER = re.compile(r"^[a-zçğıöşü]")
_WORD_BEFORE_HYPHEN = re.compile(r"([A-Za-zÇĞİÖŞÜçğıöşü]+)-$")
_WORD_AT_LINE_START = re.compile(r"^([A-Za-zÇĞİÖŞÜçğıöşü]+)")
_SAFE_WRAPPED_WORDS = {
    "başvuran",
    "başvuru",
    "basvuran",
    "basvuru",
    "düzenleme",
    "duzenleme",
    "gönderen",
    "gönderenin",
    "gönderici",
    "gonderen",
    "gonderenin",
    "gonderici",
    "lokasyon",
    "müracaatçı",
    "muracaatci",
}


def normalize_document_text(text: str) -> str:
    """Normalize OCR/text-layer noise without changing semantic characters.

    Line boundaries are evidence for labelled-field extraction, so they are
    retained.  The only cross-line repair is a conservative de-hyphenation of
    known form-label words. Numeric road identifiers such as ``D-100`` and
    meaningful expressions such as ``Ankara-\nçevre yolu`` remain untouched.
    """

    normalized = unicodedata.normalize("NFKC", text)
    normalized = normalized.translate(_INVISIBLE_FORMATTING)
    normalized = (
        normalized.replace("\r\n", "\n")
        .replace("\r", "\n")
        .replace("\f", "\n\n")
        .replace("\v", "\n")
    )
    lines = [normalize_whitespace(line) for line in normalized.split("\n")]
    lines = _join_wrapped_words(lines)

    cleaned: list[str] = []
    previous_blank = False
    for line in lines:
        if not line:
            if cleaned and not previous_blank:
                cleaned.append("")
            previous_blank = True
            continue
        cleaned.append(line)
        previous_blank = False
    return "\n".join(cleaned).strip()


def _join_wrapped_words(lines: list[str]) -> list[str]:
    joined: list[str] = []
    index = 0
    while index < len(lines):
        current = lines[index]
        while _is_safe_wrapped_label(current, lines, index):
            current = current[:-1] + lines[index + 1]
            index += 1
        joined.append(current)
        index += 1
    return joined


def _is_safe_wrapped_label(current: str, lines: list[str], index: int) -> bool:
    if not current or index + 1 >= len(lines) or not lines[index + 1]:
        return False
    next_line = lines[index + 1]
    if not _LOWERCASE_LETTER.match(next_line):
        return False
    before = _WORD_BEFORE_HYPHEN.search(current)
    after = _WORD_AT_LINE_START.match(next_line)
    if before is None or after is None:
        return False
    repaired_word = turkish_lower(before.group(1) + after.group(1))
    return repaired_word in _SAFE_WRAPPED_WORDS


__all__ = ["normalize_document_text"]
