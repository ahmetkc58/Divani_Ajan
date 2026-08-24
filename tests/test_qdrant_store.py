from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import UUID

import pytest

import karayol_agent.retrieval.qdrant_store as qdrant_store_module
from karayol_agent.retrieval.corpus import build_corpus_binding
from karayol_agent.retrieval.contracts import (
    COMPETITION_SNAPSHOT_NOTICE,
    COMPETITION_SNAPSHOT_STATUS,
    CorpusMode,
)
from karayol_agent.retrieval.qdrant_store import (
    DEFAULT_COMPETITION_SNAPSHOT_COLLECTION_NAME,
    PAYLOAD_INDEXES,
    QdrantStore,
    QdrantUnavailable,
    SchemaMismatch,
    stable_point_id,
)
from karayol_agent.schemas import LegislationChunk


def _value(value: Any, key: str) -> Any:
    if isinstance(value, dict):
        return value.get(key)
    return getattr(value, key, None)


def _normalized_enum(value: Any) -> str:
    return str(getattr(value, "value", value)).lower()


class FakeQdrantClient:
    def __init__(self) -> None:
        self.collections: dict[str, Any] = {}
        self.create_calls: list[dict[str, Any]] = []
        self.index_calls: list[dict[str, Any]] = []
        self.upsert_calls: list[dict[str, Any]] = []
        self.query_calls: list[dict[str, Any]] = []
        self.query_results: list[Any] = []
        self.points: dict[str, dict[str, Any]] = {}
        self.raise_on_query: Exception | None = None

    def collection_exists(self, collection_name: str) -> bool:
        return collection_name in self.collections

    def create_collection(
        self, *, collection_name: str, vectors_config: Any
    ) -> None:
        self.create_calls.append(
            {
                "collection_name": collection_name,
                "vectors_config": vectors_config,
            }
        )
        self.collections[collection_name] = SimpleNamespace(
            config=SimpleNamespace(
                params=SimpleNamespace(vectors=vectors_config)
            ),
            payload_schema={},
        )

    def get_collection(self, collection_name: str) -> Any:
        return self.collections[collection_name]

    def create_payload_index(
        self,
        *,
        collection_name: str,
        field_name: str,
        field_schema: Any,
        wait: bool,
    ) -> None:
        self.index_calls.append(
            {
                "collection_name": collection_name,
                "field_name": field_name,
                "field_schema": field_schema,
                "wait": wait,
            }
        )
        self.collections[collection_name].payload_schema[field_name] = (
            SimpleNamespace(data_type=field_schema)
        )

    def upsert(
        self, *, collection_name: str, points: list[Any], wait: bool
    ) -> Any:
        self.upsert_calls.append(
            {
                "collection_name": collection_name,
                "points": points,
                "wait": wait,
            }
        )
        collection_points = self.points.setdefault(collection_name, {})
        for point in points:
            collection_points[str(_value(point, "id"))] = point
        return SimpleNamespace(status="completed")

    def count(
        self,
        *,
        collection_name: str,
        count_filter: Any | None,
        exact: bool,
    ) -> Any:
        assert exact is True
        points = list(self.points.get(collection_name, {}).values())
        if count_filter is not None:
            conditions = _value(count_filter, "must") or []

            def matches(point: Any) -> bool:
                payload = _value(point, "payload") or {}
                for condition in conditions:
                    key = _value(condition, "key")
                    match = _value(condition, "match")
                    allowed = _value(match, "any")
                    if allowed is not None and payload.get(key) not in allowed:
                        return False
                    if allowed is None and payload.get(key) != _value(match, "value"):
                        return False
                return True

            points = [point for point in points if matches(point)]
        return SimpleNamespace(count=len(points))

    def query_points(self, **kwargs: Any) -> Any:
        if self.raise_on_query is not None:
            raise self.raise_on_query
        self.query_calls.append(kwargs)
        return SimpleNamespace(points=self.query_results)


def _store(client: FakeQdrantClient, **kwargs: Any) -> QdrantStore:
    store = QdrantStore(client=client, **kwargs)
    # Force the dependency-free compatibility request objects even on a machine
    # where qdrant-client happens to be installed.
    store._models_checked = True
    store._models_module = None
    return store


def _approved_chunk(
    *,
    chunk_id: str = "MEV-TEST-001",
    domain: str = "kgm_infrastructure",
) -> LegislationChunk:
    return LegislationChunk(
        chunk_id=chunk_id,
        document_id="UAB-TEST-001",
        title="Karayolu Test Yönetmeliği",
        section="Birinci Bölüm",
        article="Madde 7",
        paragraph="2",
        clause="a",
        text="Yol bakım güvenliği için gerekli tedbirler alınır.",
        source="resources/official/test.pdf",
        source_sha256="a" * 64,
        source_kind="public_legislation",
        page=14,
        page_end=14,
        source_url="https://example.test/test.pdf",
        document_type="yonetmelik",
        domain=domain,
        subdomain="traffic_safety",
        validity_status="verified",
        approved_for_active_rag=True,
        ocr_status="text_layer_available",
        context_text="Yönetmelik > Birinci Bölüm > Madde 7",
        status="verified",
        tags=["trafik güvenliği"],
    )


def _snapshot_chunk(
    *,
    chunk_id: str = "MEV-SNAPSHOT-001",
    domain: str = "official_writing",
) -> LegislationChunk:
    return LegislationChunk(
        chunk_id=chunk_id,
        document_id="official-writing-regulation",
        title="Resmî Yazışma Yönetmeliği",
        section="Birinci Bölüm",
        article="Madde 1",
        text="Bu sabit yarışma snapshot metnidir.",
        source="mevzuat-1.pdf",
        source_sha256="b" * 64,
        source_kind=CorpusMode.COMPETITION_SNAPSHOT.value,
        page=1,
        page_end=1,
        source_url=None,
        document_type="yonetmelik",
        domain=domain,
        subdomain="formal_correspondence",
        validity_status="needs_verification",
        approved_for_active_rag=False,
        ocr_status="ocr_candidate_unverified",
        context_text="Resmî Yazışma Yönetmeliği > Madde 1 > Sayfa 1",
        status=COMPETITION_SNAPSHOT_STATUS,
        tags=["yarışma snapshot"],
    )


def _bind(store: QdrantStore, *chunks: LegislationChunk) -> QdrantStore:
    store.bind_corpus(build_corpus_binding(chunks))
    return store


def test_ensure_collection_creates_cosine_1024_schema_and_plan_indexes() -> None:
    client = FakeQdrantClient()
    store = _store(client)

    assert store.ensure_collection() is True
    assert client.create_calls[0]["collection_name"] == "legal_chunks_v1"
    vector_config = client.create_calls[0]["vectors_config"]
    assert _value(vector_config, "size") == 1024
    assert _normalized_enum(_value(vector_config, "distance")) == "cosine"
    assert {
        call["field_name"]: _normalized_enum(call["field_schema"])
        for call in client.index_calls
    } == PAYLOAD_INDEXES
    assert all(call["wait"] is True for call in client.index_calls)

    assert store.ensure_collection() is False
    assert len(client.create_calls) == 1
    assert len(client.index_calls) == len(PAYLOAD_INDEXES)


@pytest.mark.parametrize(
    ("size", "distance", "message"),
    [(768, "Cosine", "vektör boyutu"), (1024, "Dot", "uzaklık metriği")],
)
def test_existing_collection_schema_mismatch_is_explicit(
    size: int, distance: str, message: str
) -> None:
    client = FakeQdrantClient()
    client.collections["legal_chunks_v1"] = SimpleNamespace(
        config=SimpleNamespace(
            params=SimpleNamespace(
                vectors=SimpleNamespace(size=size, distance=distance)
            )
        ),
        payload_schema={},
    )

    with pytest.raises(SchemaMismatch, match=message):
        _store(client).ensure_collection()


def test_existing_payload_index_type_mismatch_is_explicit() -> None:
    client = FakeQdrantClient()
    vector_config = SimpleNamespace(size=1024, distance="Cosine")
    client.collections["legal_chunks_v1"] = SimpleNamespace(
        config=SimpleNamespace(
            params=SimpleNamespace(vectors=vector_config)
        ),
        payload_schema={
            "approved_for_active_rag": SimpleNamespace(data_type="keyword")
        },
    )

    with pytest.raises(SchemaMismatch, match="approved_for_active_rag"):
        _store(client).ensure_collection()


def test_dense_search_does_not_create_a_missing_collection() -> None:
    client = FakeQdrantClient()
    store = _bind(_store(client), _approved_chunk())

    with pytest.raises(QdrantUnavailable, match="index-vectors"):
        store.dense_search([0.0] * 1024, domain="kgm_infrastructure")

    assert client.create_calls == []


def test_readiness_requires_exact_bound_corpus_and_model_metadata() -> None:
    client = FakeQdrantClient()
    chunk = _approved_chunk()
    store = _bind(_store(client), chunk)
    store.upsert([chunk], [[0.125] * 1024])

    report = store.validate_readiness()

    assert report.expected_point_count == 1
    assert report.total_point_count == 1
    assert report.compatible_point_count == 1
    assert report.corpus_fingerprint == store.corpus_fingerprint
    assert report.storage_mode == "server"
    assert report.payload_indexes_enforced is True
    assert "doğrulandı" in report.payload_index_detail

    point = next(iter(client.points[store.collection_name].values()))
    _value(point, "payload")["embedding_model"] = "stale-model"
    with pytest.raises(SchemaMismatch, match="uyumlu nokta sayısı yetersiz"):
        store.validate_readiness()


def test_embedded_mode_skips_unsupported_indexes_but_keeps_readiness_checks(
    tmp_path: Path,
) -> None:
    client = FakeQdrantClient()
    chunk = _approved_chunk()
    store = _bind(_store(client, path=tmp_path / "qdrant-local"), chunk)

    store.upsert([chunk], [[0.125] * 1024])
    report = store.validate_readiness()

    assert client.index_calls == []
    assert report.storage_mode == "embedded_local"
    assert report.payload_indexes_enforced is False
    assert "desteklemez" in report.payload_index_detail
    assert report.total_point_count == 1
    assert report.compatible_point_count == 1

    point = next(iter(client.points[store.collection_name].values()))
    _value(point, "payload")["index_version"] = "stale-index"
    with pytest.raises(SchemaMismatch, match="uyumlu nokta sayısı yetersiz"):
        store.validate_readiness()


def test_embedded_local_qdrant_persists_across_client_reopen(
    tmp_path: Path,
) -> None:
    pytest.importorskip("qdrant_client")
    qdrant_path = tmp_path / "persistent-qdrant"
    chunk = _approved_chunk()

    first = _bind(
        QdrantStore(path=qdrant_path, embedding_dimension=4),
        chunk,
    )
    try:
        assert first.upsert([chunk], [[0.25] * 4]) == 1
        assert first.validate_readiness().compatible_point_count == 1
    finally:
        first.close()

    reopened = _bind(
        QdrantStore(path=qdrant_path, embedding_dimension=4),
        chunk,
    )
    try:
        report = reopened.validate_readiness()
        hits = reopened.dense_search(
            [0.25] * 4,
            domain=chunk.domain,
            limit=1,
        )
    finally:
        reopened.close()

    assert report.storage_mode == "embedded_local"
    assert report.payload_indexes_enforced is False
    assert [hit.chunk.chunk_id for hit in hits] == [chunk.chunk_id]


def test_stable_point_id_preserves_uuid_and_hashes_project_chunk_id() -> None:
    existing_uuid = "a67e8ce7-ef28-48fc-a09f-576dba397aec"

    assert stable_point_id(existing_uuid) == existing_uuid
    assert stable_point_id("MEV-TEST-001") == stable_point_id("MEV-TEST-001")
    assert stable_point_id("MEV-TEST-001") != stable_point_id("MEV-TEST-002")
    UUID(stable_point_id("MEV-TEST-001"))


def test_upsert_writes_stable_id_plan_payload_and_version_metadata() -> None:
    client = FakeQdrantClient()
    store = _store(client)
    chunk = _approved_chunk()
    _bind(store, chunk)

    assert store.upsert([chunk], [[0.125] * 1024]) == 1

    point = client.upsert_calls[0]["points"][0]
    payload = _value(point, "payload")
    assert _value(point, "id") == stable_point_id(chunk.chunk_id)
    assert len(_value(point, "vector")) == 1024
    assert payload["chunk_id"] == chunk.chunk_id
    assert payload["source_path"] == chunk.source
    assert payload["original_text"] == chunk.text
    assert payload["embedding_model"] == "jinaai/jina-embeddings-v3"
    assert payload["embedding_dimension"] == 1024
    assert payload["embedding_task"] == "retrieval.passage"
    assert payload["index_version"] == "1.0"
    assert payload["corpus_fingerprint"] == store.corpus_fingerprint
    assert payload["chunk_fingerprint"] == (
        store.corpus_binding.expected_chunk_fingerprint(chunk.chunk_id)
    )


def test_build_payload_rejects_changed_content_under_an_allowed_chunk_id() -> None:
    store = _store(FakeQdrantClient())
    chunk = _approved_chunk()
    _bind(store, chunk)

    with pytest.raises(SchemaMismatch, match="içeriği bağlı corpus ile uyuşmuyor"):
        store.build_payload(chunk.model_copy(update={"text": "Değiştirilmiş hüküm."}))


def test_payload_persists_and_search_validates_pinned_jina_revisions() -> None:
    client = FakeQdrantClient()
    store = _store(
        client,
        embedding_model_revision="weights-commit",
        embedding_code_revision="code-commit",
    )
    chunk = _approved_chunk()
    _bind(store, chunk)
    payload = store.build_payload(chunk)

    assert payload["embedding_model_revision"] == "weights-commit"
    assert payload["embedding_code_revision"] == "code-commit"

    store.ensure_collection()
    payload["embedding_code_revision"] = "different-code"
    client.query_results = [SimpleNamespace(score=0.8, payload=payload)]
    with pytest.raises(SchemaMismatch, match="embedding sözleşmesi uyuşmuyor"):
        store.dense_search([0.0] * 1024, domain="kgm_infrastructure")


def test_upsert_rejects_wrong_task_dimension_and_unapproved_chunk() -> None:
    store = _store(FakeQdrantClient())
    chunk = _approved_chunk()
    _bind(store, chunk)

    with pytest.raises(SchemaMismatch, match="yanlış görev"):
        store.upsert([chunk], [[0.0] * 1024], embedding_task="retrieval.query")
    with pytest.raises(SchemaMismatch, match="Embedding boyutu"):
        store.upsert([chunk], [[0.0] * 3])
    with pytest.raises(SchemaMismatch, match="aktif Qdrant indeksine alınamaz"):
        store.upsert(
            [chunk.model_copy(update={"approved_for_active_rag": False})],
            [[0.0] * 1024],
        )


@pytest.mark.parametrize(
    "update",
    [
        {"source_kind": "synthetic"},
        {"ocr_status": "needs_ocr"},
        {"source_sha256": None},
        {"document_id": None},
        {"page": None},
        {"domain": "unknown"},
    ],
)
def test_active_index_reuses_full_public_repository_gate(
    update: dict[str, Any],
) -> None:
    store = _store(FakeQdrantClient())
    _bind(store, _approved_chunk())

    with pytest.raises(SchemaMismatch, match="aktif Qdrant indeksine alınamaz"):
        store.build_payload(_approved_chunk().model_copy(update=update))


def test_dense_search_always_sends_fail_closed_filters_and_returns_search_hits() -> None:
    client = FakeQdrantClient()
    store = _store(client)
    active_chunk = _approved_chunk()
    wrong_domain_chunk = _approved_chunk(
        chunk_id="MEV-TEST-002", domain="road_transport"
    )
    _bind(store, active_chunk, wrong_domain_chunk)
    store.ensure_collection()
    active_payload = store.build_payload(active_chunk)
    wrong_domain_payload = store.build_payload(wrong_domain_chunk)
    client.query_results = [
        SimpleNamespace(id="1", score=0.91, payload=active_payload),
        # The local boundary must also reject a result if a server/proxy ignores
        # the mandatory domain filter.
        SimpleNamespace(id="2", score=0.99, payload=wrong_domain_payload),
    ]

    hits = store.dense_search(
        [0.25] * 1024,
        domain="kgm_infrastructure",
        limit=20,
    )

    query = client.query_calls[0]
    conditions = {
        _value(condition, "key"): _value(_value(condition, "match"), "value")
        for condition in _value(query["query_filter"], "must")
        if _value(condition, "key") != "chunk_id"
    }
    assert conditions == {
        "approved_for_active_rag": True,
        "validity_status": "verified",
        "source_kind": "public_legislation",
        "corpus_mode": CorpusMode.VERIFIED_PUBLIC.value,
        "currentness_verified": True,
        "legal_reliance_allowed": True,
        "domain": "kgm_infrastructure",
        "corpus_fingerprint": store.corpus_fingerprint,
    }
    chunk_id_condition = next(
        condition
        for condition in _value(query["query_filter"], "must")
        if _value(condition, "key") == "chunk_id"
    )
    assert set(_value(_value(chunk_id_condition, "match"), "any")) == {
        "MEV-TEST-001",
        "MEV-TEST-002",
    }
    assert query["with_payload"] is True
    assert query["with_vectors"] is False
    assert [hit.chunk.chunk_id for hit in hits] == ["MEV-TEST-001"]
    assert hits[0].score == 0.91
    assert hits[0].matched_terms == []


def test_snapshot_store_requires_separate_collection_name() -> None:
    with pytest.raises(ValueError, match="public koleksiyon"):
        _store(
            FakeQdrantClient(),
            corpus_mode=CorpusMode.COMPETITION_SNAPSHOT,
        )


def test_snapshot_payload_search_and_readiness_preserve_safety_contract() -> None:
    client = FakeQdrantClient()
    chunk = _snapshot_chunk()
    store = _bind(
        _store(
            client,
            corpus_mode=CorpusMode.COMPETITION_SNAPSHOT,
            collection_name=DEFAULT_COMPETITION_SNAPSHOT_COLLECTION_NAME,
        ),
        chunk,
    )

    assert store.upsert([chunk], [[0.125] * 1024]) == 1
    payload = store.build_payload(chunk)
    client.query_results = [SimpleNamespace(score=0.87, payload=payload)]
    hits = store.dense_search(
        [0.125] * 1024,
        domain="official_writing",
        limit=1,
    )
    report = store.validate_readiness()

    assert [hit.chunk.chunk_id for hit in hits] == [chunk.chunk_id]
    assert payload["corpus_mode"] == CorpusMode.COMPETITION_SNAPSHOT.value
    assert payload["currentness_verified"] is False
    assert payload["legal_reliance_allowed"] is False
    assert payload["usage_notice"] == COMPETITION_SNAPSHOT_NOTICE
    assert report.corpus_mode == CorpusMode.COMPETITION_SNAPSHOT.value
    assert report.currentness_verified is False
    assert report.legal_reliance_allowed is False
    assert report.usage_notice == COMPETITION_SNAPSHOT_NOTICE

    conditions = {
        _value(condition, "key"): _value(_value(condition, "match"), "value")
        for condition in _value(client.query_calls[0]["query_filter"], "must")
        if _value(condition, "key") != "chunk_id"
    }
    assert conditions["approved_for_active_rag"] is False
    assert conditions["validity_status"] == "needs_verification"
    assert conditions["source_kind"] == CorpusMode.COMPETITION_SNAPSHOT.value
    assert conditions["status"] == COMPETITION_SNAPSHOT_STATUS
    assert conditions["currentness_verified"] is False
    assert conditions["legal_reliance_allowed"] is False


def test_dense_search_requires_domain_query_task_and_matching_payload_metadata() -> None:
    client = FakeQdrantClient()
    store = _store(client)

    with pytest.raises(ValueError, match="domain filtresi zorunludur"):
        store.dense_search([0.0] * 1024, domain="unknown")
    with pytest.raises(SchemaMismatch, match="Sorgu vektörü yanlış görev"):
        store.dense_search(
            [0.0] * 1024,
            domain="kgm_infrastructure",
            embedding_task="retrieval.passage",
        )

    chunk = _approved_chunk()
    _bind(store, chunk)
    store.ensure_collection()
    payload = store.build_payload(chunk)
    payload["embedding_model"] = "different-model"
    client.query_results = [SimpleNamespace(score=0.8, payload=payload)]
    with pytest.raises(SchemaMismatch, match="embedding sözleşmesi uyuşmuyor"):
        store.dense_search([0.0] * 1024, domain="kgm_infrastructure")


def test_dense_search_rejects_tampered_payload_with_current_corpus_identity() -> None:
    client = FakeQdrantClient()
    chunk = _approved_chunk()
    store = _bind(_store(client), chunk)
    store.ensure_collection()
    payload = store.build_payload(chunk)
    payload["original_text"] = "Kimliği korunmuş gibi gösterilen değiştirilmiş hüküm."
    client.query_results = [SimpleNamespace(score=0.9, payload=payload)]

    with pytest.raises(SchemaMismatch, match="payload içeriği bağlı corpus"):
        store.dense_search([0.0] * 1024, domain="kgm_infrastructure")


def test_client_import_is_lazy_and_missing_dependency_is_explicit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = QdrantStore()

    def missing_dependency(name: str) -> Any:
        raise ImportError(name)

    monkeypatch.setattr(qdrant_store_module, "import_module", missing_dependency)
    with pytest.raises(QdrantUnavailable, match="qdrant-client"):
        _ = store.client


def test_client_query_failure_is_wrapped_as_qdrant_unavailable() -> None:
    client = FakeQdrantClient()
    client.raise_on_query = OSError("connection refused")
    store = _store(client)
    _bind(store, _approved_chunk())
    store.ensure_collection()

    with pytest.raises(QdrantUnavailable, match="dense araması başarısız"):
        store.dense_search([0.0] * 1024, domain="kgm_infrastructure")


def test_store_fails_closed_without_corpus_binding() -> None:
    store = _store(FakeQdrantClient())

    with pytest.raises(SchemaMismatch, match="corpus binding"):
        store.build_payload(_approved_chunk())
    with pytest.raises(SchemaMismatch, match="corpus binding"):
        store.dense_search([0.0] * 1024, domain="kgm_infrastructure")


def test_dense_search_rejects_stale_point_from_old_corpus() -> None:
    client = FakeQdrantClient()
    old_chunk = _approved_chunk(chunk_id="MEV-OLD-001")
    old_store = _bind(_store(client), old_chunk)
    old_payload = old_store.build_payload(old_chunk)

    current_chunk = _approved_chunk(chunk_id="MEV-CURRENT-001")
    current_store = _bind(_store(client), current_chunk)
    current_store.ensure_collection()
    client.query_results = [SimpleNamespace(score=0.99, payload=old_payload)]

    hits = current_store.dense_search(
        [0.1] * 1024,
        domain="kgm_infrastructure",
    )

    assert hits == []
    query_filter = client.query_calls[-1]["query_filter"]
    conditions = _value(query_filter, "must")
    fingerprint_condition = next(
        condition
        for condition in conditions
        if _value(condition, "key") == "corpus_fingerprint"
    )
    assert _value(_value(fingerprint_condition, "match"), "value") == (
        current_store.corpus_fingerprint
    )
