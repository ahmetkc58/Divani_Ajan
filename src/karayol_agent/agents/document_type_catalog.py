from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from karayol_agent.text_utils import normalize_for_search, tokenize


@dataclass(frozen=True, slots=True)
class DocumentTypeCandidate:
    candidate_id: str
    name: str
    document_type: str
    requested: bool
    score: float
    source: str = "DETSIS"

    def as_prompt_data(self) -> dict[str, object]:
        return {
            "candidate_id": self.candidate_id,
            "name": self.name,
            "document_type": self.document_type,
            "requested": self.requested,
            "score": self.score,
            "source": self.source,
        }


class DocumentTypeCatalog:
    """Small local lexical RAG channel over the repository's DETSIS catalog."""

    def __init__(self, paths: list[Path]) -> None:
        records: dict[tuple[str, bool], dict[str, object]] = {}
        for path in paths:
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                continue
            raw_records = payload.get("data", payload) if isinstance(payload, dict) else payload
            if not isinstance(raw_records, list):
                continue
            for record in raw_records:
                if not isinstance(record, dict):
                    continue
                raw_id = record.get("belgeBeyanID")
                name = record.get("belgeBeyanAdi")
                document_type = record.get("belgeTur")
                if raw_id is None or not isinstance(name, str) or not isinstance(document_type, str):
                    continue
                records[(str(raw_id), bool(record.get("istenenmi", False)))] = record
        self.records = tuple(records.values())

    def search(self, text: str, *, top_k: int = 12) -> list[DocumentTypeCandidate]:
        query_tokens = {token for token in tokenize(normalize_for_search(text)) if len(token) >= 3}
        candidates: list[DocumentTypeCandidate] = []
        for record in self.records:
            name = str(record["belgeBeyanAdi"])
            document_type = str(record["belgeTur"])
            candidate_tokens = set(
                tokenize(normalize_for_search(f"{name} {document_type}"))
            )
            overlap = query_tokens & candidate_tokens
            if not overlap:
                continue
            score = sum(2.0 if token in tokenize(normalize_for_search(document_type)) else 1.0 for token in overlap)
            candidates.append(
                DocumentTypeCandidate(
                    candidate_id=(
                        f"DETSIS-BELGE-{record['belgeBeyanID']}-"
                        + ("ISTENEN" if bool(record.get("istenenmi", False)) else "DUZENLENEN")
                    ),
                    name=name,
                    document_type=document_type,
                    requested=bool(record.get("istenenmi", False)),
                    score=round(score, 4),
                )
            )
        candidates.sort(key=lambda item: (-item.score, item.document_type, item.name))
        return candidates[:top_k]


__all__ = ["DocumentTypeCandidate", "DocumentTypeCatalog"]
