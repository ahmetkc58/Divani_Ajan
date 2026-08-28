from __future__ import annotations

import json

from karayol_agent.agents.document_type_catalog import DocumentTypeCatalog


def test_document_type_catalog_returns_evidence_bound_candidates(tmp_path) -> None:
    catalog_path = tmp_path / "belgeler.json"
    catalog_path.write_text(
        json.dumps(
            {
                "data": [
                    {
                        "belgeBeyanID": 10,
                        "belgeBeyanAdi": "Olay Yeri Tutanağı",
                        "belgeTur": "TUTANAK",
                        "istenenmi": True,
                    },
                    {
                        "belgeBeyanID": 11,
                        "belgeBeyanAdi": "Lisans Diploması",
                        "belgeTur": "DİPLOMA",
                        "istenenmi": True,
                    },
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    results = DocumentTypeCatalog([catalog_path]).search(
        "Olay yerinde düzenlenen tutanak"
    )

    assert results
    assert results[0].candidate_id == "DETSIS-BELGE-10-ISTENEN"
    assert results[0].document_type == "TUTANAK"
