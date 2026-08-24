from __future__ import annotations

import math
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from importlib import import_module
from pathlib import Path
from typing import Any
from uuid import UUID, uuid5

from pydantic import ValidationError

from karayol_agent.retrieval.corpus import CorpusBinding, chunk_fingerprint
from karayol_agent.retrieval.contracts import (
    COMPETITION_SNAPSHOT_NOTICE,
    COMPETITION_SNAPSHOT_STATUS,
    CorpusMode,
    competition_snapshot_chunk_blockers,
)
from karayol_agent.retrieval.repository import LegislationRepository
from karayol_agent.schemas import LegislationChunk, SearchHit


DEFAULT_COLLECTION_NAME = "legal_chunks_v1"
DEFAULT_COMPETITION_SNAPSHOT_COLLECTION_NAME = "competition_snapshot_chunks_v1"
DEFAULT_EMBEDDING_MODEL = "jinaai/jina-embeddings-v3"
DEFAULT_EMBEDDING_DIMENSION = 1024
DEFAULT_PASSAGE_TASK = "retrieval.passage"
DEFAULT_QUERY_TASK = "retrieval.query"
DEFAULT_INDEX_VERSION = "1.0"
DEFAULT_DISTANCE = "Cosine"

# Qdrant arbitrary strings as point IDs are not portable: the server accepts an
# unsigned integer or a UUID. UUIDv5 keeps the existing, human-readable chunk_id
# in the payload while giving every client/server version a stable point ID.
_POINT_ID_NAMESPACE = UUID("bd612ff0-2b50-5f91-a782-61f306788a6b")

PAYLOAD_INDEXES: dict[str, str] = {
    "domain": "keyword",
    "subdomain": "keyword",
    "validity_status": "keyword",
    "approved_for_active_rag": "bool",
    "document_type": "keyword",
    "document_id": "keyword",
    "chunk_id": "keyword",
    "chunk_fingerprint": "keyword",
    "corpus_fingerprint": "keyword",
    "corpus_mode": "keyword",
    "source_kind": "keyword",
    "status": "keyword",
    "currentness_verified": "bool",
    "legal_reliance_allowed": "bool",
}


class QdrantUnavailable(RuntimeError):
    """Qdrant istemcisi kurulu olmadığında veya sunucuya erişilemediğinde."""


class SchemaMismatch(RuntimeError):
    """Koleksiyon veya kayıt embedding sözleşmesi beklenenden farklı olduğunda."""


QdrantUnavailableError = QdrantUnavailable
QdrantSchemaMismatch = SchemaMismatch


@dataclass(frozen=True, slots=True)
class QdrantReadinessReport:
    """Read-only proof that a collection matches the active corpus contract."""

    collection_name: str
    expected_point_count: int
    total_point_count: int
    compatible_point_count: int
    corpus_fingerprint: str
    embedding_model: str
    embedding_dimension: int
    index_version: str
    storage_mode: str
    payload_indexes_enforced: bool
    payload_index_detail: str
    corpus_mode: str
    currentness_verified: bool
    legal_reliance_allowed: bool
    usage_notice: str | None


@dataclass(frozen=True, slots=True)
class _CompatVectorParams:
    size: int
    distance: str


@dataclass(frozen=True, slots=True)
class _CompatMatchValue:
    value: Any


@dataclass(frozen=True, slots=True)
class _CompatFieldCondition:
    key: str
    match: Any


@dataclass(frozen=True, slots=True)
class _CompatMatchAny:
    any: list[str]


@dataclass(frozen=True, slots=True)
class _CompatFilter:
    must: list[_CompatFieldCondition]


@dataclass(frozen=True, slots=True)
class _CompatPointStruct:
    id: str
    vector: list[float]
    payload: dict[str, Any]


def stable_point_id(chunk_id: str) -> str:
    """Return a deterministic Qdrant-compatible UUID for ``chunk_id``."""

    normalized = chunk_id.strip()
    if not normalized:
        raise ValueError("chunk_id boş olamaz.")
    try:
        return str(UUID(normalized))
    except (ValueError, AttributeError, TypeError):
        return str(uuid5(_POINT_ID_NAMESPACE, normalized))


class QdrantStore:
    """Qdrant adapter for one explicitly selected legal-corpus contract.

    ``qdrant-client`` is imported only when a real client or its request models
    are needed. Offline tests can inject a duck-typed client with no dependency.
    Verified-public and non-current competition snapshots use distinct trust
    filters and collection names; synthetic benchmark storage is separate.
    """

    def __init__(
        self,
        client: Any | None = None,
        *,
        url: str = "http://localhost:6333",
        path: str | Path | None = None,
        api_key: str | None = None,
        timeout: float = 10.0,
        prefer_grpc: bool = False,
        collection_name: str = DEFAULT_COLLECTION_NAME,
        embedding_model: str = DEFAULT_EMBEDDING_MODEL,
        embedding_dimension: int = DEFAULT_EMBEDDING_DIMENSION,
        embedding_model_revision: str | None = None,
        embedding_code_revision: str | None = None,
        passage_task: str = DEFAULT_PASSAGE_TASK,
        query_task: str = DEFAULT_QUERY_TASK,
        index_version: str = DEFAULT_INDEX_VERSION,
        corpus_mode: CorpusMode | str = CorpusMode.VERIFIED_PUBLIC,
    ) -> None:
        if not collection_name.strip():
            raise ValueError("collection_name boş olamaz.")
        if embedding_dimension < 1:
            raise ValueError("embedding_dimension pozitif olmalıdır.")
        if not all(
            value.strip()
            for value in (embedding_model, passage_task, query_task, index_version)
        ):
            raise ValueError("Embedding model, görev ve indeks sürümü boş olamaz.")
        for field_name, revision in (
            ("embedding_model_revision", embedding_model_revision),
            ("embedding_code_revision", embedding_code_revision),
        ):
            if revision is not None and not revision.strip():
                raise ValueError(f"{field_name} boş bir değer olamaz.")

        normalized_path: Path | None = None
        if path is not None:
            if not str(path).strip():
                raise ValueError("Qdrant yerel depolama yolu boş olamaz.")
            normalized_path = Path(path).resolve()

        normalized_corpus_mode = CorpusMode(corpus_mode)
        if normalized_corpus_mode == CorpusMode.TRUSTED_SYNTHETIC:
            raise ValueError(
                "Production QdrantStore trusted_synthetic corpus kabul etmez."
            )
        if (
            normalized_corpus_mode == CorpusMode.COMPETITION_SNAPSHOT
            and collection_name == DEFAULT_COLLECTION_NAME
        ):
            raise ValueError(
                "Yarışma snapshot'ı public koleksiyon adıyla indekslenemez; "
                f"{DEFAULT_COMPETITION_SNAPSHOT_COLLECTION_NAME!r} kullanın."
            )

        self._client = client
        self.url = url
        self.path = normalized_path
        self.api_key = api_key
        self.timeout = timeout
        self.prefer_grpc = prefer_grpc
        self.collection_name = collection_name
        self.embedding_model = embedding_model
        self.embedding_dimension = embedding_dimension
        self.embedding_model_revision = (
            embedding_model_revision.strip()
            if embedding_model_revision is not None
            else None
        )
        self.embedding_code_revision = (
            embedding_code_revision.strip()
            if embedding_code_revision is not None
            else None
        )
        self.passage_task = passage_task
        self.query_task = query_task
        self.index_version = index_version
        self.corpus_mode = normalized_corpus_mode
        self._corpus_binding: CorpusBinding | None = None
        self._models_module: Any | None = None
        self._models_checked = False

    @property
    def corpus_binding(self) -> CorpusBinding | None:
        return self._corpus_binding

    @property
    def is_corpus_bound(self) -> bool:
        return self._corpus_binding is not None

    @property
    def corpus_fingerprint(self) -> str | None:
        binding = self._corpus_binding
        return binding.fingerprint if binding is not None else None

    @property
    def allowed_chunk_ids(self) -> frozenset[str]:
        binding = self._require_corpus_binding()
        return binding.allowed_chunk_ids

    @property
    def storage_mode(self) -> str:
        """Return the explicit Qdrant persistence mode for diagnostics."""

        return "embedded_local" if self.path is not None else "server"

    @property
    def payload_indexes_enforced(self) -> bool:
        """Whether Qdrant can create and report the required payload indexes.

        Embedded qdrant-client storage persists points and evaluates filters,
        but its payload-index API is intentionally a no-op.  Server mode keeps
        the strict payload-index contract; embedded mode reports the limitation
        rather than pretending to provide server parity.
        """

        return self.path is None

    def bind_corpus(self, binding: CorpusBinding) -> None:
        """Bind this store instance to one immutable exact-corpus contract."""

        if not isinstance(binding, CorpusBinding):
            raise TypeError("binding bir CorpusBinding olmalıdır.")
        if self._corpus_binding is not None and self._corpus_binding != binding:
            raise SchemaMismatch(
                "Qdrant store zaten farklı bir corpus fingerprint/ID sözleşmesine bağlı."
            )
        self._corpus_binding = binding

    @property
    def client(self) -> Any:
        """Return the injected client or lazily construct ``QdrantClient``."""

        if self._client is not None:
            return self._client
        try:
            module = import_module("qdrant_client")
            client_type = getattr(module, "QdrantClient")
        except (ImportError, AttributeError) as exc:
            raise QdrantUnavailable(
                "Qdrant kullanılamıyor: 'qdrant-client' paketi kurulu değil."
            ) from exc

        if self.path is not None:
            kwargs: dict[str, Any] = {"path": str(self.path)}
            target = str(self.path)
        else:
            kwargs = {
                "url": self.url,
                "timeout": self.timeout,
                "prefer_grpc": self.prefer_grpc,
            }
            if self.api_key is not None:
                kwargs["api_key"] = self.api_key
            target = self.url
        try:
            self._client = client_type(**kwargs)
        except Exception as exc:  # pragma: no cover - qdrant-client specific
            raise QdrantUnavailable(
                f"Qdrant istemcisi oluşturulamadı ({target})."
            ) from exc
        return self._client

    def close(self) -> None:
        """Close an already-created client without triggering lazy creation."""

        client = self._client
        self._client = None
        close = getattr(client, "close", None)
        if callable(close):
            close()

    def ensure_collection(self) -> bool:
        """Create the collection/indexes or validate the existing schema."""

        client = self.client
        info = self._get_collection_info(client)
        created = info is None
        if created:
            if not hasattr(client, "create_collection"):
                raise QdrantUnavailable(
                    "Qdrant istemcisi create_collection işlemini desteklemiyor."
                )
            try:
                client.create_collection(
                    collection_name=self.collection_name,
                    vectors_config=self._vector_params(),
                )
            except Exception as exc:
                raise QdrantUnavailable(
                    f"Qdrant koleksiyonu oluşturulamadı: {self.collection_name}."
                ) from exc
        else:
            self._validate_collection_schema(info)

        if self.payload_indexes_enforced:
            self._ensure_payload_indexes(client, None if created else info)
        return created

    def require_collection(self) -> Any:
        """Validate an existing collection without changing Qdrant."""

        info = self._get_collection_info(self.client)
        if info is None:
            raise QdrantUnavailable(
                f"Qdrant koleksiyonu bulunamadı: {self.collection_name}; "
                "önce index-vectors komutunu çalıştırın."
            )
        self._validate_collection_schema(info)
        if self.payload_indexes_enforced:
            self._validate_payload_indexes(info)
        return info

    def validate_readiness(self) -> QdrantReadinessReport:
        """Validate schema, indexes, counts, corpus and embedding metadata."""

        binding = self._require_corpus_binding()
        self.require_collection()
        expected_count = len(binding.chunk_ids)
        if expected_count < 1:
            raise SchemaMismatch("Bağlı aktif corpus boş olamaz.")

        total_count = self._count_points()
        compatible_count = self._count_points(
            count_filter=self._readiness_filter(binding)
        )
        if total_count != expected_count:
            raise SchemaMismatch(
                f"{self.collection_name} nokta sayısı corpus ile uyuşmuyor: "
                f"beklenen={expected_count}, gelen={total_count}."
            )
        if compatible_count != expected_count:
            raise SchemaMismatch(
                f"{self.collection_name} içinde corpus/model/index sözleşmesiyle "
                f"uyumlu nokta sayısı yetersiz: beklenen={expected_count}, "
                f"gelen={compatible_count}."
            )
        return QdrantReadinessReport(
            collection_name=self.collection_name,
            expected_point_count=expected_count,
            total_point_count=total_count,
            compatible_point_count=compatible_count,
            corpus_fingerprint=binding.fingerprint,
            embedding_model=self.embedding_model,
            embedding_dimension=self.embedding_dimension,
            index_version=self.index_version,
            storage_mode=self.storage_mode,
            payload_indexes_enforced=self.payload_indexes_enforced,
            payload_index_detail=(
                "Qdrant sunucusunda zorunlu payload indeksleri doğrulandı."
                if self.payload_indexes_enforced
                else (
                    "Gömülü yerel Qdrant payload indekslerini desteklemez; "
                    "filtre metadata'sı readiness sayımıyla doğrulandı."
                )
            ),
            corpus_mode=self.corpus_mode.value,
            currentness_verified=(
                self.corpus_mode == CorpusMode.VERIFIED_PUBLIC
            ),
            legal_reliance_allowed=(
                self.corpus_mode == CorpusMode.VERIFIED_PUBLIC
            ),
            usage_notice=(
                COMPETITION_SNAPSHOT_NOTICE
                if self.corpus_mode == CorpusMode.COMPETITION_SNAPSHOT
                else None
            ),
        )

    def build_payload(
        self, chunk: LegislationChunk | Mapping[str, Any]
    ) -> dict[str, Any]:
        """Build a versioned payload under the store's selected trust contract."""

        binding = self._require_corpus_binding()
        legal_chunk = self._coerce_chunk(chunk)
        self._validate_chunk_for_active_index(legal_chunk)
        if legal_chunk.chunk_id not in binding.allowed_chunk_ids:
            raise SchemaMismatch(
                f"{legal_chunk.chunk_id} bağlı corpus chunk_id izin listesinde değil."
            )
        expected_chunk_fingerprint = binding.expected_chunk_fingerprint(
            legal_chunk.chunk_id
        )
        actual_chunk_fingerprint = chunk_fingerprint(legal_chunk)
        if actual_chunk_fingerprint != expected_chunk_fingerprint:
            raise SchemaMismatch(
                f"{legal_chunk.chunk_id} içeriği bağlı corpus ile uyuşmuyor."
            )
        payload = legal_chunk.model_dump(mode="json")
        payload["source_path"] = payload.pop("source")
        payload["original_text"] = payload.pop("text")
        payload.update(
            {
                "embedding_model": self.embedding_model,
                "embedding_dimension": self.embedding_dimension,
                "embedding_task": self.passage_task,
                "index_version": self.index_version,
                "corpus_fingerprint": binding.fingerprint,
                "chunk_fingerprint": actual_chunk_fingerprint,
                "corpus_mode": self.corpus_mode.value,
                "currentness_verified": (
                    self.corpus_mode == CorpusMode.VERIFIED_PUBLIC
                ),
                "legal_reliance_allowed": (
                    self.corpus_mode == CorpusMode.VERIFIED_PUBLIC
                ),
                "usage_notice": (
                    COMPETITION_SNAPSHOT_NOTICE
                    if self.corpus_mode == CorpusMode.COMPETITION_SNAPSHOT
                    else None
                ),
            }
        )
        if self.embedding_model_revision is not None:
            payload["embedding_model_revision"] = self.embedding_model_revision
        if self.embedding_code_revision is not None:
            payload["embedding_code_revision"] = self.embedding_code_revision
        return payload

    def upsert(
        self,
        chunks: Iterable[LegislationChunk | Mapping[str, Any]],
        vectors: Iterable[Sequence[float]],
        *,
        embedding_task: str = DEFAULT_PASSAGE_TASK,
        wait: bool = True,
    ) -> int:
        """Upsert aligned chunks/vectors and return the number of points."""

        if embedding_task != self.passage_task:
            raise SchemaMismatch(
                "Belge vektörleri yanlış görev adaptörüyle üretildi: "
                f"beklenen={self.passage_task!r}, gelen={embedding_task!r}."
            )
        self._require_corpus_binding()
        legal_chunks = [self._coerce_chunk(chunk) for chunk in chunks]
        normalized_vectors = [self._normalize_vector(vector) for vector in vectors]
        if len(legal_chunks) != len(normalized_vectors):
            raise ValueError("Chunk ve embedding sayıları eşit olmalıdır.")
        if not legal_chunks:
            return 0

        chunk_ids = [chunk.chunk_id for chunk in legal_chunks]
        if len(set(chunk_ids)) != len(chunk_ids):
            raise ValueError("Aynı upsert çağrısında yinelenen chunk_id bulunamaz.")

        points = [
            self._point_struct(
                point_id=stable_point_id(chunk.chunk_id),
                vector=vector,
                payload=self.build_payload(chunk),
            )
            for chunk, vector in zip(legal_chunks, normalized_vectors, strict=True)
        ]
        # Indexing is the only path allowed to create/repair collection metadata.
        self.ensure_collection()
        client = self.client
        if not hasattr(client, "upsert"):
            raise QdrantUnavailable("Qdrant istemcisi upsert işlemini desteklemiyor.")
        try:
            result = client.upsert(
                collection_name=self.collection_name,
                points=points,
                wait=wait,
            )
        except Exception as exc:
            raise QdrantUnavailable(
                f"Qdrant upsert işlemi başarısız: {self.collection_name}."
            ) from exc

        status = self._read_value(result, "status")
        if status is not None and self._normalize_name(status) in {
            "failed",
            "failure",
            "error",
        }:
            raise QdrantUnavailable(
                f"Qdrant upsert işlemi başarısız durum döndürdü: {status}."
            )
        return len(points)

    def upsert_chunks(
        self,
        chunks: Iterable[LegislationChunk | Mapping[str, Any]],
        vectors: Iterable[Sequence[float]],
        *,
        embedding_task: str = DEFAULT_PASSAGE_TASK,
        wait: bool = True,
    ) -> int:
        return self.upsert(
            chunks,
            vectors,
            embedding_task=embedding_task,
            wait=wait,
        )

    def dense_search(
        self,
        query_vector: Sequence[float],
        *,
        domain: str,
        limit: int = 20,
        embedding_task: str = DEFAULT_QUERY_TASK,
    ) -> list[SearchHit]:
        """Search with mandatory corpus-mode, validity, and domain filters."""

        normalized_domain = domain.strip()
        if not normalized_domain or normalized_domain == "unknown":
            raise ValueError(
                "Dense arama için açık ve doğrulanmış bir domain filtresi zorunludur."
            )
        if embedding_task != self.query_task:
            raise SchemaMismatch(
                "Sorgu vektörü yanlış görev adaptörüyle üretildi: "
                f"beklenen={self.query_task!r}, gelen={embedding_task!r}."
            )
        binding = self._require_corpus_binding()
        if limit < 1:
            raise ValueError("limit pozitif olmalıdır.")
        if not binding.chunk_ids:
            return []

        vector = self._normalize_vector(query_vector)
        query_filter = self._active_filter(normalized_domain, binding)
        # Query-time access is read-only and must fail closed when indexing has
        # not been completed.
        self.require_collection()
        client = self.client

        try:
            if hasattr(client, "query_points"):
                response = client.query_points(
                    collection_name=self.collection_name,
                    query=vector,
                    query_filter=query_filter,
                    limit=limit,
                    with_payload=True,
                    with_vectors=False,
                )
                points = self._read_value(response, "points")
                if points is None:
                    points = response
            elif hasattr(client, "search"):
                points = client.search(
                    collection_name=self.collection_name,
                    query_vector=vector,
                    query_filter=query_filter,
                    limit=limit,
                    with_payload=True,
                    with_vectors=False,
                )
            else:
                raise QdrantUnavailable(
                    "Qdrant istemcisi query_points/search işlemini desteklemiyor."
                )
        except QdrantUnavailable:
            raise
        except Exception as exc:
            raise QdrantUnavailable(
                f"Qdrant dense araması başarısız: {self.collection_name}."
            ) from exc

        if points is None:
            return []
        try:
            point_list = list(points)
        except TypeError as exc:
            raise SchemaMismatch("Qdrant arama yanıtı bir nokta listesi değil.") from exc

        hits: list[SearchHit] = []
        for point in point_list:
            payload = self._read_value(point, "payload")
            if not isinstance(payload, Mapping):
                raise SchemaMismatch("Qdrant sonucunda payload eksik veya geçersiz.")
            if not self._payload_is_active_for_domain(
                payload,
                normalized_domain,
                binding,
            ):
                continue
            self._validate_payload_metadata(payload)
            score = self._read_value(point, "score")
            try:
                numeric_score = float(score)
            except (TypeError, ValueError) as exc:
                raise SchemaMismatch("Qdrant sonucunda geçerli skor yok.") from exc
            if not math.isfinite(numeric_score):
                raise SchemaMismatch("Qdrant sonucundaki skor sonlu değil.")
            chunk = self._chunk_from_payload(payload)
            self._validate_chunk_for_active_index(chunk)
            self._validate_chunk_content_binding(chunk, payload, binding)
            hits.append(
                SearchHit(
                    chunk=chunk,
                    score=numeric_score,
                    matched_terms=[],
                )
            )
        return hits

    def search(
        self,
        query_vector: Sequence[float],
        *,
        domain: str,
        top_k: int = 20,
        embedding_task: str = DEFAULT_QUERY_TASK,
    ) -> list[SearchHit]:
        """BM25-like convenience alias using ``top_k``."""

        return self.dense_search(
            query_vector,
            domain=domain,
            limit=top_k,
            embedding_task=embedding_task,
        )

    def _get_collection_info(self, client: Any) -> Any | None:
        if hasattr(client, "collection_exists"):
            try:
                exists = bool(client.collection_exists(self.collection_name))
            except Exception as exc:
                raise QdrantUnavailable(
                    f"Qdrant koleksiyon durumu okunamadı: {self.collection_name}."
                ) from exc
            if not exists:
                return None

        if not hasattr(client, "get_collection"):
            raise QdrantUnavailable(
                "Qdrant istemcisi get_collection işlemini desteklemiyor."
            )
        try:
            return client.get_collection(self.collection_name)
        except Exception as exc:
            if not hasattr(client, "collection_exists") and self._is_not_found(exc):
                return None
            raise QdrantUnavailable(
                f"Qdrant koleksiyon şeması okunamadı: {self.collection_name}."
            ) from exc

    def _validate_collection_schema(self, info: Any) -> None:
        config = self._read_value(info, "config")
        params = self._read_value(config, "params")
        vectors = self._read_value(params, "vectors")
        if vectors is None:
            vectors = self._read_value(params, "vectors_config")
        if vectors is None:
            raise SchemaMismatch(
                f"{self.collection_name} koleksiyonunda vektör şeması bulunamadı."
            )

        if isinstance(vectors, Mapping) and not {
            "size",
            "distance",
        }.issubset(vectors):
            names = ", ".join(str(name) for name in vectors) or "(boş)"
            raise SchemaMismatch(
                f"{self.collection_name} adlandırılmış/beklenmeyen vektör şeması "
                f"kullanıyor: {names}."
            )

        size = self._read_value(vectors, "size")
        distance = self._read_value(vectors, "distance")
        if size != self.embedding_dimension:
            raise SchemaMismatch(
                f"{self.collection_name} vektör boyutu uyuşmuyor: "
                f"beklenen={self.embedding_dimension}, gelen={size}."
            )
        if self._normalize_name(distance) != self._normalize_name(DEFAULT_DISTANCE):
            raise SchemaMismatch(
                f"{self.collection_name} uzaklık metriği uyuşmuyor: "
                f"beklenen={DEFAULT_DISTANCE}, gelen={distance}."
            )

    def _ensure_payload_indexes(self, client: Any, info: Any | None) -> None:
        schema = self._read_value(info, "payload_schema") if info is not None else None
        existing = schema if isinstance(schema, Mapping) else {}
        for field_name, expected_type in PAYLOAD_INDEXES.items():
            if field_name in existing:
                actual = self._read_value(existing[field_name], "data_type")
                if actual is None:
                    actual = existing[field_name]
                if not self._payload_types_match(actual, expected_type):
                    raise SchemaMismatch(
                        f"{self.collection_name}.{field_name} payload indeksi uyuşmuyor: "
                        f"beklenen={expected_type}, gelen={actual}."
                    )
                continue

            if not hasattr(client, "create_payload_index"):
                raise QdrantUnavailable(
                    "Qdrant istemcisi create_payload_index işlemini desteklemiyor."
                )
            try:
                client.create_payload_index(
                    collection_name=self.collection_name,
                    field_name=field_name,
                    field_schema=self._payload_schema_type(expected_type),
                    wait=True,
                )
            except Exception as exc:
                raise QdrantUnavailable(
                    f"Qdrant payload indeksi oluşturulamadı: {field_name}."
                ) from exc

    def _validate_payload_indexes(self, info: Any) -> None:
        schema = self._read_value(info, "payload_schema")
        existing = schema if isinstance(schema, Mapping) else {}
        missing = sorted(set(PAYLOAD_INDEXES) - set(existing))
        if missing:
            raise SchemaMismatch(
                f"{self.collection_name} zorunlu payload indekslerini taşımıyor: "
                + ", ".join(missing)
                + "."
            )
        for field_name, expected_type in PAYLOAD_INDEXES.items():
            actual = self._read_value(existing[field_name], "data_type")
            if actual is None:
                actual = existing[field_name]
            if not self._payload_types_match(actual, expected_type):
                raise SchemaMismatch(
                    f"{self.collection_name}.{field_name} payload indeksi uyuşmuyor: "
                    f"beklenen={expected_type}, gelen={actual}."
                )

    def _count_points(self, *, count_filter: Any | None = None) -> int:
        client = self.client
        if not hasattr(client, "count"):
            raise QdrantUnavailable(
                "Qdrant istemcisi readiness için count işlemini desteklemiyor."
            )
        try:
            result = client.count(
                collection_name=self.collection_name,
                count_filter=count_filter,
                exact=True,
            )
        except Exception as exc:
            raise QdrantUnavailable(
                f"Qdrant koleksiyon sayımı başarısız: {self.collection_name}."
            ) from exc
        count = self._read_value(result, "count")
        if type(count) is not int or count < 0:
            raise SchemaMismatch("Qdrant count yanıtı geçersiz.")
        return count

    def _vector_params(self) -> Any:
        models = self._request_models()
        if models is None:
            return _CompatVectorParams(
                size=self.embedding_dimension,
                distance=DEFAULT_DISTANCE,
            )
        return models.VectorParams(
            size=self.embedding_dimension,
            distance=models.Distance.COSINE,
        )

    def _payload_schema_type(self, expected_type: str) -> Any:
        models = self._request_models()
        if models is None:
            return expected_type
        enum_name = "BOOL" if expected_type == "bool" else "KEYWORD"
        return getattr(models.PayloadSchemaType, enum_name)

    def _point_struct(
        self, *, point_id: str, vector: list[float], payload: dict[str, Any]
    ) -> Any:
        models = self._request_models()
        if models is None:
            return _CompatPointStruct(id=point_id, vector=vector, payload=payload)
        return models.PointStruct(id=point_id, vector=vector, payload=payload)

    def _active_filter(self, domain: str, binding: CorpusBinding) -> Any:
        values = self._trust_filter_values()
        values.extend(
            [
                ("domain", domain),
                ("corpus_fingerprint", binding.fingerprint),
            ]
        )
        models = self._request_models()
        if models is None:
            return _CompatFilter(
                must=[
                    _CompatFieldCondition(key=key, match=_CompatMatchValue(value=value))
                    for key, value in values
                ]
                + [
                    _CompatFieldCondition(
                        key="chunk_id",
                        match=_CompatMatchAny(any=list(binding.chunk_ids)),
                    )
                ]
            )
        return models.Filter(
            must=[
                models.FieldCondition(
                    key=key,
                    match=models.MatchValue(value=value),
                )
                for key, value in values
            ]
            + [
                models.FieldCondition(
                    key="chunk_id",
                    match=models.MatchAny(any=list(binding.chunk_ids)),
                )
            ]
        )

    def _readiness_filter(self, binding: CorpusBinding) -> Any:
        values: list[tuple[str, Any]] = [
            *self._trust_filter_values(),
            ("corpus_fingerprint", binding.fingerprint),
            ("embedding_model", self.embedding_model),
            ("embedding_dimension", self.embedding_dimension),
            ("embedding_task", self.passage_task),
            ("index_version", self.index_version),
        ]
        if self.embedding_model_revision is not None:
            values.append(("embedding_model_revision", self.embedding_model_revision))
        if self.embedding_code_revision is not None:
            values.append(("embedding_code_revision", self.embedding_code_revision))

        models = self._request_models()
        if models is None:
            return _CompatFilter(
                must=[
                    _CompatFieldCondition(key=key, match=_CompatMatchValue(value=value))
                    for key, value in values
                ]
                + [
                    _CompatFieldCondition(
                        key="chunk_id",
                        match=_CompatMatchAny(any=list(binding.chunk_ids)),
                    )
                ]
            )
        return models.Filter(
            must=[
                models.FieldCondition(key=key, match=models.MatchValue(value=value))
                for key, value in values
            ]
            + [
                models.FieldCondition(
                    key="chunk_id",
                    match=models.MatchAny(any=list(binding.chunk_ids)),
                )
            ]
        )

    def _request_models(self) -> Any | None:
        if self._models_checked:
            return self._models_module
        self._models_checked = True
        for module_name in ("qdrant_client.models", "qdrant_client.http.models"):
            try:
                self._models_module = import_module(module_name)
                break
            except ImportError:
                continue
        return self._models_module

    def _normalize_vector(self, vector: Sequence[float]) -> list[float]:
        if isinstance(vector, (str, bytes, bytearray)):
            raise ValueError("Embedding sayısal bir dizi olmalıdır.")
        try:
            normalized = [float(value) for value in vector]
        except (TypeError, ValueError) as exc:
            raise ValueError("Embedding yalnızca sayısal değerlerden oluşmalıdır.") from exc
        if len(normalized) != self.embedding_dimension:
            raise SchemaMismatch(
                "Embedding boyutu uyuşmuyor: "
                f"beklenen={self.embedding_dimension}, gelen={len(normalized)}."
            )
        if not all(math.isfinite(value) for value in normalized):
            raise ValueError("Embedding NaN veya sonsuz değer içeremez.")
        return normalized

    @staticmethod
    def _coerce_chunk(
        chunk: LegislationChunk | Mapping[str, Any]
    ) -> LegislationChunk:
        if isinstance(chunk, LegislationChunk):
            return chunk
        try:
            return LegislationChunk.model_validate(chunk)
        except (ValidationError, TypeError) as exc:
            raise SchemaMismatch(f"LegislationChunk payload'ı geçersiz: {exc}") from exc

    def _validate_chunk_for_active_index(self, chunk: LegislationChunk) -> None:
        blockers = (
            competition_snapshot_chunk_blockers(chunk)
            if self.corpus_mode == CorpusMode.COMPETITION_SNAPSHOT
            else LegislationRepository.public_chunk_blockers(chunk)
        )
        if blockers:
            target_label = (
                "yarışma snapshot Qdrant indeksine"
                if self.corpus_mode == CorpusMode.COMPETITION_SNAPSHOT
                else "aktif Qdrant indeksine"
            )
            raise SchemaMismatch(
                f"{chunk.chunk_id} {target_label} alınamaz: "
                + ", ".join(blockers)
                + "."
            )

    def _validate_payload_metadata(self, payload: Mapping[str, Any]) -> None:
        binding = self._require_corpus_binding()
        expected = {
            "embedding_model": self.embedding_model,
            "embedding_dimension": self.embedding_dimension,
            "embedding_task": self.passage_task,
            "index_version": self.index_version,
            "corpus_fingerprint": binding.fingerprint,
            "corpus_mode": self.corpus_mode.value,
            "currentness_verified": (
                self.corpus_mode == CorpusMode.VERIFIED_PUBLIC
            ),
            "legal_reliance_allowed": (
                self.corpus_mode == CorpusMode.VERIFIED_PUBLIC
            ),
            "usage_notice": (
                COMPETITION_SNAPSHOT_NOTICE
                if self.corpus_mode == CorpusMode.COMPETITION_SNAPSHOT
                else None
            ),
        }
        if self.embedding_model_revision is not None:
            expected["embedding_model_revision"] = self.embedding_model_revision
        if self.embedding_code_revision is not None:
            expected["embedding_code_revision"] = self.embedding_code_revision
        chunk_id = payload.get("chunk_id")
        expected_chunk_fingerprint = (
            binding.expected_chunk_fingerprint(chunk_id)
            if isinstance(chunk_id, str)
            else None
        )
        expected["chunk_fingerprint"] = expected_chunk_fingerprint
        mismatches = [
            f"{key}: beklenen={value!r}, gelen={payload.get(key)!r}"
            for key, value in expected.items()
            if payload.get(key) != value
        ]
        if mismatches:
            raise SchemaMismatch(
                "Qdrant payload embedding sözleşmesi uyuşmuyor; "
                + "; ".join(mismatches)
                + "."
            )

    def _payload_is_active_for_domain(
        self,
        payload: Mapping[str, Any],
        domain: str,
        binding: CorpusBinding,
    ) -> bool:
        trust_values = self._trust_filter_values()
        return (
            all(payload.get(key) == value for key, value in trust_values)
            and payload.get("domain") == domain
            and payload.get("corpus_fingerprint") == binding.fingerprint
            and payload.get("chunk_id") in binding.allowed_chunk_ids
            and payload.get("chunk_fingerprint")
            == binding.expected_chunk_fingerprint(str(payload.get("chunk_id")))
        )

    def _trust_filter_values(self) -> list[tuple[str, Any]]:
        if self.corpus_mode == CorpusMode.COMPETITION_SNAPSHOT:
            return [
                ("approved_for_active_rag", False),
                ("validity_status", "needs_verification"),
                ("source_kind", CorpusMode.COMPETITION_SNAPSHOT.value),
                ("status", COMPETITION_SNAPSHOT_STATUS),
                ("corpus_mode", CorpusMode.COMPETITION_SNAPSHOT.value),
                ("currentness_verified", False),
                ("legal_reliance_allowed", False),
            ]
        return [
            ("approved_for_active_rag", True),
            ("validity_status", "verified"),
            ("source_kind", "public_legislation"),
            ("corpus_mode", CorpusMode.VERIFIED_PUBLIC.value),
            ("currentness_verified", True),
            ("legal_reliance_allowed", True),
        ]

    @staticmethod
    def _validate_chunk_content_binding(
        chunk: LegislationChunk,
        payload: Mapping[str, Any],
        binding: CorpusBinding,
    ) -> None:
        expected = binding.expected_chunk_fingerprint(chunk.chunk_id)
        actual = chunk_fingerprint(chunk)
        if expected is None or payload.get("chunk_fingerprint") != expected:
            raise SchemaMismatch(
                f"{chunk.chunk_id} Qdrant chunk fingerprint sözleşmesi uyuşmuyor."
            )
        if actual != expected:
            raise SchemaMismatch(
                f"{chunk.chunk_id} Qdrant payload içeriği bağlı corpus ile uyuşmuyor."
            )

    def _require_corpus_binding(self) -> CorpusBinding:
        binding = self._corpus_binding
        if binding is None:
            raise SchemaMismatch(
                "Qdrant store corpus binding olmadan kullanılamaz; "
                "fingerprint ve izinli chunk ID'leri zorunludur."
            )
        return binding

    @staticmethod
    def _chunk_from_payload(payload: Mapping[str, Any]) -> LegislationChunk:
        data = {
            field_name: payload[field_name]
            for field_name in LegislationChunk.model_fields
            if field_name in payload
        }
        if "text" not in data and "original_text" in payload:
            data["text"] = payload["original_text"]
        if "source" not in data and "source_path" in payload:
            data["source"] = payload["source_path"]
        try:
            return LegislationChunk.model_validate(data)
        except ValidationError as exc:
            raise SchemaMismatch(
                f"Qdrant payload'ı LegislationChunk olarak doğrulanamadı: {exc}"
            ) from exc

    @staticmethod
    def _read_value(value: Any, key: str) -> Any:
        if value is None:
            return None
        if isinstance(value, Mapping):
            return value.get(key)
        return getattr(value, key, None)

    @classmethod
    def _normalize_name(cls, value: Any) -> str:
        if value is None:
            return ""
        enum_value = getattr(value, "value", None)
        if enum_value is not None:
            value = enum_value
        return str(value).strip().lower().replace("_", "")

    @classmethod
    def _payload_types_match(cls, actual: Any, expected: str) -> bool:
        normalized = cls._normalize_name(actual)
        expected_names = {"bool", "boolean"} if expected == "bool" else {expected}
        return normalized in expected_names

    @staticmethod
    def _is_not_found(exc: Exception) -> bool:
        if isinstance(exc, KeyError):
            return True
        status = getattr(exc, "status_code", None)
        if status is None:
            response = getattr(exc, "response", None)
            status = getattr(response, "status_code", None)
        return status == 404 or "not found" in str(exc).lower()


QdrantLegalChunkStore = QdrantStore
LegalChunkQdrantStore = QdrantStore


__all__ = [
    "DEFAULT_COLLECTION_NAME",
    "DEFAULT_COMPETITION_SNAPSHOT_COLLECTION_NAME",
    "DEFAULT_DISTANCE",
    "DEFAULT_EMBEDDING_DIMENSION",
    "DEFAULT_EMBEDDING_MODEL",
    "DEFAULT_INDEX_VERSION",
    "DEFAULT_PASSAGE_TASK",
    "DEFAULT_QUERY_TASK",
    "LegalChunkQdrantStore",
    "PAYLOAD_INDEXES",
    "QdrantLegalChunkStore",
    "QdrantReadinessReport",
    "QdrantSchemaMismatch",
    "QdrantStore",
    "QdrantUnavailable",
    "QdrantUnavailableError",
    "SchemaMismatch",
    "stable_point_id",
]
