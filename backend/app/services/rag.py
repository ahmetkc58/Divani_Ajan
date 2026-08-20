import hashlib
import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pymupdf as fitz

from app.config import Settings
from app.services.catalog import municipality_catalog
from app.services.ocr import ocr_pdf_page, text_quality
from app.services.ollama import OllamaClient


@dataclass
class SearchResult:
    payload: dict[str, Any]
    score: float


SOURCE_SPECS = (
    ("resmi-yazisma-yonetmeligi", "Resmî Yazışmalar Yönetmeliği", "mevzuat-1.pdf", True),
    ("resmi-yazisma-kilavuzu", "Resmî Yazışmalar Kılavuzu", "mevzuat-kılavuz.pdf", True),
    (
        "ssdp-v4-2024",
        "Saklama Süreli Standart Dosya Planı V.4",
        "resources/official/ssdp_v4_2024.pdf",
        False,
    ),
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _article_hint(text: str) -> str | None:
    match = re.search(r"\bMADDE\s+(\d+[A-Z]?)", text, flags=re.IGNORECASE)
    if match:
        return f"Madde {match.group(1)}"
    example = re.search(r"\bÖRNEK\s+(\d+[A-Z]?)", text, flags=re.IGNORECASE)
    if example:
        return f"Örnek {example.group(1)}"
    heading = next(
        (
            line.strip()
            for line in text.splitlines()
            if 3 <= len(line.strip()) <= 100
            and line.strip() == line.strip().upper()
            and not re.search(r"\.{4,}|(.)\1{5,}", line.strip(), flags=re.IGNORECASE)
        ),
        None,
    )
    return heading


def _reference_quality(text: str, quality: float) -> bool:
    if quality < 0.62:
        return False
    if re.search(r"\.{5,}|([a-zçğıöşü])\1{5,}", text, flags=re.IGNORECASE):
        return False
    letters = sum(character.isalpha() for character in text)
    return letters / max(len(text), 1) >= 0.5


def _split_text(text: str, max_chars: int = 2400, overlap: int = 280) -> list[str]:
    normalized = re.sub(r"[ \t]+", " ", text)
    normalized = re.sub(r"\n{3,}", "\n\n", normalized).strip()
    if not normalized:
        return []
    chunks: list[str] = []
    start = 0
    while start < len(normalized):
        end = min(start + max_chars, len(normalized))
        if end < len(normalized):
            boundary = normalized.rfind("\n", start, end)
            if boundary > start + max_chars // 2:
                end = boundary
        chunks.append(normalized[start:end].strip())
        if end >= len(normalized):
            break
        start = max(end - overlap, start + 1)
    return [chunk for chunk in chunks if len(chunk) >= 80]


def prepare_corpus(settings: Settings, progress: Callable[[int, str], None] | None = None) -> list[dict[str, Any]]:
    chunks: list[dict[str, Any]] = []
    total_sources = len(SOURCE_SPECS)
    for source_index, (source_id, title, relative_path, force_ocr) in enumerate(SOURCE_SPECS):
        path = settings.project_root / relative_path
        if not path.exists():
            continue
        document = fitz.open(path)
        source_hash = _sha256(path)
        for page_index, page in enumerate(document):
            direct_text = page.get_text("text").strip()
            direct_quality = text_quality(direct_text)
            if force_ocr or direct_quality < 0.62:
                text = ocr_pdf_page(page)
                quality = text_quality(text)
                verification_method = "tesseract"
            else:
                text = direct_text
                quality = direct_quality
                verification_method = "direct_text"
            if quality < 0.45:
                continue
            for part_index, part in enumerate(_split_text(text)):
                chunks.append(
                    {
                        "id": f"{source_id}-p{page_index + 1}-c{part_index + 1}",
                        "source_id": source_id,
                        "title": title,
                        "source_path": relative_path,
                        "source_hash": source_hash,
                        "page": page_index + 1,
                        "article": _article_hint(part),
                        "text": part,
                        "verified": _reference_quality(part, quality),
                        "verification_method": verification_method,
                    }
                )
            if progress:
                source_ratio = (source_index + (page_index + 1) / document.page_count) / total_sources
                progress(int(source_ratio * 25), f"{title}: {page_index + 1}/{document.page_count} sayfa")
        document.close()
    return chunks


class RagIndex:
    def __init__(self, settings: Settings, ollama: OllamaClient):
        self.settings = settings
        self.ollama = ollama
        self.meta_path = settings.index_dir / "index_meta.json"
        self.chunks_path = settings.index_dir / "chunks.jsonl"
        self.vectors_path = settings.index_dir / "embeddings.npy"
        self.units_path = settings.index_dir / "unit_embeddings.npy"

    def status(self, embedding_model: str | None) -> tuple[bool, str | None]:
        required = (self.meta_path, self.chunks_path, self.vectors_path, self.units_path)
        if not all(path.exists() for path in required):
            return False, "Mevzuat indeksi henüz oluşturulmadı."
        try:
            meta = json.loads(self.meta_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return False, "İndeks metadata dosyası okunamıyor."
        if embedding_model and meta.get("embedding_model") != embedding_model:
            return False, "Embedding modeli değişti; indeks yeniden oluşturulmalı."
        return True, None

    def build(
        self,
        embedding_model: str,
        progress: Callable[[int, str], None] | None = None,
    ) -> dict[str, Any]:
        chunks = prepare_corpus(self.settings, progress)
        if not chunks:
            raise RuntimeError("Mevzuat kaynaklarından indekslenebilir metin çıkarılamadı.")

        vectors: list[list[float]] = []
        batch_size = 16
        for offset in range(0, len(chunks), batch_size):
            batch = chunks[offset : offset + batch_size]
            vectors.extend(self.ollama.embed(embedding_model, [item["text"] for item in batch]))
            if progress:
                ratio = (offset + len(batch)) / len(chunks)
                progress(25 + int(ratio * 60), f"Mevzuat embedding: {offset + len(batch)}/{len(chunks)}")

        units = municipality_catalog()["units"]
        unit_texts = [
            f"{unit['name']}. {unit['description']} Anahtarlar: {', '.join(unit['keywords'])}"
            for unit in units
        ]
        unit_vectors = self.ollama.embed(embedding_model, unit_texts)

        vector_array = _normalize(np.asarray(vectors, dtype=np.float32))
        unit_array = _normalize(np.asarray(unit_vectors, dtype=np.float32))
        np.save(self.vectors_path, vector_array)
        np.save(self.units_path, unit_array)
        with self.chunks_path.open("w", encoding="utf-8") as stream:
            for chunk in chunks:
                stream.write(json.dumps(chunk, ensure_ascii=False) + "\n")
        meta = {
            "schema_version": "1.0",
            "embedding_model": embedding_model,
            "dimension": int(vector_array.shape[1]),
            "chunk_count": len(chunks),
            "unit_count": len(units),
            "source_hashes": sorted({chunk["source_hash"] for chunk in chunks}),
        }
        self.meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
        if progress:
            progress(100, "Mevzuat ve birim indeksi hazır")
        return meta

    def retrieve(self, query: str, embedding_model: str, limit: int = 4) -> list[SearchResult]:
        ready, reason = self.status(embedding_model)
        if not ready:
            raise RuntimeError(reason or "RAG indeksi hazır değil.")
        query_vector = _normalize(np.asarray(self.ollama.embed(embedding_model, [query]), dtype=np.float32))[0]
        vectors = np.load(self.vectors_path)
        scores = vectors @ query_vector
        chunks = [json.loads(line) for line in self.chunks_path.read_text(encoding="utf-8").splitlines()]
        ranked = np.argsort(scores)[::-1]
        results: list[SearchResult] = []
        for index in ranked:
            chunk = chunks[int(index)]
            if not chunk.get("verified"):
                continue
            results.append(SearchResult(payload=chunk, score=float(scores[int(index)])))
            if len(results) >= limit:
                break
        return results

    def route(self, query: str, embedding_model: str, limit: int = 3) -> list[SearchResult]:
        ready, reason = self.status(embedding_model)
        if not ready:
            raise RuntimeError(reason or "Birim indeksi hazır değil.")
        query_vector = _normalize(np.asarray(self.ollama.embed(embedding_model, [query]), dtype=np.float32))[0]
        vectors = np.load(self.units_path)
        scores = vectors @ query_vector
        units = municipality_catalog()["units"]
        ranked = np.argsort(scores)[::-1][:limit]
        return [SearchResult(payload=units[int(index)], score=float(scores[int(index)])) for index in ranked]


def _normalize(vectors: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    norms[norms == 0] = 1
    return vectors / norms
