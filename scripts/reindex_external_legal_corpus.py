"""Index ``data/processed/external_legal_corpus.json`` into Qdrant reusing
the embeddings already present in the user-supplied
``qdrant_db_tamamlandi`` collection -- no re-embedding.

Pairs with ``scripts/integrate_external_legal_corpus.py``: that script wrote
the corpus JSON plus a ``chunk_order.jsonl`` sidecar (chunk_id -> original
sqlite rowid in ``qdrant_db_tamamlandi``). This script loads the corpus
through the normal ``LegislationRepository``/``CorpusBinding`` path (so the
exact same fingerprint contract applies as any other snapshot), then walks
chunks and sidecar rows in lockstep, pulling each chunk's original 1024-dim
vector straight out of the source SQLite and upserting it through the normal
``QdrantStore``.
"""

from __future__ import annotations

import argparse
import json
import os
import pickle
import sqlite3
from pathlib import Path

from karayol_agent.retrieval.contracts import CorpusMode
from karayol_agent.retrieval.qdrant_store import QdrantStore
from karayol_agent.retrieval.repository import LegislationRepository


def _load_dotenv_defaults(name: str) -> str | None:
    """Minimal ``.env`` reader, used only as a CLI-default fallback."""

    if name in os.environ:
        return os.environ[name]
    env_path = Path(__file__).resolve().parents[1] / ".env"
    if not env_path.is_file():
        return None
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        if key.strip() == name:
            return value.strip()
    return None


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CORPUS = ROOT / "data" / "processed" / "external_legal_corpus.json"
DEFAULT_SIDECAR = ROOT / "data" / "processed" / "external_legal_corpus.chunk_order.jsonl"
DEFAULT_SOURCE_SQLITE = (
    ROOT / "qdrant_db_tamamlandi" / "collection" / "legal_chunks_direct" / "storage.sqlite"
)
DEFAULT_QDRANT_PATH = ROOT / "runtime" / "qdrant-external-legal-corpus"
DEFAULT_COLLECTION = "external_legal_corpus_chunks_v1"


def load_sidecar_order(sidecar_path: Path) -> list[tuple[str, int]]:
    order: list[tuple[str, int]] = []
    with sidecar_path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            record = json.loads(line)
            order.append((record["chunk_id"], int(record["sqlite_rowid"])))
    return order


def fetch_vectors(cur: sqlite3.Cursor, rowids: list[int]) -> dict[int, list[float]]:
    placeholders = ",".join("?" for _ in rowids)
    cur.execute(
        f"SELECT rowid, point FROM points WHERE rowid IN ({placeholders})", rowids
    )
    result: dict[int, list[float]] = {}
    for rowid, blob in cur.fetchall():
        point = pickle.loads(blob)
        vector = point.vector
        if vector is None:
            raise ValueError(f"sqlite_rowid={rowid} için embedding yok.")
        result[rowid] = [float(value) for value in vector]
    missing = set(rowids) - result.keys()
    if missing:
        raise ValueError(f"sqlite_rowid'ler kaynakta bulunamadı: {sorted(missing)[:10]}")
    return result


def run(
    *,
    corpus_path: Path,
    sidecar_path: Path,
    source_sqlite: Path,
    qdrant_path: Path | None,
    qdrant_url: str | None,
    team_prefix: str | None = None,
    team_api_key: str | None = None,
    collection: str,
    batch_size: int,
) -> dict[str, object]:
    chunks, binding = LegislationRepository(
        corpus_path, corpus_mode=CorpusMode.COMPETITION_SNAPSHOT
    ).load_with_binding()
    chunk_by_id = {chunk.chunk_id: chunk for chunk in chunks}

    order = load_sidecar_order(sidecar_path)
    if len(order) != len(chunks):
        raise ValueError(
            f"sidecar satır sayısı ({len(order)}) korpüs chunk sayısıyla "
            f"({len(chunks)}) uyuşmuyor."
        )

    store_kwargs: dict[str, object] = {
        "collection_name": collection,
        "embedding_dimension": 1024,
        "corpus_mode": CorpusMode.COMPETITION_SNAPSHOT,
    }
    if team_prefix:
        # The competition's shared Qdrant proxy needs port=443 and a
        # team-prefix path segment passed as separate qdrant_client kwargs
        # (see https://evren-teknofest.ssyz.org.tr/hizli-baslangic);
        # QdrantStore's own client builder doesn't expose those, so build
        # the client here and inject it.
        from qdrant_client import QdrantClient

        client = QdrantClient(
            url=qdrant_url,
            port=443,
            prefix=team_prefix,
            api_key=team_api_key,
            timeout=600,
            prefer_grpc=False,
        )
        store_kwargs["client"] = client
    elif qdrant_url:
        store_kwargs["url"] = qdrant_url
    else:
        store_kwargs["path"] = qdrant_path
    store = QdrantStore(**store_kwargs)
    store.bind_corpus(binding)

    conn = sqlite3.connect(str(source_sqlite))
    cur = conn.cursor()

    total_indexed = 0
    total = len(order)
    try:
        for start in range(0, total, batch_size):
            window = order[start : start + batch_size]
            rowids = [rowid for _, rowid in window]
            vectors_by_rowid = fetch_vectors(cur, rowids)

            batch_chunks = []
            batch_vectors = []
            for chunk_id, rowid in window:
                chunk = chunk_by_id.get(chunk_id)
                if chunk is None:
                    raise ValueError(f"sidecar chunk_id={chunk_id!r} korpüste yok.")
                batch_chunks.append(chunk)
                batch_vectors.append(vectors_by_rowid[rowid])

            total_indexed += store.upsert(batch_chunks, batch_vectors)

            done = start + len(window)
            if done % 10000 < batch_size:
                print(f"İndekslenen: {done}/{total}", flush=True)
    finally:
        conn.close()
        store.close()

    return {
        "collection": collection,
        "qdrant_target": qdrant_url or str(qdrant_path),
        "indexed_points": total_indexed,
        "corpus_fingerprint": binding.fingerprint,
    }


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--corpus", type=Path, default=DEFAULT_CORPUS)
    result.add_argument("--sidecar", type=Path, default=DEFAULT_SIDECAR)
    result.add_argument("--source-sqlite", type=Path, default=DEFAULT_SOURCE_SQLITE)
    target = result.add_mutually_exclusive_group()
    target.add_argument("--qdrant-path", type=Path, default=None)
    target.add_argument("--qdrant-url", type=str, default=None)
    result.add_argument(
        "--team-prefix",
        type=str,
        default=_load_dotenv_defaults("EVREN_QDRANT_TEAM_PREFIX"),
        help="Yarışma paylaşımlı Qdrant proxy'si için takım öneki (örn. team05).",
    )
    result.add_argument(
        "--team-api-key",
        type=str,
        default=_load_dotenv_defaults("EVREN_QDRANT_API_KEY"),
        help="Yarışma paylaşımlı Qdrant proxy'si için API anahtarı.",
    )
    result.add_argument(
        "--no-team",
        action="store_true",
        help="'.env'deki takım prefix'i ayarlı olsa bile onu yok say.",
    )
    result.add_argument("--collection", type=str, default=DEFAULT_COLLECTION)
    result.add_argument("--batch-size", type=int, default=500)
    return result


def main() -> int:
    args = parser().parse_args()
    if args.no_team:
        args.team_prefix = None
        args.team_api_key = None
    qdrant_path = args.qdrant_path
    qdrant_url = args.qdrant_url
    if args.team_prefix and not qdrant_url:
        qdrant_url = "https://evren-vektor.ssyz.org.tr"
    if qdrant_path is None and not qdrant_url and not args.team_prefix:
        qdrant_path = DEFAULT_QDRANT_PATH
    summary = run(
        corpus_path=args.corpus,
        sidecar_path=args.sidecar,
        source_sqlite=args.source_sqlite,
        qdrant_path=qdrant_path,
        qdrant_url=qdrant_url,
        team_prefix=args.team_prefix,
        team_api_key=args.team_api_key,
        collection=args.collection,
        batch_size=args.batch_size,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
