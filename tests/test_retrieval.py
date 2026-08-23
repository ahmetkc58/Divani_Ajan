from pathlib import Path

from karayol_agent.retrieval import BM25Index, LegislationRepository


ROOT = Path(__file__).resolve().parents[1]


def test_bm25_returns_yol_bakim_rule_first() -> None:
    chunks = LegislationRepository(ROOT / "data" / "synthetic_legislation.json").load()
    hits = BM25Index(chunks).search("asfalt çukuru için yol bakım onarım talebi", top_k=3)

    assert hits
    assert hits[0].chunk.chunk_id == "SENT-KRY-001"
    assert "asfalt" in hits[0].matched_terms

