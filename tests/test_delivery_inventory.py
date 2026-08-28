from __future__ import annotations

from pathlib import Path

from scripts.audit_delivery_inventory import build_inventory


ROOT = Path(__file__).resolve().parents[1]


def test_every_tracked_data_bearing_file_has_a_delivery_decision() -> None:
    report = build_inventory(ROOT / "data" / "manifests" / "delivery_policy.json")

    assert report["unresolved_paths"] == []
    decisions = {item["path"]: item["decision"] for item in report["items"]}
    assert decisions["data/synthetic_gold.json"] == "include"
    assert decisions[
        "veri_kaynaklari/karayolu/detsis/belgeler.json"
    ] == "exclude"
    assert decisions[
        "runtime/qdrant-competition-snapshot/collection/competition_snapshot_chunks_v1/storage.sqlite"
    ] == "exclude"
    assert decisions[
        "2026_TYDA_SARTNAME_Birinci_Senaryo_TR_1_A8mT1 (1).pdf"
    ] == "review_required"
