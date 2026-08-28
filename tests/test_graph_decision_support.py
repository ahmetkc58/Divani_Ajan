from __future__ import annotations

import json
from pathlib import Path

import pytest

from karayol_agent.graph import EvidenceGraphAdvisor, GraphBuildError
from karayol_agent.schemas import VerifiedReference


PROJECT_ROOT = Path(__file__).resolve().parents[1]
GRAPH_PATH = PROJECT_ROOT / "reports" / "synthetic_evidence_graph_2026-08-24.json"


def _reference(*, verified: bool = True, source_kind: str = "synthetic") -> VerifiedReference:
    return VerifiedReference(
        chunk_id="SENT-KRY-001",
        title="Sentetik kural",
        article="Kural 1",
        source="data/synthetic_legislation.json",
        source_kind=source_kind,
        corpus_mode="trusted_synthetic",
        excerpt="Yol bakım başvurusu ilgili birime yönlendirilir.",
        score=0.9,
        verified=verified,
        verification_note="Sentetik benchmark doğrulaması.",
    )


def test_graph_advisor_returns_auditable_multi_hop_candidates() -> None:
    advisor = EvidenceGraphAdvisor.load(GRAPH_PATH, project_root=PROJECT_ROOT)

    advice = advisor.advise(
        document_type="yol_bakim_talebi",
        references=[_reference()],
        synthetic_corpus_allowed=True,
    )

    assert advice.applied is True
    assert advice.strategy == "selective_multi_hop"
    assert advice.matched_rule_ids == ["rule:SENT-KRY-001"]
    assert "ORKGM-YB-001" in advice.candidate_unit_ids
    assert "ust_yazi_v1" in advice.candidate_template_ids
    assert advice.paths
    assert advice.evidence_record_ids
    assert advice.legal_reliance_allowed is False
    assert "sentetik" in (advice.warning or "").casefold()


@pytest.mark.parametrize(
    ("synthetic_corpus_allowed", "reference"),
    [
        (False, _reference()),
        (True, _reference(verified=False)),
        (True, _reference(source_kind="public_legislation")),
    ],
)
def test_graph_advisor_abstains_outside_verified_synthetic_evidence(
    synthetic_corpus_allowed: bool,
    reference: VerifiedReference,
) -> None:
    advisor = EvidenceGraphAdvisor.load(GRAPH_PATH, project_root=PROJECT_ROOT)

    advice = advisor.advise(
        document_type="yol_bakim_talebi",
        references=[reference],
        synthetic_corpus_allowed=synthetic_corpus_allowed,
    )

    assert advice.applied is False
    assert advice.legal_reliance_allowed is False
    assert not advice.candidate_unit_ids
    assert not advice.candidate_template_ids


def test_graph_advisor_rejects_changed_provenance_hash(tmp_path: Path) -> None:
    payload = json.loads(GRAPH_PATH.read_text(encoding="utf-8"))
    payload["inputs"][0]["sha256"] = "0" * 64
    graph_path = tmp_path / "tampered-graph.json"
    graph_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(GraphBuildError, match="SHA-256"):
        EvidenceGraphAdvisor.load(graph_path, project_root=PROJECT_ROOT)


def test_graph_advisor_rejects_semantically_tampered_edge(tmp_path: Path) -> None:
    payload = json.loads(GRAPH_PATH.read_text(encoding="utf-8"))
    unit_ids = [
        node["node_id"]
        for node in payload["nodes"]
        if node["node_type"] == "Birim"
    ]
    edge = next(
        item for item in payload["edges"] if item["relation"] == "ASSIGNED_TO"
    )
    edge["target_id"] = next(
        unit_id for unit_id in unit_ids if unit_id != edge["target_id"]
    )
    graph_path = tmp_path / "tampered-edge-graph.json"
    graph_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(GraphBuildError, match="deterministik"):
        EvidenceGraphAdvisor.load(graph_path, project_root=PROJECT_ROOT)
