import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.config import get_settings


def _load_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as stream:
        return json.load(stream)


@lru_cache
def document_catalog() -> dict[str, Any]:
    return _load_json(get_settings().data_dir / "catalog" / "document_types.json")


@lru_cache
def municipality_catalog() -> dict[str, Any]:
    return _load_json(get_settings().data_dir / "catalog" / "municipal_units.json")


def document_type_map() -> dict[str, dict[str, Any]]:
    return {item["id"]: item for item in document_catalog()["document_types"]}


def unit_map() -> dict[str, dict[str, Any]]:
    return {item["id"]: item for item in municipality_catalog()["units"]}
