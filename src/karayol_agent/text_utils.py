from __future__ import annotations

import re
import unicodedata


_WHITESPACE_RE = re.compile(r"\s+")
_TOKEN_RE = re.compile(r"[0-9a-zçğıöşü]+", re.IGNORECASE)


def normalize_whitespace(value: str) -> str:
    return _WHITESPACE_RE.sub(" ", value).strip()


def turkish_lower(value: str) -> str:
    return value.translate(str.maketrans({"I": "ı", "İ": "i"})).lower()


def normalize_for_search(value: str) -> str:
    value = unicodedata.normalize("NFKC", value)
    return normalize_whitespace(turkish_lower(value))


def tokenize(value: str) -> list[str]:
    return _TOKEN_RE.findall(normalize_for_search(value))


def truncate(value: str, limit: int = 240) -> str:
    value = normalize_whitespace(value)
    if len(value) <= limit:
        return value
    return value[: limit - 1].rstrip() + "…"

