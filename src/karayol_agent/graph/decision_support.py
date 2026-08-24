from __future__ import annotations

import json
from hashlib import sha256
from pathlib import Path

from pydantic import ValidationError

from karayol_agent.graph.evidence_graph import (
    EvidenceGraph,
    EvidenceGraphBuilder,
    GraphBuildError,
)
from karayol_agent.schemas import GraphDecisionTrace, VerifiedReference


SYNTHETIC_GRAPH_WARNING = (
    "Kanıt grafı yalnız dondurulmuş sentetik benchmark verisidir; "
    "güncel kamu mevzuatı veya üretim hukuk kanıtı olarak kullanılamaz."
)


class EvidenceGraphAdvisor:
    """Selective multi-hop advice over the frozen synthetic evidence graph.

    The advisor is deliberately fail-closed: it validates the graph schema and
    every content-addressed input before use, accepts only verified synthetic
    references, and never marks its output as legally reliable.
    """

    def __init__(self, graph: EvidenceGraph) -> None:
        self.graph = graph
        self._nodes = {node.node_id: node for node in graph.nodes}
        self._edges_by_source: dict[str, list] = {}
        for edge in graph.edges:
            self._edges_by_source.setdefault(edge.source_id, []).append(edge)

    @classmethod
    def load(cls, graph_path: Path, *, project_root: Path) -> "EvidenceGraphAdvisor":
        try:
            payload = json.loads(graph_path.read_text(encoding="utf-8"))
            graph = EvidenceGraph.model_validate(payload)
        except (OSError, json.JSONDecodeError, ValidationError) as exc:
            raise GraphBuildError(f"Kanıt grafı yüklenemedi: {exc}") from exc
        input_paths = cls._validate_input_hashes(graph, project_root=project_root)
        cls._validate_deterministic_derivation(graph, input_paths=input_paths)
        return cls(graph)

    @staticmethod
    def _validate_input_hashes(
        graph: EvidenceGraph,
        *,
        project_root: Path,
    ) -> dict[str, Path]:
        root = project_root.resolve()
        resolved_inputs: dict[str, Path] = {}
        for graph_input in graph.inputs:
            relative = Path(graph_input.path)
            if relative.is_absolute():
                raise GraphBuildError(
                    f"Kanıt grafı girdisi taşınabilir göreli yol olmalıdır: {relative}"
                )
            candidate = (root / relative).resolve()
            try:
                candidate.relative_to(root)
            except ValueError as exc:
                raise GraphBuildError(
                    f"Kanıt grafı girdisi proje kökünün dışında: {relative}"
                ) from exc
            digest = sha256()
            try:
                with candidate.open("rb") as source:
                    for block in iter(lambda: source.read(1024 * 1024), b""):
                        digest.update(block)
            except OSError as exc:
                raise GraphBuildError(
                    f"Kanıt grafı girdisi doğrulanamadı ({relative}): {exc}"
                ) from exc
            if digest.hexdigest() != graph_input.sha256:
                raise GraphBuildError(
                    f"Kanıt grafı girdisi SHA-256 ile uyuşmuyor: {relative}"
                )
            resolved_inputs[graph_input.role] = candidate
        return resolved_inputs

    @staticmethod
    def _validate_deterministic_derivation(
        graph: EvidenceGraph,
        *,
        input_paths: dict[str, Path],
    ) -> None:
        rebuilt = EvidenceGraphBuilder().build(
            dataset_path=input_paths["gold_dataset"],
            legislation_path=input_paths["legislation"],
            units_path=input_paths["units"],
        )
        excluded = {"generated_at"}
        actual = graph.model_dump(mode="json", exclude=excluded)
        expected = rebuilt.model_dump(mode="json", exclude=excluded)
        if actual != expected:
            raise GraphBuildError(
                "Kanıt grafı doğrulanmış girdilerden deterministik olarak "
                "yeniden üretilen yapıyla uyuşmuyor."
            )

    def advise(
        self,
        *,
        document_type: str,
        references: list[VerifiedReference],
        synthetic_corpus_allowed: bool,
    ) -> GraphDecisionTrace:
        if not synthetic_corpus_allowed:
            return GraphDecisionTrace(
                strategy="abstained_non_synthetic_corpus",
                graph_id=self.graph.graph_id,
                warning=SYNTHETIC_GRAPH_WARNING,
            )

        document_node_id = f"document_type:{document_type}"
        eligible_chunk_ids = {
            reference.chunk_id
            for reference in references
            if reference.verified and reference.source_kind == "synthetic"
        }
        matched_rules: list[str] = []
        template_ids: set[str] = set()
        unit_ids: set[str] = set()
        required_fields: set[str] = set()
        paths: list[list[str]] = []
        evidence_record_ids: set[str] = set()

        for chunk_id in sorted(eligible_chunk_ids):
            rule_id = f"rule:{chunk_id}"
            outgoing = self._edges_by_source.get(rule_id, [])
            if not any(
                edge.relation == "APPLIES_TO"
                and edge.target_id == document_node_id
                for edge in outgoing
            ):
                continue

            matched_rules.append(rule_id)
            trace = self.graph.trace_rule(rule_id, max_hops=2)
            paths.extend(trace.paths)
            evidence_record_ids.update(trace.evidence_record_ids)

            for edge in outgoing:
                target = self._nodes[edge.target_id]
                if edge.relation == "SUPPORTS_TEMPLATE" and target.node_type == "YaziSablonu":
                    template_ids.add(str(target.properties.get("template_id") or target.label))
                elif edge.relation == "ASSIGNED_TO" and target.node_type == "Birim":
                    unit_ids.add(str(target.properties.get("unit_id") or target.label))

            for edge in self._edges_by_source.get(document_node_id, []):
                target = self._nodes[edge.target_id]
                if edge.relation == "REQUIRES_FIELD" and target.node_type == "ZorunluAlan":
                    required_fields.add(target.label)

        applied = bool(matched_rules)
        return GraphDecisionTrace(
            strategy="selective_multi_hop" if applied else "abstained_no_matching_rule",
            graph_id=self.graph.graph_id,
            applied=applied,
            matched_rule_ids=matched_rules,
            candidate_template_ids=sorted(template_ids),
            candidate_unit_ids=sorted(unit_ids),
            required_fields=sorted(required_fields),
            paths=paths,
            evidence_record_ids=sorted(evidence_record_ids),
            legal_reliance_allowed=False,
            warning=SYNTHETIC_GRAPH_WARNING,
        )
