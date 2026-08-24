from __future__ import annotations

import json
from hashlib import sha256
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = ROOT / "resources" / "manifests" / "sources.json"


def _scoped_bytes(path: Path, scope: object) -> bytes:
    raw = path.read_bytes()
    if scope in {None, "raw_file"}:
        return raw
    if scope == "normalized_lf_utf8_text":
        text = raw.decode("utf-8")
        normalized = text.replace("\r\n", "\n").replace("\r", "\n")
        return normalized.encode("utf-8")
    raise AssertionError(f"Bilinmeyen hash_scope: {scope!r}")


def test_local_resource_manifest_hashes_match_declared_scope() -> None:
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    checked_ids: list[str] = []

    for item in manifest["items"]:
        local_path = item.get("local_path")
        declared_hash = item.get("sha256")
        if local_path is None or declared_hash is None:
            continue

        artifact_path = (ROOT / local_path).resolve()
        assert artifact_path.is_relative_to(ROOT)
        assert artifact_path.is_file(), item["id"]
        content = _scoped_bytes(artifact_path, item.get("hash_scope"))
        assert len(content) == item["bytes"], item["id"]
        assert sha256(content).hexdigest() == declared_hash, item["id"]
        checked_ids.append(item["id"])

    assert checked_ids
