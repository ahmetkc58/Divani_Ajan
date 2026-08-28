"""Integrate the Kaggle Legal RAG v2 archive without re-embedding vectors."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import zipfile
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from karayol_agent.retrieval.contracts import (  # noqa: E402
    COMPETITION_SNAPSHOT_DATASET_NAME,
    COMPETITION_SNAPSHOT_NOTICE,
    COMPETITION_SNAPSHOT_STATUS,
    CorpusMode,
)
from karayol_agent.retrieval.qdrant_store import QdrantStore  # noqa: E402
from karayol_agent.retrieval.repository import LegislationRepository  # noqa: E402
from karayol_agent.schemas import LegislationChunk  # noqa: E402


EXPECTED_FILES = {
    "build_manifest.json",
    "leaves.jsonl",
    "parents.jsonl",
    "reference_edges_candidates.jsonl",
    "bm25_vocabulary.json",
    "qdrant/meta.json",
}
MODEL_NAME = "jinaai/jina-embeddings-v3"
MODEL_REVISION = "ab036b023d30b4d1138c4c3bfa9f0c445ab455d6"
CODE_REVISION = "bd55a5ec8e6c0fb1d6c26efb4b6a4a74ce8a88d3"
COLLECTION_NAME = "uab_legal_leaf_v2"


def _safe_extract(archive: Path, target: Path) -> None:
    if target.exists():
        existing = {
            path.relative_to(target).as_posix()
            for path in target.rglob("*")
            if path.is_file()
        }
        missing = sorted(EXPECTED_FILES - existing)
        if missing:
            raise RuntimeError(
                f"Hedef eksik bir kurulum içeriyor: {target}; eksik: "
                + ", ".join(missing)
            )
        print(f"Hazır çıkarılmış paket yeniden kullanılıyor: {target}", flush=True)
        return
    with zipfile.ZipFile(archive) as bundle:
        names = set(bundle.namelist())
        missing = sorted(EXPECTED_FILES - names)
        if missing:
            raise RuntimeError("Arşiv zorunlu dosyaları taşımıyor: " + ", ".join(missing))
        for info in bundle.infolist():
            member = PurePosixPath(info.filename)
            if member.is_absolute() or ".." in member.parts:
                raise RuntimeError(f"Güvensiz ZIP yolu reddedildi: {info.filename}")
        target.mkdir(parents=True)
        try:
            bundle.extractall(target)
        except BaseException:
            shutil.rmtree(target)
            raise

    # Kaggle sürecinden kalan kilit çalışma verisi değildir. Yalnız tam ve
    # doğrulanmış hedefin içindeki bilinen lock dosyası kaldırılır.
    stale_lock = target / "qdrant" / ".lock"
    if stale_lock.is_file():
        stale_lock.unlink()


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, start=1):
            if not line.strip():
                continue
            value = json.loads(line)
            if not isinstance(value, dict):
                raise RuntimeError(f"{path.name}:{line_number} nesne değil.")
            rows.append(value)
    return rows


def _build_snapshot(
    leaves: list[dict[str, Any]], old_snapshot: Path, output: Path
) -> tuple[list[LegislationChunk], Any]:
    source = json.loads(old_snapshot.read_text(encoding="utf-8"))
    documents = source.get("documents")
    if not isinstance(documents, list):
        raise RuntimeError("Eski UAB snapshot documents listesi taşımıyor.")
    document_by_id = {str(item["document_id"]): dict(item) for item in documents}

    chunks: list[LegislationChunk] = []
    counts: Counter[str] = Counter()
    for leaf in leaves:
        document_id = str(leaf["document_id"])
        document = document_by_id.get(document_id)
        if document is None:
            raise RuntimeError(f"Leaf belgesi eski snapshot zarfında yok: {document_id}")
        tags = [
            str(leaf.get("domain") or "unknown"),
            str(leaf.get("subdomain") or "unknown"),
            str(leaf.get("document_type") or "unknown"),
            str(leaf.get("level") or "leaf"),
            f"parent:{leaf['parent_id']}",
        ]
        page = int(leaf["page"])
        page_end = int(leaf["page_end"])
        if page_end < page:
            # Bazı kaynak sayfa blokları sıralı gelmediğinde Kaggle parent
            # birleştirmesi uçları ters yazmış olabilir. Aynı iki uç korunarak
            # yalnız aralık kanonik küçük->büyük biçimine çevrilir.
            page, page_end = page_end, page
        chunk = LegislationChunk(
            chunk_id=str(leaf["leaf_id"]),
            document_id=document_id,
            title=str(leaf["title"]),
            section=str(leaf.get("section") or leaf.get("article") or leaf["title"]),
            article=leaf.get("article"),
            paragraph=leaf.get("paragraph"),
            clause=leaf.get("clause"),
            text=str(leaf["text"]),
            source=str(leaf["source"]),
            source_sha256=str(leaf["source_sha256"]),
            source_kind=CorpusMode.COMPETITION_SNAPSHOT.value,
            page=page,
            page_end=page_end,
            source_url=leaf.get("source_url"),
            document_type=str(leaf.get("document_type") or "unknown"),
            domain=str(leaf.get("domain") or "unknown"),
            subdomain=str(leaf.get("subdomain") or "unknown"),
            validity_status="needs_verification",
            approved_for_active_rag=False,
            ocr_status=str(leaf.get("ocr_status") or "not_inspected"),
            context_text=str(leaf.get("context_text") or leaf["title"]),
            status=COMPETITION_SNAPSHOT_STATUS,
            tags=tags,
        )
        if (
            chunk.source != document.get("source_path")
            or chunk.source_sha256 != document.get("source_sha256")
            or chunk.source_url != document.get("source_url")
        ):
            raise RuntimeError(f"{chunk.chunk_id}: kaynak izi belge zarfıyla uyuşmuyor.")
        chunks.append(chunk)
        counts[document_id] += 1

    for document_id, document in document_by_id.items():
        count = counts[document_id]
        if count < 1:
            raise RuntimeError(f"V2 leaf içermeyen belge var: {document_id}")
        document["source_chunk_count"] = count
        document["chunk_count"] = count
        document["exact_duplicate_rows_consolidated"] = 0

    envelope = {
        "schema_version": "2.0",
        "dataset_name": COMPETITION_SNAPSHOT_DATASET_NAME,
        "corpus_mode": CorpusMode.COMPETITION_SNAPSHOT.value,
        "generated_at": datetime.now(UTC).isoformat(),
        "currentness_verified": False,
        "legal_reliance_allowed": False,
        "approved_for_competition_use": True,
        "usage_notice": COMPETITION_SNAPSHOT_NOTICE,
        "document_count": len(documents),
        "source_chunk_count": len(chunks),
        "chunk_count": len(chunks),
        "exact_duplicate_rows_consolidated": 0,
        "documents": [document_by_id[str(item["document_id"])] for item in documents],
        "data": [chunk.model_dump(mode="json") for chunk in chunks],
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(envelope, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    validated, binding = LegislationRepository(
        output, corpus_mode=CorpusMode.COMPETITION_SNAPSHOT
    ).load_with_binding()
    if len(validated) != len(chunks):
        raise RuntimeError("Yazılan v2 snapshot kayıt sayısı doğrulanamadı.")
    return validated, binding


def _upgrade_qdrant_payloads(
    qdrant_path: Path, chunks: list[LegislationChunk], binding: Any
) -> int:
    from qdrant_client import models

    store = QdrantStore(
        path=qdrant_path,
        collection_name=COLLECTION_NAME,
        vector_name="dense",
        embedding_model=MODEL_NAME,
        embedding_dimension=1024,
        embedding_model_revision=MODEL_REVISION,
        embedding_code_revision=CODE_REVISION,
        index_version="2.0",
        corpus_mode=CorpusMode.COMPETITION_SNAPSHOT,
    )
    store.bind_corpus(binding)
    store.require_collection()
    chunk_by_id = {chunk.chunk_id: chunk for chunk in chunks}
    client = store.client
    offset = None
    scanned = 0
    rewritten = 0
    try:
        while True:
            points, offset = client.scroll(
                collection_name=COLLECTION_NAME,
                limit=1024,
                offset=offset,
                with_payload=True,
                with_vectors=True,
            )
            if not points:
                break
            replacements = []
            for point in points:
                old_payload = point.payload or {}
                chunk_id = str(old_payload.get("leaf_id") or old_payload.get("chunk_id") or "")
                chunk = chunk_by_id.get(chunk_id)
                if chunk is None:
                    raise RuntimeError(f"Qdrant noktası v2 snapshot'ta yok: {chunk_id!r}")
                if (
                    old_payload.get("corpus_fingerprint") == binding.fingerprint
                    and old_payload.get("index_version") == "2.0"
                    and old_payload.get("chunk_id") == chunk_id
                ):
                    continue
                payload = dict(old_payload)
                payload.update(store.build_payload(chunk))
                replacements.append(
                    models.PointStruct(id=point.id, vector=point.vector, payload=payload)
                )
            if replacements:
                client.upsert(
                    collection_name=COLLECTION_NAME,
                    points=replacements,
                    wait=True,
                )
            scanned += len(points)
            rewritten += len(replacements)
            print(
                f"Payload entegrasyonu: {scanned}/{len(chunks)} "
                f"(yazılan={rewritten})",
                flush=True,
            )
            if offset is None:
                break
        report = store.validate_readiness()
        if report.compatible_point_count != len(chunks):
            raise RuntimeError("Qdrant readiness sayımı v2 corpus ile uyuşmuyor.")
        return report.compatible_point_count
    finally:
        store.close()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("archive", type=Path)
    parser.add_argument(
        "--target", type=Path, default=PROJECT_ROOT / "runtime/uab-legal-rag-v2"
    )
    parser.add_argument(
        "--old-snapshot",
        type=Path,
        default=PROJECT_ROOT / "data/processed/uab_ministry_archive_snapshot.json",
    )
    parser.add_argument(
        "--snapshot-output",
        type=Path,
        default=PROJECT_ROOT / "data/processed/uab_legal_rag_v2_snapshot.json",
    )
    args = parser.parse_args()
    archive = args.archive.resolve()
    if not archive.is_file():
        raise FileNotFoundError(archive)
    _safe_extract(archive, args.target.resolve())
    leaves = _load_jsonl(args.target.resolve() / "leaves.jsonl")
    manifest = json.loads((args.target.resolve() / "build_manifest.json").read_text("utf-8"))
    if len(leaves) != 30_972 or manifest.get("leaf_count") != len(leaves):
        raise RuntimeError("V2 leaf sayısı build manifest ile uyuşmuyor.")
    chunks, binding = _build_snapshot(leaves, args.old_snapshot, args.snapshot_output)
    upgraded = _upgrade_qdrant_payloads(args.target.resolve() / "qdrant", chunks, binding)
    print(
        json.dumps(
            {
                "status": "ready",
                "chunks": len(chunks),
                "qdrant_points": upgraded,
                "collection": COLLECTION_NAME,
                "vector_name": "dense",
                "corpus_fingerprint": binding.fingerprint,
                "snapshot": str(args.snapshot_output.resolve()),
                "qdrant_path": str((args.target.resolve() / "qdrant")),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
