#!/usr/bin/env python3
"""Kaggle GPU pipeline: UAB snapshot -> legal hierarchy -> Jina v3 -> Qdrant.

Kaggle usage (GPU accelerator must be enabled):

    # The configured Kaggle input/output paths work without arguments:
    !python kaggle_legal_rag_v2.py

The source snapshot already contains PDF text-layer and OCR-selected text. This
script deliberately does not read PDFs and does not install/replace PyTorch.
It creates deterministic parent/leaf artifacts, candidate legal-reference
edges, a contextual dense+BM25 Qdrant collection, and a downloadable ZIP.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import math
import re
import shutil
import subprocess
import sys
import time
import uuid
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Any, Iterable, Iterator, Sequence


PIPELINE_VERSION = "2.0.0"
DEFAULT_INPUT = Path(
    "/kaggle/input/datasets/matrimaldous/sssssssssssssss/"
    "uab_ministry_archive_snapshot.json"
)
DEFAULT_OUTPUT = Path("/kaggle/working/uab_legal_rag_v2")
DEFAULT_MODEL = "jinaai/jina-embeddings-v3"
DEFAULT_MODEL_REVISION = "ab036b023d30b4d1138c4c3bfa9f0c445ab455d6"
DEFAULT_CODE_REVISION = "bd55a5ec8e6c0fb1d6c26efb4b6a4a74ce8a88d3"
DEFAULT_COLLECTION = "uab_legal_leaf_v2"
VECTOR_DIMENSION = 1024
PAGE_SEPARATOR = "\n\n"
TOKEN_RE = re.compile(r"\d+[A-Za-zÇĞİÖŞÜçğıöşü]*|[A-Za-zÇĞİÖŞÜçğıöşü]+", re.UNICODE)
ARTICLE_RE = re.compile(
    r"(?i)(?<!\w)(?P<label>(?:(?:GEÇİCİ|EK)\s+)?MADDE\s+"
    r"(?P<number>\d+[A-ZÇĞİÖŞÜ]?))\s*[-–—:]?"
)
# Turkish legislation paragraphs are line-level markers such as ``(1)``.
# Restricting them to line starts and 1-99 prevents years/codes like ``(2008)``
# inside a sentence from being misclassified as paragraph boundaries.
PARAGRAPH_RE = re.compile(
    r"(?m)(?:^|[\r\n])\s*\((?P<number>[1-9]\d?)\)\s*"
)
CLAUSE_RE = re.compile(
    r"(?<!\w)(?:\((?P<paren>[a-zçğıöşü])\)|(?P<plain>[a-zçğıöşü])\))\s*",
    re.I,
)
SECTION_RE = re.compile(
    r"(?i)(?P<label>(?:BİRİNCİ|İKİNCİ|ÜÇÜNCÜ|DÖRDÜNCÜ|BEŞİNCİ|ALTINCI|"
    r"YEDİNCİ|SEKİZİNCİ|DOKUZUNCU|ONUNCU|\d+\.?)[ ]+BÖLÜM)"
    r"(?:\s*[-–—:]?\s*(?P<title>[^\n]{0,180}))?"
)
EXPLICIT_REFERENCE_RE = re.compile(
    r"(?i)(?P<law_no>\d{3,6})\s+sayılı\s+"
    r"(?P<law_name>[A-ZÇĞİÖŞÜa-zçğıöşü0-9 .,'’\-]{2,100}?)\s+"
    r"(?:Kanun|Yönetmelik|Tüzük)[A-ZÇĞİÖŞÜa-zçğıöşü'’]*\s+"
    r"(?P<article>\d+[A-ZÇĞİÖŞÜ]?)\s*(?:inci|ıncı|uncu|üncü)?\s+"
    r"maddesi"
)
SAME_DOCUMENT_REFERENCE_RE = re.compile(
    r"(?i)(?<!sayılı\s)(?P<article>\d+[A-ZÇĞİÖŞÜ]?)\s*"
    r"(?:inci|ıncı|uncu|üncü)?\s+madde(?:si|sinin|ye|ye göre|de)?"
)


def normalize(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def stable_hash(*parts: object, length: int = 20) -> str:
    raw = "|".join("" if part is None else str(part) for part in parts)
    return sha256(raw.encode("utf-8")).hexdigest()[:length]


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def atomic_write_json(path: Path, value: object) -> None:
    """Replace a JSON checkpoint only after the complete file is durable."""

    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    temporary.replace(path)


def write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")))
            handle.write("\n")


def install_dependencies() -> None:
    """Install only missing RAG dependencies; never replace Kaggle PyTorch."""

    subprocess.run(
        [
            sys.executable,
            "-m",
            "pip",
            "install",
            "-q",
            "qdrant-client>=1.12,<2",
            "transformers>=4.48,<5",
            "sentence-transformers>=5.4,<6",
            "einops>=0.7,<1",
            "accelerate>=1,<2",
        ],
        check=True,
    )


@dataclass(frozen=True)
class SourceDocument:
    document_id: str
    title: str
    source: str
    source_url: str | None
    source_sha256: str | None
    document_type: str
    domain: str
    subdomain: str
    ocr_status: str
    pages: tuple[tuple[int, str], ...]


def load_documents(input_path: Path, limit: int | None) -> tuple[dict[str, Any], list[SourceDocument]]:
    envelope = json.loads(input_path.read_text(encoding="utf-8"))
    if envelope.get("document_count") != 501 and limit is None:
        raise ValueError(
            "Tam UAB snapshot'ı bekleniyordu: document_count=501 değil. "
            "Pilot için --limit kullanın."
        )
    rows = envelope.get("data")
    if not isinstance(rows, list) or not rows:
        raise ValueError("Snapshot data[] metin parçalarını içermiyor.")

    by_document: dict[str, list[dict[str, Any]]] = defaultdict(list)
    document_order: list[str] = []
    for row in rows:
        document_id = str(row.get("document_id") or "").strip()
        if not document_id:
            raise ValueError("document_id eksik snapshot satırı bulundu.")
        if document_id not in by_document:
            document_order.append(document_id)
        by_document[document_id].append(row)
    if limit is not None:
        document_order = document_order[:limit]

    documents: list[SourceDocument] = []
    for document_id in document_order:
        records = by_document[document_id]
        records.sort(key=lambda item: (int(item.get("page") or 0), str(item.get("chunk_id") or "")))
        first = records[0]
        page_parts: dict[int, list[str]] = defaultdict(list)
        for record in records:
            text = str(record.get("text") or "").strip()
            if text:
                page_parts[int(record.get("page") or 1)].append(text)
        pages = tuple(
            (page, PAGE_SEPARATOR.join(parts))
            for page, parts in sorted(page_parts.items())
            if parts
        )
        if not pages:
            raise ValueError(f"{document_id}: kullanılabilir metin yok.")
        documents.append(
            SourceDocument(
                document_id=document_id,
                title=str(first.get("title") or document_id),
                source=str(first.get("source") or ""),
                source_url=first.get("source_url"),
                source_sha256=first.get("source_sha256"),
                document_type=str(first.get("document_type") or "unknown"),
                domain=str(first.get("domain") or "unknown"),
                subdomain=str(first.get("subdomain") or "unknown"),
                ocr_status=str(first.get("ocr_status") or "not_inspected"),
                pages=pages,
            )
        )
    return envelope, documents


def combine_pages(document: SourceDocument) -> tuple[str, list[tuple[int, int, int]]]:
    parts: list[str] = []
    spans: list[tuple[int, int, int]] = []
    cursor = 0
    for page, text in document.pages:
        if parts:
            parts.append(PAGE_SEPARATOR)
            cursor += len(PAGE_SEPARATOR)
        start = cursor
        parts.append(text)
        cursor += len(text)
        spans.append((start, cursor, page))
    return "".join(parts), spans


def page_for_offset(spans: Sequence[tuple[int, int, int]], offset: int) -> int:
    for start, end, page in spans:
        if start <= offset < end:
            return page
    return spans[-1][2]


def section_for(matches: Sequence[re.Match[str]], article_offset: int) -> str | None:
    prior = [match for match in matches if match.start() < article_offset]
    if not prior:
        return None
    match = prior[-1]
    label = normalize(match.group("label"))
    title = normalize(match.group("title") or "")
    title = re.split(r"(?i)\b(?:GEÇİCİ|EK)?\s*MADDE\b", title, maxsplit=1)[0].strip(" -–—:")
    return f"{label} - {title}" if title else label


def bounded_parts(text: str, max_chars: int) -> list[str]:
    value = normalize(text)
    if not value:
        return []
    if len(value) <= max_chars:
        return [value]
    sentences = [normalize(item) for item in re.split(r"(?<=[.!?;])\s+", value) if normalize(item)]
    result: list[str] = []
    current = ""
    for sentence in sentences:
        if len(sentence) > max_chars:
            if current:
                result.append(current)
                current = ""
            words = sentence.split()
            hard = ""
            for word in words:
                candidate = f"{hard} {word}".strip()
                if hard and len(candidate) > max_chars:
                    result.append(hard)
                    hard = word
                else:
                    hard = candidate
            if hard:
                result.append(hard)
            continue
        candidate = f"{current} {sentence}".strip()
        if current and len(candidate) > max_chars:
            result.append(current)
            current = sentence
        else:
            current = candidate
    if current:
        result.append(current)
    return result


def leaf_record(
    document: SourceDocument,
    *,
    parent_id: str,
    parent_text: str,
    section: str | None,
    article: str | None,
    paragraph: str | None,
    clause: str | None,
    level: str,
    text: str,
    page: int,
    page_end: int,
    source_offset: int,
    part_index: int,
) -> dict[str, Any]:
    leaf_id = "leaf-" + stable_hash(
        document.document_id,
        parent_id,
        paragraph,
        clause,
        source_offset,
        part_index,
        text,
    )
    hierarchy = [document.title]
    if section:
        hierarchy.append(section)
    if article:
        hierarchy.append(article)
    if paragraph:
        hierarchy.append(f"Fıkra {paragraph}")
    if clause:
        hierarchy.append(f"Bent {clause}")
    context = " > ".join(hierarchy)
    return {
        "leaf_id": leaf_id,
        "parent_id": parent_id,
        "document_id": document.document_id,
        "title": document.title,
        "section": section,
        "article": article,
        "paragraph": paragraph,
        "clause": clause,
        "level": level,
        "text": normalize(text),
        "context_text": context,
        "embedding_text": f"{context}\n{normalize(text)}",
        "parent_text_sha256": sha256(parent_text.encode("utf-8")).hexdigest(),
        "source": document.source,
        "source_url": document.source_url,
        "source_sha256": document.source_sha256,
        "page": page,
        "page_end": page_end,
        "source_offset": source_offset,
        "document_type": document.document_type,
        "domain": document.domain,
        "subdomain": document.subdomain,
        "ocr_status": document.ocr_status,
        "validity_status": "needs_verification",
        "legal_reliance_allowed": False,
    }


def split_article_leaves(
    document: SourceDocument,
    *,
    parent_id: str,
    parent_text: str,
    body: str,
    body_offset: int,
    section: str | None,
    article: str,
    spans: Sequence[tuple[int, int, int]],
    max_chars: int,
) -> list[dict[str, Any]]:
    paragraph_matches = list(PARAGRAPH_RE.finditer(body))
    units: list[tuple[str | None, int, int, str]] = []
    if not paragraph_matches:
        units.append((None, 0, len(body), body))
    else:
        preamble = body[: paragraph_matches[0].start()]
        if normalize(preamble):
            units.append((None, 0, paragraph_matches[0].start(), preamble))
        for index, match in enumerate(paragraph_matches):
            start = match.start()
            end = paragraph_matches[index + 1].start() if index + 1 < len(paragraph_matches) else len(body)
            units.append((match.group("number"), start, end, body[start:end]))

    leaves: list[dict[str, Any]] = []
    for paragraph, unit_start, unit_end, unit_text in units:
        clause_matches = list(CLAUSE_RE.finditer(unit_text))
        leaf_units: list[tuple[str | None, int, int, str, str]] = []
        if not clause_matches:
            leaf_units.append((None, 0, len(unit_text), unit_text, "paragraph" if paragraph else "article"))
        else:
            prefix = unit_text[: clause_matches[0].start()]
            if normalize(prefix):
                leaf_units.append((None, 0, clause_matches[0].start(), prefix, "paragraph_preamble"))
            for index, match in enumerate(clause_matches):
                start = match.start()
                end = clause_matches[index + 1].start() if index + 1 < len(clause_matches) else len(unit_text)
                clause = (match.group("paren") or match.group("plain") or "").lower()
                leaf_units.append((clause, start, end, unit_text[start:end], "clause"))

        for clause, local_start, local_end, leaf_text, level in leaf_units:
            absolute_start = body_offset + unit_start + local_start
            absolute_end = body_offset + unit_start + local_end
            for part_index, part in enumerate(bounded_parts(leaf_text, max_chars), start=1):
                leaves.append(
                    leaf_record(
                        document,
                        parent_id=parent_id,
                        parent_text=parent_text,
                        section=section,
                        article=article,
                        paragraph=paragraph,
                        clause=clause,
                        level=level,
                        text=part,
                        page=page_for_offset(spans, absolute_start),
                        page_end=page_for_offset(spans, max(absolute_start, absolute_end - 1)),
                        source_offset=absolute_start,
                        part_index=part_index,
                    )
                )
    return leaves


def chunk_document(document: SourceDocument, max_chars: int) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    text, spans = combine_pages(document)
    articles = list(ARTICLE_RE.finditer(text))
    sections = list(SECTION_RE.finditer(text))
    parents: list[dict[str, Any]] = []
    leaves: list[dict[str, Any]] = []

    if not articles:
        # Lossless fallback for circulars, tables, appendices, and OCR documents
        # that do not expose a reliable MADDE structure.
        for page, page_text in document.pages:
            parent_id = "parent-" + stable_hash(document.document_id, "page", page)
            parents.append(
                {
                    "parent_id": parent_id,
                    "document_id": document.document_id,
                    "title": document.title,
                    "section": f"Sayfa {page}",
                    "article": None,
                    "text": page_text,
                    "page": page,
                    "page_end": page,
                    "source": document.source,
                }
            )
            for part_index, part in enumerate(bounded_parts(page_text, max_chars), start=1):
                leaves.append(
                    leaf_record(
                        document,
                        parent_id=parent_id,
                        parent_text=page_text,
                        section=f"Sayfa {page}",
                        article=None,
                        paragraph=None,
                        clause=None,
                        level="page_fallback",
                        text=part,
                        page=page,
                        page_end=page,
                        source_offset=0,
                        part_index=part_index,
                    )
                )
        return parents, leaves

    for index, match in enumerate(articles):
        start = match.start()
        end = articles[index + 1].start() if index + 1 < len(articles) else len(text)
        # Prevent the next section heading from being appended to the prior article.
        intervening_sections = [item.start() for item in sections if match.end() < item.start() < end]
        if intervening_sections:
            end = min(intervening_sections)
        article = normalize(match.group("label"))
        section = section_for(sections, start)
        parent_text = normalize(text[start:end])
        if not parent_text:
            continue
        page = page_for_offset(spans, start)
        page_end = page_for_offset(spans, max(start, end - 1))
        parent_id = "parent-" + stable_hash(document.document_id, article, parent_text)
        parents.append(
            {
                "parent_id": parent_id,
                "document_id": document.document_id,
                "title": document.title,
                "section": section,
                "article": article,
                "text": parent_text,
                "page": page,
                "page_end": page_end,
                "source": document.source,
                "source_url": document.source_url,
                "source_sha256": document.source_sha256,
            }
        )
        leaves.extend(
            split_article_leaves(
                document,
                parent_id=parent_id,
                parent_text=parent_text,
                body=text[match.end():end],
                body_offset=match.end(),
                section=section,
                article=article,
                spans=spans,
                max_chars=max_chars,
            )
        )
    return parents, leaves


def reference_edges(leaves: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    edges: list[dict[str, Any]] = []
    seen: set[str] = set()
    for leaf in leaves:
        text = leaf["text"]
        occupied: list[tuple[int, int]] = []
        for match in EXPLICIT_REFERENCE_RE.finditer(text):
            occupied.append(match.span())
            edge_id = "edge-" + stable_hash(leaf["leaf_id"], match.group(0))
            if edge_id in seen:
                continue
            seen.add(edge_id)
            edges.append(
                {
                    "edge_id": edge_id,
                    "source_leaf_id": leaf["leaf_id"],
                    "source_parent_id": leaf["parent_id"],
                    "relation": "CITES",
                    "raw_reference": match.group(0),
                    "target_law_number": match.group("law_no"),
                    "target_law_name_candidate": normalize(match.group("law_name")),
                    "target_article_candidate": match.group("article"),
                    "resolution_status": "candidate_unresolved",
                    "confidence": 0.82,
                    "source_page": leaf["page"],
                }
            )
        for match in SAME_DOCUMENT_REFERENCE_RE.finditer(text):
            if any(start <= match.start() < end for start, end in occupied):
                continue
            edge_id = "edge-" + stable_hash(leaf["leaf_id"], match.group(0), "same-document")
            if edge_id in seen:
                continue
            seen.add(edge_id)
            edges.append(
                {
                    "edge_id": edge_id,
                    "source_leaf_id": leaf["leaf_id"],
                    "source_parent_id": leaf["parent_id"],
                    "relation": "CITES",
                    "raw_reference": match.group(0),
                    "target_document_id": leaf["document_id"],
                    "target_article_candidate": match.group("article"),
                    "resolution_status": "candidate_unresolved",
                    "confidence": 0.68,
                    "source_page": leaf["page"],
                }
            )
    return edges


def tokenize(text: str) -> list[str]:
    return [token.casefold().replace("i̇", "i") for token in TOKEN_RE.findall(text)]


def build_bm25(leaves: Sequence[dict[str, Any]], k1: float = 1.2, b: float = 0.75) -> tuple[dict[str, Any], list[tuple[list[int], list[float]]]]:
    tokenized = [tokenize(item["embedding_text"]) for item in leaves]
    document_frequency: Counter[str] = Counter()
    for tokens in tokenized:
        document_frequency.update(set(tokens))
    vocabulary = {token: index for index, token in enumerate(sorted(document_frequency))}
    count = len(tokenized)
    average_length = sum(map(len, tokenized)) / max(count, 1)
    idf = {
        token: math.log(1.0 + (count - frequency + 0.5) / (frequency + 0.5))
        for token, frequency in document_frequency.items()
    }
    vectors: list[tuple[list[int], list[float]]] = []
    for tokens in tokenized:
        frequencies = Counter(tokens)
        denominator_length = k1 * (1.0 - b + b * len(tokens) / max(average_length, 1.0))
        weighted = []
        for token, frequency in frequencies.items():
            score = idf[token] * (frequency * (k1 + 1.0)) / (frequency + denominator_length)
            weighted.append((vocabulary[token], float(score)))
        weighted.sort()
        vectors.append(([item[0] for item in weighted], [item[1] for item in weighted]))
    metadata = {
        "tokenizer": "turkish_casefold_raw_v1",
        "vocabulary": vocabulary,
        "idf": idf,
        "document_count": count,
        "average_document_length": average_length,
        "k1": k1,
        "b": b,
        "query_weighting": "term_frequency; document vector already contains BM25 idf",
    }
    return metadata, vectors


def batches(values: Sequence[int], size: int) -> Iterator[Sequence[int]]:
    for start in range(0, len(values), size):
        yield values[start:start + size]


def format_duration(seconds: float) -> str:
    if not math.isfinite(seconds) or seconds < 0:
        return "bilinmiyor"
    total = int(round(seconds))
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def require_cuda(requested_devices: Sequence[str] | None) -> tuple[Any, list[str]]:
    import torch

    if not torch.cuda.is_available():
        raise RuntimeError(
            "CUDA bulunamadı. Kaggle Notebook Settings > Accelerator bölümünden GPU seçin."
        )
    available_count = torch.cuda.device_count()
    devices = (
        list(requested_devices)
        if requested_devices
        else [f"cuda:{index}" for index in range(available_count)]
    )
    if not devices:
        raise RuntimeError("Kullanılacak CUDA cihazı seçilmedi.")
    for device in devices:
        match = re.fullmatch(r"cuda:(\d+)", device)
        if not match:
            raise ValueError(f"Geçersiz CUDA cihazı: {device!r}")
        index = int(match.group(1))
        if index >= available_count:
            raise RuntimeError(
                f"{device} bulunamadı; kullanılabilir GPU sayısı={available_count}."
            )
        print(
            f"CUDA hazır: {device}={torch.cuda.get_device_name(index)}; "
            f"torch={torch.__version__}; cuda={torch.version.cuda}",
            flush=True,
        )
    return torch, devices


def open_jina_model(
    model_name: str,
    device: str,
    model_revision: str,
    code_revision: str,
) -> Any:
    from transformers import AutoModel

    model = AutoModel.from_pretrained(
        model_name,
        revision=model_revision,
        code_revision=code_revision,
        trust_remote_code=True,
    )
    model = model.to(device)
    model.eval()
    if not callable(getattr(model, "encode", None)):
        raise RuntimeError("Jina modelinin encode() metodu bulunamadı.")
    return model


def normalized_vectors(raw: Any) -> list[list[float]]:
    if hasattr(raw, "detach"):
        raw = raw.detach()
    if hasattr(raw, "cpu"):
        raw = raw.cpu()
    if hasattr(raw, "tolist"):
        raw = raw.tolist()
    result: list[list[float]] = []
    for vector in raw:
        values = [float(value) for value in vector]
        norm = math.sqrt(sum(value * value for value in values))
        if not math.isfinite(norm) or norm <= 0:
            raise RuntimeError("Geçersiz embedding normu.")
        result.append([value / norm for value in values])
    return result


def embed_batch_on_device(
    model: Any,
    torch: Any,
    texts: Sequence[str],
) -> list[list[float]]:
    """Run one batch on the model permanently assigned to one CUDA device."""

    with torch.inference_mode():
        raw = model.encode(
            list(texts),
            task="retrieval.passage",
            truncate_dim=VECTOR_DIMENSION,
            batch_size=len(texts),
        )
    return normalized_vectors(raw)


def build_qdrant(
    leaves: Sequence[dict[str, Any]],
    sparse_vectors: Sequence[tuple[list[int], list[float]]],
    *,
    output_dir: Path,
    collection_name: str,
    model_name: str,
    model_revision: str,
    code_revision: str,
    devices: Sequence[str] | None,
    batch_size: int,
    upsert_batch_size: int,
    overwrite: bool,
) -> dict[str, Any]:
    torch, resolved_devices = require_cuda(devices)
    from qdrant_client import QdrantClient, models

    qdrant_path = output_dir / "qdrant"
    checkpoint_path = output_dir / "checkpoint.json"
    leaf_fingerprint = sha256(
        "\n".join(item["leaf_id"] for item in leaves).encode("utf-8")
    ).hexdigest()
    if checkpoint_path.is_file() and not overwrite:
        previous_checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
        if previous_checkpoint.get("leaf_fingerprint") != leaf_fingerprint:
            raise RuntimeError(
                "Checkpoint farklı bir leaf korpusuna ait. Yeni bir --output yolu "
                "kullanın veya bilinçli olarak --overwrite verin."
            )
        if previous_checkpoint.get("collection_name") != collection_name:
            raise RuntimeError(
                "Checkpoint farklı bir Qdrant koleksiyonuna ait. Yeni bir --output "
                "yolu kullanın veya bilinçli olarak --overwrite verin."
            )
    client = QdrantClient(path=str(qdrant_path))
    existing = {item.name for item in client.get_collections().collections}
    if collection_name in existing and overwrite:
        client.delete_collection(collection_name)
        existing.remove(collection_name)
    if collection_name not in existing:
        client.create_collection(
            collection_name=collection_name,
            vectors_config={
                "dense": models.VectorParams(size=VECTOR_DIMENSION, distance=models.Distance.COSINE)
            },
            sparse_vectors_config={
                "bm25": models.SparseVectorParams(
                    index=models.SparseIndexParams(on_disk=True)
                )
            },
        )

    point_ids = [str(uuid.uuid5(uuid.NAMESPACE_URL, item["leaf_id"])) for item in leaves]
    missing_indices: list[int] = []
    for index_batch in batches(list(range(len(leaves))), 256):
        ids = [point_ids[index] for index in index_batch]
        found = {str(point.id) for point in client.retrieve(collection_name, ids=ids, with_payload=False)}
        missing_indices.extend(index for index in index_batch if point_ids[index] not in found)
    print(f"Qdrant resume: mevcut={len(leaves) - len(missing_indices)}, eksik={len(missing_indices)}", flush=True)
    checkpoint_base = {
        "pipeline_version": PIPELINE_VERSION,
        "collection_name": collection_name,
        "leaf_fingerprint": leaf_fingerprint,
        "total_leaf_count": len(leaves),
        "embedding_model": model_name,
        "embedding_model_revision": model_revision,
        "embedding_code_revision": code_revision,
        "devices": resolved_devices,
    }
    if not missing_indices:
        atomic_write_json(
            checkpoint_path,
            {
                **checkpoint_base,
                "status": "completed",
                "completed_count": len(leaves),
                "remaining_count": 0,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            },
        )
        client.close()
        return {
            "indexed_count": len(leaves),
            "qdrant_path": str(qdrant_path),
            "checkpoint": str(checkpoint_path),
            "resumed": True,
        }

    models_by_device: list[Any] = []
    for device in resolved_devices:
        print(f"Jina-v3 yükleniyor: {device}", flush=True)
        models_by_device.append(
            open_jina_model(model_name, device, model_revision, code_revision)
        )
    print(
        f"Çoklu GPU embedding hazır: {len(models_by_device)} GPU; "
        f"cihazlar={','.join(resolved_devices)}",
        flush=True,
    )
    indexed = len(leaves) - len(missing_indices)
    run_started = time.monotonic()
    embedded_this_run = 0
    atomic_write_json(
        checkpoint_path,
        {
            **checkpoint_base,
            "status": "running",
            "completed_count": indexed,
            "remaining_count": len(leaves) - indexed,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        },
    )
    executors = [
        concurrent.futures.ThreadPoolExecutor(
            max_workers=1,
            thread_name_prefix=f"jina-{device.replace(':', '-')}",
        )
        for device in resolved_devices
    ]
    work_batches = iter(batches(missing_indices, batch_size))
    pending: dict[concurrent.futures.Future[list[list[float]]], tuple[int, Sequence[int]]] = {}

    def submit_next(device_index: int) -> bool:
        try:
            encode_indices = next(work_batches)
        except StopIteration:
            return False
        texts = [leaves[index]["embedding_text"] for index in encode_indices]
        future = executors[device_index].submit(
            embed_batch_on_device,
            models_by_device[device_index],
            torch,
            texts,
        )
        pending[future] = (device_index, encode_indices)
        return True

    for device_index in range(len(executors)):
        submit_next(device_index)

    try:
        while pending:
            completed, _ = concurrent.futures.wait(
                tuple(pending),
                return_when=concurrent.futures.FIRST_COMPLETED,
            )
            for future in completed:
                device_index, encode_indices = pending.pop(future)
                dense_vectors = future.result()
                points = []
                for local_index, leaf_index in enumerate(encode_indices):
                    sparse_indices, sparse_values = sparse_vectors[leaf_index]
                    payload = dict(leaves[leaf_index])
                    payload.update(
                        {
                            "embedding_model": model_name,
                            "embedding_model_revision": model_revision,
                            "embedding_code_revision": code_revision,
                            "embedding_dimension": VECTOR_DIMENSION,
                            "embedding_task": "retrieval.passage",
                            "pipeline_version": PIPELINE_VERSION,
                        }
                    )
                    points.append(
                        models.PointStruct(
                            id=point_ids[leaf_index],
                            vector={
                                "dense": dense_vectors[local_index],
                                "bm25": models.SparseVector(
                                    indices=sparse_indices,
                                    values=sparse_values,
                                ),
                            },
                            payload=payload,
                        )
                    )
                for point_batch_start in range(0, len(points), upsert_batch_size):
                    client.upsert(
                        collection_name=collection_name,
                        points=points[
                            point_batch_start : point_batch_start + upsert_batch_size
                        ],
                        wait=True,
                    )
                indexed += len(points)
                embedded_this_run += len(points)
                elapsed = max(time.monotonic() - run_started, 1e-9)
                rate = embedded_this_run / elapsed
                remaining = len(leaves) - indexed
                eta = remaining / rate if rate > 0 else math.inf
                progress = indexed * 100.0 / len(leaves)
                atomic_write_json(
                    checkpoint_path,
                    {
                        **checkpoint_base,
                        "status": "running",
                        "completed_count": indexed,
                        "remaining_count": remaining,
                        "last_completed_leaf_id": leaves[encode_indices[-1]][
                            "leaf_id"
                        ],
                        "last_completed_point_id": point_ids[encode_indices[-1]],
                        "average_leaf_per_second": rate,
                        "elapsed_seconds_this_run": elapsed,
                        "eta_seconds": eta,
                        "updated_at": datetime.now(timezone.utc).isoformat(),
                    },
                )
                print(
                    "Embedding/Qdrant: "
                    f"{indexed}/{len(leaves)} ({progress:.2f}%) | "
                    f"gpu={len(resolved_devices)} | "
                    f"hız={rate:.2f} leaf/sn | "
                    f"geçen={format_duration(elapsed)} | "
                    f"ETA={format_duration(eta)} | checkpoint=OK",
                    flush=True,
                )
                submit_next(device_index)
    except BaseException as exc:
        for future in pending:
            future.cancel()
        for executor in executors:
            executor.shutdown(wait=False, cancel_futures=True)
        atomic_write_json(
            checkpoint_path,
            {
                **checkpoint_base,
                "status": "failed",
                "completed_count": indexed,
                "remaining_count": len(leaves) - indexed,
                "error_type": type(exc).__name__,
                "error": str(exc)[:1000],
                "updated_at": datetime.now(timezone.utc).isoformat(),
            },
        )
        client.close()
        raise
    for executor in executors:
        executor.shutdown(wait=True)
    del models_by_device
    torch.cuda.empty_cache()
    count = client.count(collection_name, exact=True).count
    if count != len(leaves):
        raise RuntimeError(f"Qdrant sayımı uyuşmuyor: {count} != {len(leaves)}")
    atomic_write_json(
        checkpoint_path,
        {
            **checkpoint_base,
            "status": "completed",
            "completed_count": count,
            "remaining_count": 0,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        },
    )
    client.close()
    return {
        "indexed_count": count,
        "qdrant_path": str(qdrant_path),
        "checkpoint": str(checkpoint_path),
        "resumed": False,
    }


def sha256_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--model-revision", default=DEFAULT_MODEL_REVISION)
    parser.add_argument("--code-revision", default=DEFAULT_CODE_REVISION)
    parser.add_argument("--collection", default=DEFAULT_COLLECTION)
    parser.add_argument("--max-leaf-chars", type=int, default=1800)
    parser.add_argument("--batch-size", type=int, default=32)
    parser.add_argument(
        "--devices",
        nargs="+",
        help="CUDA cihazları; varsayılan olarak görünen tüm GPU'lar kullanılır",
    )
    parser.add_argument("--upsert-batch-size", type=int, default=64)
    parser.add_argument("--limit", type=int, help="İlk N belgeyle pilot koşu")
    parser.add_argument("--prepare-only", action="store_true", help="GPU embedding aşamasını atla")
    parser.add_argument("--install-deps", action="store_true")
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--no-zip", action="store_true")
    # Pasting the complete file into a Kaggle notebook cell exposes the
    # ipykernel's own ``-f`` argument. In that mode use this file's defaults.
    args = parser.parse_args([] if "ipykernel" in sys.modules else None)
    for name in ("max_leaf_chars", "batch_size", "upsert_batch_size"):
        if getattr(args, name) < 1:
            parser.error(f"--{name.replace('_', '-')} pozitif olmalıdır")
    if args.limit is not None and args.limit < 1:
        parser.error("--limit pozitif olmalıdır")
    return args


def main() -> int:
    args = parse_args()
    # Safe to run on every full Kaggle build: this pins only RAG dependencies
    # and deliberately does not install, remove, or replace PyTorch.
    if not args.prepare_only:
        install_dependencies()
    input_path = args.input.resolve()
    output_dir = args.output.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    envelope, documents = load_documents(input_path, args.limit)
    print(f"Kaynak yüklendi: belge={len(documents)}", flush=True)

    parents: list[dict[str, Any]] = []
    leaves: list[dict[str, Any]] = []
    for index, document in enumerate(documents, start=1):
        document_parents, document_leaves = chunk_document(document, args.max_leaf_chars)
        parents.extend(document_parents)
        leaves.extend(document_leaves)
        if index % 25 == 0 or index == len(documents):
            print(f"Chunklama: {index}/{len(documents)}; parent={len(parents)}; leaf={len(leaves)}", flush=True)
    if not leaves:
        raise RuntimeError("Hiç leaf chunk üretilemedi.")
    if len({item["leaf_id"] for item in leaves}) != len(leaves):
        raise RuntimeError("leaf_id çakışması bulundu.")

    edges = reference_edges(leaves)
    parents_path = output_dir / "parents.jsonl"
    leaves_path = output_dir / "leaves.jsonl"
    edges_path = output_dir / "reference_edges_candidates.jsonl"
    write_jsonl(parents_path, parents)
    write_jsonl(leaves_path, leaves)
    write_jsonl(edges_path, edges)
    bm25_metadata, sparse_vectors = build_bm25(leaves)
    bm25_path = output_dir / "bm25_vocabulary.json"
    write_json(bm25_path, bm25_metadata)

    qdrant_result: dict[str, Any] | None = None
    if not args.prepare_only:
        qdrant_result = build_qdrant(
            leaves,
            sparse_vectors,
            output_dir=output_dir,
            collection_name=args.collection,
            model_name=args.model,
            model_revision=args.model_revision,
            code_revision=args.code_revision,
            devices=args.devices,
            batch_size=args.batch_size,
            upsert_batch_size=args.upsert_batch_size,
            overwrite=args.overwrite,
        )

    manifest = {
        "pipeline_version": PIPELINE_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_file": input_path.name,
        "source_sha256": sha256_file(input_path),
        "source_document_count": envelope.get("document_count"),
        "processed_document_count": len(documents),
        "parent_count": len(parents),
        "leaf_count": len(leaves),
        "reference_candidate_count": len(edges),
        "fallback_leaf_count": sum(item["level"] == "page_fallback" for item in leaves),
        "embedding_model": None if args.prepare_only else args.model,
        "embedding_model_revision": None if args.prepare_only else args.model_revision,
        "embedding_code_revision": None if args.prepare_only else args.code_revision,
        "embedding_dimension": None if args.prepare_only else VECTOR_DIMENSION,
        "embedding_task": None if args.prepare_only else "retrieval.passage",
        "collection_name": None if args.prepare_only else args.collection,
        "qdrant": qdrant_result,
        "legal_reliance_allowed": False,
        "reference_edges_are_verified": False,
        "artifacts": {
            "parents": {"file": parents_path.name, "sha256": sha256_file(parents_path)},
            "leaves": {"file": leaves_path.name, "sha256": sha256_file(leaves_path)},
            "reference_edges": {"file": edges_path.name, "sha256": sha256_file(edges_path)},
            "bm25_vocabulary": {"file": bm25_path.name, "sha256": sha256_file(bm25_path)},
        },
    }
    manifest_path = output_dir / "build_manifest.json"
    write_json(manifest_path, manifest)

    archive: str | None = None
    if not args.no_zip:
        archive = shutil.make_archive(str(output_dir), "zip", root_dir=output_dir)
    print(json.dumps({**manifest, "download_archive": archive}, ensure_ascii=False, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
