from __future__ import annotations

import json
from collections import Counter, defaultdict, deque
from datetime import datetime
from hashlib import sha256
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError, model_validator

from karayol_agent.evaluation.models import GoldDataset
from karayol_agent.schemas import utc_now


class GraphBuildError(RuntimeError):
    """The synthetic evidence graph cannot be built without losing provenance."""


NodeType = Literal[
    "MevzuatKurali",
    "Birim",
    "EvrakTuru",
    "YaziSablonu",
    "ZorunluAlan",
]
RelationType = Literal[
    "APPLIES_TO",
    "ASSIGNED_TO",
    "REQUIRES_FIELD",
    "SUPPORTS_TEMPLATE",
]
GraphInputRole = Literal["gold_dataset", "legislation", "units"]


class GraphInput(BaseModel):
    """Portable, content-addressed provenance for one graph input."""

    role: GraphInputRole
    path: str = Field(min_length=1)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    dataset_name: str = Field(min_length=1)
    version: str | None = None


class EvidenceNode(BaseModel):
    node_id: str = Field(min_length=1)
    node_type: NodeType
    label: str = Field(min_length=1)
    description: str | None = None
    properties: dict[str, Any] = Field(default_factory=dict)
    provenance_ids: list[str] = Field(default_factory=list)


class EvidenceEdge(BaseModel):
    edge_id: str = Field(min_length=1)
    source_id: str = Field(min_length=1)
    target_id: str = Field(min_length=1)
    relation: RelationType
    evidence_record_ids: list[str] = Field(min_length=1)


class RuleTrace(BaseModel):
    rule_id: str
    reached_node_ids: list[str]
    paths: list[list[str]]
    evidence_record_ids: list[str]


class EvidenceGraph(BaseModel):
    schema_version: str = "1.1"
    graph_id: str = "benchmark_synthetic_evidence_graph_v1"
    generated_at: datetime = Field(default_factory=utc_now)
    usage: str
    benchmark_only: Literal[True] = True
    production_legal_evidence: Literal[False] = False
    inputs: list[GraphInput] = Field(min_length=3, max_length=3)
    nodes: list[EvidenceNode]
    edges: list[EvidenceEdge]
    node_counts: dict[str, int]
    edge_counts: dict[str, int]

    @model_validator(mode="after")
    def validate_graph_integrity(self) -> "EvidenceGraph":
        node_ids = [node.node_id for node in self.nodes]
        edge_ids = [edge.edge_id for edge in self.edges]
        if len(node_ids) != len(set(node_ids)):
            raise ValueError("Graf düğüm kimlikleri benzersiz olmalıdır.")
        if len(edge_ids) != len(set(edge_ids)):
            raise ValueError("Graf ilişki kimlikleri benzersiz olmalıdır.")
        known_nodes = set(node_ids)
        dangling = [
            edge.edge_id
            for edge in self.edges
            if edge.source_id not in known_nodes or edge.target_id not in known_nodes
        ]
        if dangling:
            raise ValueError(f"Ucu bulunmayan graf ilişkileri: {dangling}")
        input_roles = [item.role for item in self.inputs]
        expected_roles = {"gold_dataset", "legislation", "units"}
        if set(input_roles) != expected_roles or len(input_roles) != len(set(input_roles)):
            raise ValueError(
                "Graf girdileri gold_dataset, legislation ve units rollerini "
                "tam olarak birer kez içermelidir."
            )
        expected_node_counts = dict(
            sorted(Counter(node.node_type for node in self.nodes).items())
        )
        expected_edge_counts = dict(
            sorted(Counter(edge.relation for edge in self.edges).items())
        )
        if self.node_counts != expected_node_counts:
            raise ValueError(
                "node_counts düğüm listesinden yeniden hesaplanan değerlerle uyuşmuyor."
            )
        if self.edge_counts != expected_edge_counts:
            raise ValueError(
                "edge_counts ilişki listesinden yeniden hesaplanan değerlerle uyuşmuyor."
            )
        return self

    def trace_rule(self, rule_id: str, *, max_hops: int = 2) -> RuleTrace:
        """Return auditable outgoing paths from one synthetic rule node."""

        if max_hops < 1:
            raise ValueError("max_hops en az 1 olmalıdır.")
        known_nodes = {node.node_id for node in self.nodes}
        if rule_id not in known_nodes:
            raise GraphBuildError(f"Graf düğümü bulunamadı: {rule_id}")

        outgoing: dict[str, list[EvidenceEdge]] = defaultdict(list)
        for edge in self.edges:
            outgoing[edge.source_id].append(edge)
        for edges in outgoing.values():
            edges.sort(key=lambda edge: (edge.relation, edge.target_id))

        reached: set[str] = set()
        evidence: set[str] = set()
        paths: list[list[str]] = []
        queue: deque[tuple[str, list[str], int]] = deque([(rule_id, [rule_id], 0)])
        while queue:
            current, path, depth = queue.popleft()
            if depth >= max_hops:
                continue
            for edge in outgoing.get(current, []):
                reached.add(edge.target_id)
                evidence.update(edge.evidence_record_ids)
                next_path = [*path, edge.relation, edge.target_id]
                paths.append(next_path)
                queue.append((edge.target_id, next_path, depth + 1))

        return RuleTrace(
            rule_id=rule_id,
            reached_node_ids=sorted(reached),
            paths=paths,
            evidence_record_ids=sorted(evidence),
        )


class EvidenceGraphBuilder:
    """Build a small, deterministic graph from the frozen synthetic fixtures.

    This builder deliberately rejects inputs that are not explicitly marked as
    synthetic.  It is not an approval bypass for the public-law corpus.
    """

    SYNTHETIC_CHUNK_STATUS = "sentetik_demo_kurali"

    def build(
        self,
        *,
        dataset_path: Path,
        legislation_path: Path,
        units_path: Path,
    ) -> EvidenceGraph:
        dataset_payload = self._load_json(dataset_path)
        legislation_payload = self._load_json(legislation_path)
        units_payload = self._load_json(units_path)
        try:
            dataset = GoldDataset.model_validate(dataset_payload)
        except ValidationError as exc:
            raise GraphBuildError(f"Gold set doğrulanamadı: {exc}") from exc

        self._assert_synthetic_dataset(dataset)
        chunks = self._data_list(legislation_payload, "mevzuat")
        units = self._data_list(units_payload, "birim")
        self._assert_synthetic_legislation(legislation_payload, chunks)
        self._assert_synthetic_units(units_payload)

        chunk_by_id = self._unique_by(chunks, "chunk_id", "mevzuat parçası")
        unit_by_id = self._unique_by(units, "unit_id", "birim")
        nodes: dict[str, EvidenceNode] = {}
        edge_evidence: dict[tuple[str, str, RelationType], set[str]] = defaultdict(set)

        for chunk_id, chunk in chunk_by_id.items():
            node_id = self._node_id("rule", chunk_id)
            nodes[node_id] = EvidenceNode(
                node_id=node_id,
                node_type="MevzuatKurali",
                label=str(chunk.get("section") or chunk.get("article") or chunk_id),
                description=str(chunk.get("text") or ""),
                properties={
                    "chunk_id": chunk_id,
                    "title": chunk.get("title"),
                    "article": chunk.get("article"),
                    "status": chunk.get("status"),
                },
                provenance_ids=[chunk_id],
            )

        for unit_id, unit in unit_by_id.items():
            node_id = self._node_id("unit", unit_id)
            nodes[node_id] = EvidenceNode(
                node_id=node_id,
                node_type="Birim",
                label=str(unit.get("unit_name") or unit_id),
                description=str(unit.get("hierarchy") or ""),
                properties={
                    "unit_id": unit_id,
                    "responsibilities": list(unit.get("responsibilities") or []),
                },
                provenance_ids=[unit_id],
            )

        for record in dataset.data:
            document_type_id = self._node_id("document_type", record.expected_document_type)
            nodes.setdefault(
                document_type_id,
                EvidenceNode(
                    node_id=document_type_id,
                    node_type="EvrakTuru",
                    label=record.expected_document_type,
                    provenance_ids=[record.record_id],
                ),
            )
            self._append_provenance(nodes[document_type_id], record.record_id)

            template_id = self._node_id("template", record.expected_template_id)
            nodes.setdefault(
                template_id,
                EvidenceNode(
                    node_id=template_id,
                    node_type="YaziSablonu",
                    label=record.expected_template_id,
                    provenance_ids=[record.record_id],
                ),
            )
            self._append_provenance(nodes[template_id], record.record_id)
            self._add_edge(
                edge_evidence,
                document_type_id,
                template_id,
                "SUPPORTS_TEMPLATE",
                record.record_id,
            )

            unit_node_id = self._node_id("unit", record.expected_unit_id)
            if record.expected_unit_id not in unit_by_id:
                raise GraphBuildError(
                    f"Gold kaydı bilinmeyen birime işaret ediyor: "
                    f"{record.record_id} -> {record.expected_unit_id}"
                )

            for field_name in record.expected_missing_fields:
                field_id = self._node_id("field", field_name)
                nodes.setdefault(
                    field_id,
                    EvidenceNode(
                        node_id=field_id,
                        node_type="ZorunluAlan",
                        label=field_name,
                        provenance_ids=[record.record_id],
                    ),
                )
                self._append_provenance(nodes[field_id], record.record_id)
                self._add_edge(
                    edge_evidence,
                    document_type_id,
                    field_id,
                    "REQUIRES_FIELD",
                    record.record_id,
                )

            for chunk_id in record.expected_reference_chunk_ids:
                if chunk_id not in chunk_by_id:
                    raise GraphBuildError(
                        f"Gold kaydı bilinmeyen parçaya işaret ediyor: "
                        f"{record.record_id} -> {chunk_id}"
                    )
                rule_node_id = self._node_id("rule", chunk_id)
                self._add_edge(
                    edge_evidence,
                    rule_node_id,
                    document_type_id,
                    "APPLIES_TO",
                    record.record_id,
                )
                self._add_edge(
                    edge_evidence,
                    rule_node_id,
                    unit_node_id,
                    "ASSIGNED_TO",
                    record.record_id,
                )
                self._add_edge(
                    edge_evidence,
                    rule_node_id,
                    template_id,
                    "SUPPORTS_TEMPLATE",
                    record.record_id,
                )

        edges = [
            EvidenceEdge(
                edge_id=self._edge_id(source, relation, target),
                source_id=source,
                target_id=target,
                relation=relation,
                evidence_record_ids=sorted(record_ids),
            )
            for (source, target, relation), record_ids in sorted(
                edge_evidence.items(), key=lambda item: item[0]
            )
        ]
        sorted_nodes = sorted(nodes.values(), key=lambda node: node.node_id)
        for node in sorted_nodes:
            node.provenance_ids = sorted(set(node.provenance_ids))

        node_counts: dict[str, int] = defaultdict(int)
        edge_counts: dict[str, int] = defaultdict(int)
        for node in sorted_nodes:
            node_counts[node.node_type] += 1
        for edge in edges:
            edge_counts[edge.relation] += 1
        return EvidenceGraph(
            usage=(
                "Yalnız dondurulmuş sentetik test verisi; kamu mevzuatı veya "
                "üretim hukuk kanıtı değildir."
            ),
            inputs=[
                self._input_metadata("gold_dataset", dataset_path, dataset_payload),
                self._input_metadata("legislation", legislation_path, legislation_payload),
                self._input_metadata("units", units_path, units_payload),
            ],
            nodes=sorted_nodes,
            edges=edges,
            node_counts=dict(sorted(node_counts.items())),
            edge_counts=dict(sorted(edge_counts.items())),
        )

    @staticmethod
    def write(graph: EvidenceGraph, output_path: Path) -> Path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(graph.model_dump(mode="json"), ensure_ascii=False, indent=2),
            encoding="utf-8",
            newline="\n",
        )
        return output_path

    @staticmethod
    def _input_metadata(
        role: GraphInputRole,
        path: Path,
        payload: dict[str, Any],
    ) -> GraphInput:
        resolved = path.resolve()
        digest = sha256()
        try:
            with resolved.open("rb") as source:
                for block in iter(lambda: source.read(1024 * 1024), b""):
                    digest.update(block)
        except OSError as exc:
            raise GraphBuildError(f"Graf girdisi özetlenemedi ({path}): {exc}") from exc
        return GraphInput(
            role=role,
            path=EvidenceGraphBuilder._portable_path(resolved),
            sha256=digest.hexdigest(),
            dataset_name=str(payload.get("dataset_name") or "").strip(),
            version=(
                str(payload["version"]).strip()
                if payload.get("version") is not None
                else None
            ),
        )

    @staticmethod
    def _portable_path(path: Path) -> str:
        project_root = Path(__file__).resolve().parents[3]
        try:
            return path.relative_to(project_root).as_posix()
        except ValueError:
            # External test fixtures must not leak a workstation/user path into
            # an artifact; the SHA-256 remains the authoritative identity.
            return path.name

    @staticmethod
    def _load_json(path: Path) -> dict[str, Any]:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise GraphBuildError(f"JSON okunamadı ({path}): {exc}") from exc
        if not isinstance(payload, dict):
            raise GraphBuildError(f"JSON kökü nesne olmalıdır: {path}")
        return payload

    @staticmethod
    def _data_list(payload: dict[str, Any], label: str) -> list[dict[str, Any]]:
        data = payload.get("data")
        if not isinstance(data, list) or not data or not all(isinstance(item, dict) for item in data):
            raise GraphBuildError(f"{label} verisi dolu bir data listesi olmalıdır.")
        return data

    @classmethod
    def _assert_synthetic_legislation(
        cls, payload: dict[str, Any], chunks: list[dict[str, Any]]
    ) -> None:
        dataset_name = str(payload.get("dataset_name") or "").casefold()
        if "sentetik" not in dataset_name:
            raise GraphBuildError("Mevzuat girdisi açıkça sentetik olarak işaretlenmemiş.")
        invalid = [
            chunk.get("chunk_id")
            for chunk in chunks
            if chunk.get("status") != cls.SYNTHETIC_CHUNK_STATUS
        ]
        if invalid:
            raise GraphBuildError(f"Sentetik olmayan mevzuat parçaları reddedildi: {invalid}")

    @staticmethod
    def _assert_synthetic_units(payload: dict[str, Any]) -> None:
        if "sentetik" not in str(payload.get("dataset_name") or "").casefold():
            raise GraphBuildError("Birim girdisi açıkça sentetik olarak işaretlenmemiş.")

    @staticmethod
    def _assert_synthetic_dataset(dataset: GoldDataset) -> None:
        named_synthetic = "sentetik" in dataset.dataset_name.casefold()
        every_record_tagged = all(
            "sentetik" in {tag.casefold() for tag in record.tags}
            for record in dataset.data
        )
        if not named_synthetic or not every_record_tagged:
            raise GraphBuildError("Gold set açıkça sentetik olarak işaretlenmemiş.")

    @staticmethod
    def _unique_by(
        records: list[dict[str, Any]], key: str, label: str
    ) -> dict[str, dict[str, Any]]:
        result: dict[str, dict[str, Any]] = {}
        for record in records:
            value = str(record.get(key) or "").strip()
            if not value:
                raise GraphBuildError(f"{label} için {key} boş bırakılamaz.")
            if value in result:
                raise GraphBuildError(f"Yinelenen {label} kimliği: {value}")
            result[value] = record
        return result

    @staticmethod
    def _node_id(kind: str, value: str) -> str:
        return f"{kind}:{value}"

    @staticmethod
    def _edge_id(source: str, relation: str, target: str) -> str:
        return f"{source}|{relation}|{target}"

    @staticmethod
    def _append_provenance(node: EvidenceNode, record_id: str) -> None:
        if record_id not in node.provenance_ids:
            node.provenance_ids.append(record_id)

    @staticmethod
    def _add_edge(
        edge_evidence: dict[tuple[str, str, RelationType], set[str]],
        source: str,
        target: str,
        relation: RelationType,
        record_id: str,
    ) -> None:
        edge_evidence[(source, target, relation)].add(record_id)
