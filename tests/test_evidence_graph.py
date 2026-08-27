from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from karayol_agent.graph import EvidenceGraph, EvidenceGraphBuilder, GraphBuildError


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _build():
    return EvidenceGraphBuilder().build(
        dataset_path=PROJECT_ROOT / "data" / "synthetic_gold.json",
        legislation_path=PROJECT_ROOT / "data" / "synthetic_legislation.json",
        units_path=PROJECT_ROOT / "data" / "synthetic_units.json",
    )


def test_synthetic_graph_is_auditable_and_has_no_dangling_edges() -> None:
    graph = _build()

    assert graph.benchmark_only is True
    assert graph.production_legal_evidence is False
    assert graph.node_counts["MevzuatKurali"] == 7
    assert graph.node_counts["Birim"] == 5
    assert graph.edge_counts["ASSIGNED_TO"] >= 4
    assert {item.role for item in graph.inputs} == {
        "gold_dataset",
        "legislation",
        "units",
    }
    assert all(len(item.sha256) == 64 for item in graph.inputs)
    assert all(not Path(item.path).is_absolute() for item in graph.inputs)
    assert next(
        item for item in graph.inputs if item.role == "gold_dataset"
    ).version == "1.0.0"
    assert all(edge.evidence_record_ids for edge in graph.edges)
    node_ids = {node.node_id for node in graph.nodes}
    assert all(
        edge.source_id in node_ids and edge.target_id in node_ids
        for edge in graph.edges
    )


def test_rule_trace_exposes_rule_to_unit_and_template_paths() -> None:
    graph = _build()

    trace = graph.trace_rule("rule:SENT-KRY-003", max_hops=2)

    assert "unit:ORKGM-AF-001" in trace.reached_node_ids
    assert "template:ust_yazi_v1" in trace.reached_node_ids
    assert "HASAR-08" in trace.evidence_record_ids
    assert any("ASSIGNED_TO" in path for path in trace.paths)
    assert any("SUPPORTS_TEMPLATE" in path for path in trace.paths)


def test_graph_builder_rejects_non_synthetic_legislation(tmp_path: Path) -> None:
    source = json.loads(
        (PROJECT_ROOT / "data" / "synthetic_legislation.json").read_text(
            encoding="utf-8"
        )
    )
    source["dataset_name"] = "Üretim mevzuatı"
    source["usage"] = "üretim"
    source_path = tmp_path / "legislation.json"
    source_path.write_text(json.dumps(source), encoding="utf-8")

    with pytest.raises(GraphBuildError, match="sentetik"):
        EvidenceGraphBuilder().build(
            dataset_path=PROJECT_ROOT / "data" / "synthetic_gold.json",
            legislation_path=source_path,
            units_path=PROJECT_ROOT / "data" / "synthetic_units.json",
        )


def test_graph_write_round_trips(tmp_path: Path) -> None:
    graph = _build()
    output = EvidenceGraphBuilder.write(graph, tmp_path / "graph.json")

    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["graph_id"] == "benchmark_synthetic_evidence_graph_v1"
    assert payload["production_legal_evidence"] is False
    assert payload["schema_version"] == "1.1"
    assert len(payload["inputs"]) == 3


@pytest.mark.parametrize("count_field", ["node_counts", "edge_counts"])
def test_graph_rejects_tampered_summary_counts(count_field: str) -> None:
    payload = _build().model_dump(mode="json")
    first_key = next(iter(payload[count_field]))
    payload[count_field][first_key] += 1

    with pytest.raises(ValidationError, match="yeniden hesaplanan"):
        EvidenceGraph.model_validate(payload)
