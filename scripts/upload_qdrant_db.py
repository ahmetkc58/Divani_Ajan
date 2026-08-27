from __future__ import annotations

import argparse
import json
import os
import pickle
import sqlite3
import sys
import time
from pathlib import Path
from typing import Any

from qdrant_client import QdrantClient, models


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Embedded Qdrant SQLite collection'ını uzak Qdrant'a aktarır."
    )
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--collection", required=True)
    parser.add_argument("--url", default="https://evren-vektor.ssyz.org.tr")
    parser.add_argument("--port", type=int, default=443)
    parser.add_argument("--prefix", required=True)
    parser.add_argument("--batch-size", type=int, default=128)
    parser.add_argument("--timeout", type=float, default=600.0)
    parser.add_argument("--checkpoint", type=Path, required=True)
    return parser.parse_args()


def load_checkpoint(path: Path, collection: str) -> tuple[int, int]:
    if not path.exists():
        return 0, 0
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("collection") != collection:
        raise RuntimeError("Kontrol noktası farklı bir koleksiyona ait.")
    return int(data.get("last_rowid", 0)), int(data.get("uploaded", 0))


def save_checkpoint(
    path: Path, collection: str, last_rowid: int, uploaded: int, total: int
) -> None:
    temp_path = path.with_suffix(path.suffix + ".tmp")
    temp_path.write_text(
        json.dumps(
            {
                "collection": collection,
                "last_rowid": last_rowid,
                "uploaded": uploaded,
                "total": total,
                "updated_at_unix": int(time.time()),
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    temp_path.replace(path)


def vector_params(info: Any) -> Any:
    return info.config.params.vectors


def ensure_destination(client: QdrantClient, collection: str) -> None:
    existing = {item.name for item in client.get_collections().collections}
    if collection not in existing:
        client.create_collection(
            collection_name=collection,
            vectors_config=models.VectorParams(
                size=1024,
                distance=models.Distance.COSINE,
                on_disk=True,
            ),
        )
        print(f"Koleksiyon oluşturuldu: {collection}", flush=True)
        return

    params = vector_params(client.get_collection(collection))
    if isinstance(params, dict) or params.size != 1024 or params.distance != models.Distance.COSINE:
        raise RuntimeError(
            f"Mevcut {collection} koleksiyonunun vektör şeması 1024/Cosine değil."
        )
    print(f"Mevcut koleksiyon kullanılacak: {collection}", flush=True)


def main() -> int:
    args = parse_args()
    api_key = os.environ.get("QDRANT_API_KEY")
    if not api_key:
        raise RuntimeError("QDRANT_API_KEY ortam değişkeni tanımlı değil.")
    if args.batch_size < 1:
        raise ValueError("--batch-size pozitif olmalı.")

    sqlite_path = (
        args.source / "collection" / args.collection / "storage.sqlite"
    ).resolve()
    if not sqlite_path.is_file():
        raise FileNotFoundError(sqlite_path)

    source = sqlite3.connect(f"file:{sqlite_path.as_posix()}?mode=ro", uri=True)
    destination = QdrantClient(
        url=args.url,
        port=args.port,
        prefix=args.prefix,
        api_key=api_key,
        timeout=args.timeout,
        prefer_grpc=False,
    )
    try:
        total = int(source.execute("SELECT COUNT(*) FROM points").fetchone()[0])
        ensure_destination(destination, args.collection)
        last_rowid, uploaded = load_checkpoint(args.checkpoint, args.collection)
        print(
            f"Aktarım başlıyor: yerel={total}, tamamlanan={uploaded}, "
            f"son_rowid={last_rowid}",
            flush=True,
        )
        started = time.monotonic()

        while True:
            rows = source.execute(
                "SELECT rowid, point FROM points WHERE rowid > ? "
                "ORDER BY rowid LIMIT ?",
                (last_rowid, args.batch_size),
            ).fetchall()
            if not rows:
                break

            points = [pickle.loads(blob) for _, blob in rows]
            for attempt in range(1, 9):
                try:
                    destination.upsert(
                        collection_name=args.collection,
                        points=points,
                        wait=True,
                    )
                    break
                except Exception:
                    if attempt == 8:
                        raise
                    delay = min(2 ** (attempt - 1), 60)
                    print(
                        f"Geçici hata; {delay}s sonra yeniden denenecek "
                        f"(deneme {attempt}/8).",
                        file=sys.stderr,
                        flush=True,
                    )
                    time.sleep(delay)

            last_rowid = int(rows[-1][0])
            uploaded += len(rows)
            save_checkpoint(
                args.checkpoint, args.collection, last_rowid, uploaded, total
            )
            elapsed = max(time.monotonic() - started, 0.001)
            rate = uploaded / elapsed
            remaining = max(total - uploaded, 0)
            eta_minutes = remaining / max(rate, 0.001) / 60
            print(
                f"İlerleme: {uploaded}/{total} (%{uploaded / total * 100:.2f}), "
                f"{rate:.1f} nokta/sn, tahmini kalan {eta_minutes:.1f} dk",
                flush=True,
            )

        remote_count = int(
            destination.count(
                collection_name=args.collection, exact=True
            ).count
        )
        print(f"Doğrulama: yerel={total}, uzak={remote_count}", flush=True)
        if remote_count != total:
            raise RuntimeError("Uzak nokta sayısı yerel nokta sayısıyla eşleşmiyor.")
        return 0
    finally:
        source.close()
        destination.close()


if __name__ == "__main__":
    raise SystemExit(main())
