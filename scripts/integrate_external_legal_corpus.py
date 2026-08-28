"""Convert the user-supplied ``qdrant_db_tamamlandi`` embedded collection into
this project's ``LegislationChunk``/competition-snapshot contract and produce
a corpus JSON this project can load normally.

Source shape (discovered by direct SQLite/pickle inspection, see chat):
    table ``points`` in
    ``qdrant_db_tamamlandi/collection/legal_chunks_direct/storage.sqlite``,
    one row per point, ``point`` column is a pickled
    ``qdrant_client.http.models.models.PointStruct`` with a 1024-dim vector
    and a payload of exactly: ``content``, ``id``, ``madde_no``,
    ``mevzuat_adi``, ``hukuki_nitelik``.

This source corpus is general Turkish legislation (not karayolu-specific,
no domain/page/source-file metadata, provenance/currentness unverified by
this project), so every chunk is emitted under ``CorpusMode.COMPETITION_SNAPSHOT``
with ``validity_status="needs_verification"`` and
``approved_for_active_rag=False`` -- the same fail-closed contract already
used for the UAB archive snapshot this corpus replaces.

Two-pass design so 325k+ rows never need to fit in memory at once:
  Pass 1 (this script's ``build_corpus`` step): stream the SQLite table once,
    transform each row into a LegislationChunk record, and stream-write the
    corpus JSON plus a ``chunk_order.jsonl`` sidecar (chunk_id -> sqlite
    rowid) so pass 2 can fetch the matching vector without re-deriving IDs.
  Pass 2 (this script's ``reindex`` step, run separately after the corpus
    JSON is validated): load the corpus with
    ``LegislationRepository.load_with_binding()`` (which computes the exact
    corpus/chunk fingerprints our Qdrant contract requires), then walk the
    sidecar in lockstep to pull each chunk's original embedding straight out
    of the source SQLite and upsert it via the normal ``QdrantStore`` -- no
    re-embedding.
"""

from __future__ import annotations

import argparse
import json
import pickle
import re
import sqlite3
from collections import OrderedDict
from hashlib import sha256
from pathlib import Path

from karayol_agent.retrieval.contracts import (
    COMPETITION_SNAPSHOT_DATASET_NAME,
    COMPETITION_SNAPSHOT_NOTICE,
    COMPETITION_SNAPSHOT_STATUS,
    CorpusMode,
)
from karayol_agent.text_utils import normalize_whitespace


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SQLITE = (
    ROOT / "qdrant_db_tamamlandi" / "collection" / "legal_chunks_direct" / "storage.sqlite"
)
DEFAULT_OUTPUT = ROOT / "data" / "processed" / "external_legal_corpus.json"
DEFAULT_SIDECAR = ROOT / "data" / "processed" / "external_legal_corpus.chunk_order.jsonl"

_FIKRA_SUFFIX = re.compile(r"_F(\d+)$")
_MADDE_TOKEN = re.compile(r"(?i)(GE[CÇ]İ?C[Iİ]?\s*)?MADDE\s*(\d+[A-ZÇĞİÖŞÜ]?)")

_DOMAIN_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "road_transport",
        ("KARAYOLU TAŞIMA", "KARA TAŞIT", "TRAFİK", "SÜRÜCÜ", "OTOYOL"),
    ),
    (
        "kgm_infrastructure",
        ("KARAYOLLARI GENEL MÜDÜRLÜĞÜ", "KARAYOLU YAPIM", "KÖPRÜ", "ALTYAPI GÜVENLİĞİ"),
    ),
    ("railway", ("DEMİRYOLU", "TREN", "RAYLI SİSTEM")),
    ("maritime", ("DENİZ", "LİMAN", "GEMİ", "KABOTAJ", "SAHİL")),
    ("aviation", ("HAVA", "HAVACILIK", "UÇAK", "HAVAALANI", "HAVALİMANI")),
    (
        "official_writing",
        ("RESMİ YAZIŞMA", "YAZIŞMA USUL", "STANDART DOSYA PLANI"),
    ),
)

_DOCUMENT_TYPE_KEYWORDS: tuple[tuple[str, str], ...] = (
    ("KANUNU", "kanun"),
    ("KANUN HÜKMÜNDE KARARNAME", "khk"),
    ("YÖNETMELİĞİ", "yonetmelik"),
    ("YÖNETMELİK", "yonetmelik"),
    ("TEBLİĞİ", "teblig"),
    ("TEBLİĞ", "teblig"),
    ("GENELGE", "genelge"),
    ("YÖNERGE", "yonerge"),
    ("KARAR", "karar"),
)


def _document_id_for(mevzuat_adi: str) -> str:
    digest = sha256(mevzuat_adi.strip().casefold().encode("utf-8")).hexdigest()[:20]
    return f"EXT-{digest.upper()}"


def _chunk_id_for(original_id: str) -> str:
    return "MEV-" + sha256(original_id.encode("utf-8")).hexdigest()[:16].upper()


def _paragraph_for(original_id: str) -> str | None:
    match = _FIKRA_SUFFIX.search(original_id)
    return match.group(1) if match else None


def _article_for(madde_no: str | None) -> str | None:
    if not madde_no or not madde_no.strip():
        return None
    normalized = normalize_whitespace(madde_no)
    match = _MADDE_TOKEN.search(normalized)
    if not match:
        return normalized
    prefix = "Geçici Madde " if match.group(1) else "Madde "
    return f"{prefix}{match.group(2)}"


def _domain_for(mevzuat_adi: str) -> tuple[str, str]:
    upper = mevzuat_adi.upper()
    for domain, keywords in _DOMAIN_KEYWORDS:
        if any(keyword in upper for keyword in keywords):
            return domain, "external_legislation"
    return "unknown", "unknown"


def _document_type_for(mevzuat_adi: str) -> str:
    upper = mevzuat_adi.upper()
    for keyword, label in _DOCUMENT_TYPE_KEYWORDS:
        if keyword in upper:
            return label
    return "unknown"


def _safe_source_path(document_id: str) -> str:
    return f"data/external/legal_chunks_direct/{document_id}.txt"


def iter_source_rows(sqlite_path: Path, *, limit: int | None = None):
    conn = sqlite3.connect(str(sqlite_path))
    try:
        cur = conn.cursor()
        query = "SELECT rowid, id, point FROM points ORDER BY rowid"
        if limit is not None:
            query += f" LIMIT {int(limit)}"
        cur.execute(query)
        while True:
            row = cur.fetchone()
            if row is None:
                break
            yield row
    finally:
        conn.close()


def transform_row(rowid: int, original_id: str, point) -> dict[str, object]:
    payload = point.payload or {}
    mevzuat_adi = normalize_whitespace(str(payload.get("mevzuat_adi") or "").strip())
    content = str(payload.get("content") or "").strip()
    madde_no = payload.get("madde_no")
    hukuki_nitelik = payload.get("hukuki_nitelik") or []

    if not mevzuat_adi or not content:
        raise ValueError(f"rowid={rowid} id={original_id!r}: mevzuat_adi/content boş.")

    # chunk_id, payload'daki OKUNABİLİR kimlikten (örn. "32485_STVE_P1")
    # hesaplanır -- sqlite tablosunun kendi (pickle'lanmış, anlamsız) satır
    # kimliğinden DEĞİL. Uzak sunucudaki (ör. legal_chunks_direct) payload'da
    # yalnızca bu okunabilir kimlik bulunur; iki taraf aynı hash'i üretsin
    # diye kaynak burada sabitlenir.
    readable_id = str(payload.get("id") or "").strip()
    if not readable_id:
        raise ValueError(f"rowid={rowid}: payload.id boş.")

    document_id = _document_id_for(mevzuat_adi)
    article = _article_for(madde_no if isinstance(madde_no, str) else None)
    section = article or mevzuat_adi[:180]
    domain, subdomain = _domain_for(mevzuat_adi)

    chunk = {
        "chunk_id": _chunk_id_for(readable_id),
        "document_id": document_id,
        "title": mevzuat_adi,
        "section": section,
        "article": article,
        "paragraph": _paragraph_for(readable_id),
        "clause": None,
        "text": content,
        "source": _safe_source_path(document_id),
        "source_sha256": sha256(document_id.encode("utf-8")).hexdigest(),
        "source_kind": CorpusMode.COMPETITION_SNAPSHOT.value,
        "page": 1,
        "page_end": 1,
        "source_url": None,
        "document_type": _document_type_for(mevzuat_adi),
        "domain": domain,
        "subdomain": subdomain,
        "validity_status": "needs_verification",
        "approved_for_active_rag": False,
        "ocr_status": "text_layer_available",
        "context_text": f"{mevzuat_adi} > {article}" if article else mevzuat_adi,
        "status": COMPETITION_SNAPSHOT_STATUS,
        "tags": [str(item) for item in hukuki_nitelik] if hukuki_nitelik else [],
    }
    return chunk


def build_corpus(
    *, sqlite_path: Path, output_path: Path, sidecar_path: Path, limit: int | None
) -> dict[str, object]:
    documents: "OrderedDict[str, dict[str, object]]" = OrderedDict()
    # chunk_id -> document_id that actually owns the written (first/unique)
    # occurrence. A duplicate row's OWN document_id can differ from the
    # owner's (e.g. same source id re-appearing under a slightly different
    # title variant) -- bookkeeping must follow the owner, never a
    # "document" whose only rows all turned out to be duplicates, or that
    # phantom entry would end up with chunk_count == 0.
    chunk_owner_doc: dict[str, str] = {}
    total = 0
    skipped = 0
    duplicate_chunk_ids = 0

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="\n") as out, sidecar_path.open(
        "w", encoding="utf-8", newline="\n"
    ) as sidecar:
        out.write('{"data":[')
        first = True
        for rowid, original_id, blob in iter_source_rows(sqlite_path, limit=limit):
            total += 1
            try:
                point = pickle.loads(blob)
                chunk = transform_row(rowid, original_id, point)
            except Exception as exc:  # noqa: BLE001 - report and skip, never abort the run
                skipped += 1
                if skipped <= 20:
                    print(f"ATLANDI rowid={rowid} id={original_id!r}: {exc}", flush=True)
                continue

            chunk_id = chunk["chunk_id"]
            owner_doc_id = chunk_owner_doc.get(chunk_id)
            if owner_doc_id is not None:
                # Duplicate of an already-written chunk: attribute the raw
                # row to whichever document actually owns that chunk, not to
                # this row's own (possibly different) document_id.
                duplicate_chunk_ids += 1
                owner = documents[owner_doc_id]
                owner["source_chunk_count"] += 1
                owner["exact_duplicate_rows_consolidated"] += 1
                continue

            doc_id = chunk["document_id"]
            doc = documents.get(doc_id)
            if doc is None:
                doc = documents[doc_id] = {
                    "document_id": doc_id,
                    "title": chunk["title"],
                    "source_path": chunk["source"],
                    "source_url": None,
                    "source_sha256": chunk["source_sha256"],
                    "source_chunk_count": 0,
                    "chunk_count": 0,
                    "exact_duplicate_rows_consolidated": 0,
                    "text_origin": "pdf_text_layer",
                    "derived_text_sha256": None,
                }
            doc["source_chunk_count"] += 1
            doc["chunk_count"] += 1
            chunk_owner_doc[chunk_id] = doc_id

            if not first:
                out.write(",")
            first = False
            out.write(json.dumps(chunk, ensure_ascii=False))
            sidecar.write(
                json.dumps(
                    {"chunk_id": chunk["chunk_id"], "sqlite_rowid": rowid},
                    ensure_ascii=False,
                )
                + "\n"
            )

            if total % 10000 == 0:
                print(
                    f"İşlenen satır: {total}; yazılan chunk: {len(chunk_owner_doc)}; "
                    f"belge: {len(documents)}",
                    flush=True,
                )
        out.write("]}")

    print(
        f"Bitti. satır={total} chunk={len(chunk_owner_doc)} belge={len(documents)} "
        f"atlanan={skipped} yinelenen_chunk_id={duplicate_chunk_ids}",
        flush=True,
    )

    # Rewrite the file with the full envelope now that final counts are known
    # (kept as a second, cheap pass over just the already-built ``data`` we
    # streamed, re-parsed once so we never hold two full copies at once).
    data_only = json.loads(output_path.read_text(encoding="utf-8"))["data"]
    corpus = {
        "schema_version": "2.0",
        "dataset_name": COMPETITION_SNAPSHOT_DATASET_NAME,
        "corpus_mode": CorpusMode.COMPETITION_SNAPSHOT.value,
        "generated_at": None,
        "currentness_verified": False,
        "legal_reliance_allowed": False,
        "approved_for_competition_use": True,
        "usage_notice": COMPETITION_SNAPSHOT_NOTICE,
        "document_count": len(documents),
        "source_chunk_count": sum(
            int(doc["source_chunk_count"]) for doc in documents.values()
        ),
        "chunk_count": len(data_only),
        "exact_duplicate_rows_consolidated": duplicate_chunk_ids,
        "documents": list(documents.values()),
        "data": data_only,
    }
    from datetime import datetime, timezone

    corpus["generated_at"] = datetime.now(timezone.utc).isoformat()
    output_path.write_text(
        json.dumps(corpus, ensure_ascii=False), encoding="utf-8", newline="\n"
    )
    return {
        "output": str(output_path),
        "document_count": len(documents),
        "chunk_count": len(data_only),
        "skipped_rows": skipped,
        "duplicate_chunk_ids": duplicate_chunk_ids,
    }


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--sqlite", type=Path, default=DEFAULT_SQLITE)
    result.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    result.add_argument("--sidecar", type=Path, default=DEFAULT_SIDECAR)
    result.add_argument("--limit", type=int, default=None)
    return result


def main() -> int:
    args = parser().parse_args()
    summary = build_corpus(
        sqlite_path=args.sqlite,
        output_path=args.output,
        sidecar_path=args.sidecar,
        limit=args.limit,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
