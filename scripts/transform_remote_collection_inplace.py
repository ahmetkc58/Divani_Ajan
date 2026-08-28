"""Transform ``legal_chunks_direct`` on the team's remote Qdrant server
in place, into this project's payload contract -- payload only, no vectors
ever cross the network.

The user uploaded the original (unmodified) ``qdrant_db_tamamlandi`` export
directly into a collection named ``legal_chunks_direct`` on the shared
competition Qdrant proxy. Its vectors are already correct (same source as
``scripts/integrate_external_legal_corpus.py`` transformed locally into
``data/processed/external_legal_corpus.json``); only the payload shape needs
to change, from the source schema
(``content``/``id``/``madde_no``/``mevzuat_adi``/``hukuki_nitelik``) to
``LegislationChunk`` + the corpus/chunk-fingerprint contract
``QdrantStore.build_payload`` expects.

Approach: scroll the collection for ``(point_id, payload['id'])`` pairs,
derive each point's ``chunk_id`` the same way
``integrate_external_legal_corpus.py`` did, look up the already-built and
validated chunk from ``data/processed/external_legal_corpus.json``, build
its correct payload via the real ``QdrantStore.build_payload`` (so the exact
same trust/fingerprint contract applies as any other snapshot), and send
many distinct-payload ``OverwritePayloadOperation``s per
``batch_update_points`` call. No vector ever needs to be re-read or
re-uploaded.
"""

from __future__ import annotations

import argparse
import os
import time
from hashlib import sha256
from pathlib import Path

from qdrant_client import QdrantClient, models

from karayol_agent.retrieval.contracts import CorpusMode
from karayol_agent.retrieval.qdrant_store import QdrantStore
from karayol_agent.retrieval.repository import LegislationRepository


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CORPUS = ROOT / "data" / "processed" / "external_legal_corpus.json"
DEFAULT_COLLECTION = "legal_chunks_direct"


def _with_retry(fn, *, attempts: int = 5, base_delay: float = 2.0):
    """Retry a flaky remote call with exponential backoff.

    The shared competition Qdrant proxy occasionally drops the connection
    mid-request ("Server disconnected without sending a response"); this is
    transient, not a logic error, so it is always safe to just retry the
    same call.
    """

    last_exc: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001 - deliberately broad, network layer
            last_exc = exc
            if attempt == attempts:
                raise
            delay = base_delay * (2 ** (attempt - 1))
            print(
                f"  ağ hatası (deneme {attempt}/{attempts}), {delay:.0f}s sonra "
                f"tekrar denenecek: {exc}",
                flush=True,
            )
            time.sleep(delay)
    raise last_exc  # pragma: no cover - unreachable


def _load_dotenv_default(name: str) -> str | None:
    if name in os.environ:
        return os.environ[name]
    env_path = ROOT / ".env"
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


def _chunk_id_for(original_id: str) -> str:
    return "MEV-" + sha256(original_id.encode("utf-8")).hexdigest()[:16].upper()


def run(
    *,
    corpus_path: Path,
    collection: str,
    team_prefix: str,
    team_api_key: str,
    scroll_batch: int,
    update_batch: int,
    max_points: int | None = None,
) -> dict[str, object]:
    chunks, binding = LegislationRepository(
        corpus_path, corpus_mode=CorpusMode.COMPETITION_SNAPSHOT
    ).load_with_binding()
    chunk_by_id = {chunk.chunk_id: chunk for chunk in chunks}

    client = QdrantClient(
        url="https://evren-vektor.ssyz.org.tr",
        port=443,
        prefix=team_prefix,
        api_key=team_api_key,
        timeout=600,
        prefer_grpc=False,
    )
    store = QdrantStore(
        client=client,
        collection_name=collection,
        embedding_dimension=1024,
        corpus_mode=CorpusMode.COMPETITION_SNAPSHOT,
    )
    store.bind_corpus(binding)

    total = 0
    missing = 0
    offset = None
    pending_ops: list[models.OverwritePayloadOperation] = []

    def flush() -> None:
        nonlocal pending_ops
        if not pending_ops:
            return
        _with_retry(
            lambda: client.batch_update_points(
                collection_name=collection, update_operations=pending_ops, wait=True
            )
        )
        pending_ops = []

    try:
        while True:
            points, offset = _with_retry(
                lambda: client.scroll(
                    collection_name=collection,
                    limit=scroll_batch,
                    with_payload=["id"],
                    with_vectors=False,
                    offset=offset,
                )
            )
            if not points:
                break
            for point in points:
                original_id = point.payload.get("id")
                if not original_id:
                    missing += 1
                    continue
                chunk_id = _chunk_id_for(str(original_id))
                chunk = chunk_by_id.get(chunk_id)
                if chunk is None:
                    missing += 1
                    continue
                new_payload = store.build_payload(chunk)
                pending_ops.append(
                    models.OverwritePayloadOperation(
                        overwrite_payload=models.SetPayload(
                            payload=new_payload, points=[point.id]
                        )
                    )
                )
                total += 1
                if len(pending_ops) >= update_batch:
                    flush()

            if total % 10000 < scroll_batch:
                print(f"Dönüştürülen: {total} (eksik/eşleşmeyen: {missing})", flush=True)

            if offset is None:
                break
            if max_points is not None and total >= max_points:
                break

        flush()
    finally:
        store.close()

    return {"collection": collection, "transformed": total, "missing": missing}


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--corpus", type=Path, default=DEFAULT_CORPUS)
    result.add_argument("--collection", type=str, default=DEFAULT_COLLECTION)
    result.add_argument(
        "--team-prefix", type=str, default=_load_dotenv_default("EVREN_QDRANT_TEAM_PREFIX")
    )
    result.add_argument(
        "--team-api-key", type=str, default=_load_dotenv_default("EVREN_QDRANT_API_KEY")
    )
    result.add_argument("--scroll-batch", type=int, default=1000)
    result.add_argument("--update-batch", type=int, default=500)
    result.add_argument("--max-points", type=int, default=None)
    return result


def main() -> int:
    args = parser().parse_args()
    if not args.team_prefix or not args.team_api_key:
        raise SystemExit("--team-prefix ve --team-api-key (veya .env) zorunlu.")
    summary = run(
        corpus_path=args.corpus,
        collection=args.collection,
        team_prefix=args.team_prefix,
        team_api_key=args.team_api_key,
        scroll_batch=args.scroll_batch,
        update_batch=args.update_batch,
        max_points=args.max_points,
    )
    import json

    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
