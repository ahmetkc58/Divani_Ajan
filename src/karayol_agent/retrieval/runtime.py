"""Production wiring for task-aware Jina embeddings and Qdrant retrieval.

Optional ML/Qdrant packages remain lazy: importing this module and constructing
the runtime do not import ``transformers``, ``sentence_transformers`` or
``qdrant_client``. The first real embedding/search operation is the boundary at
which those adapters may report their explicit availability errors.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol

from karayol_agent.schemas import DocumentAnalysis, SearchHit
from karayol_agent.text_utils import normalize_for_search, normalize_whitespace

from .corpus import CorpusBinding
from .embeddings import (
    DEFAULT_EMBEDDING_DIMENSION,
    DEFAULT_JINA_MODEL,
    EmbeddingMetadata,
    EmbeddingProvider,
    JINA_EMBEDDINGS_V3_CODE_REVISION,
    JINA_EMBEDDINGS_V3_REVISION,
    JinaEmbeddingProvider,
)
from .hybrid import (
    DEFAULT_CHANNEL_TOP_N,
    DEFAULT_RRF_K,
    HybridRetriever,
    HybridSearchHit,
    HybridSearchResponse,
    RankedRetriever,
)
from .qdrant_store import (
    ALL_DOMAINS_FILTER,
    DEFAULT_COLLECTION_NAME,
    DEFAULT_INDEX_VERSION,
    QdrantStore,
)


ACTIVE_RETRIEVAL_DOMAINS = frozenset(
    {
        "official_writing",
        "general_application",
        "kgm_infrastructure",
        "road_transport",
    }
)


class DomainResolutionError(ValueError):
    """The analysis does not support one unambiguous active-domain filter."""


class RuntimeContractError(ValueError):
    """Embedding and vector-store model/task/dimension contracts disagree."""


@dataclass(frozen=True, slots=True)
class DomainResolution:
    """Observable result of resolving an analysis into a Qdrant domain."""

    domain: str
    confidence: float
    source: str
    evidence: tuple[str, ...] = ()


class DomainResolver(Protocol):
    def resolve(self, analysis: DocumentAnalysis | Mapping[str, Any]) -> DomainResolution:
        """Resolve an analysis to exactly one active retrieval domain."""


class DenseVectorStore(Protocol):
    embedding_model: str
    embedding_dimension: int
    embedding_model_revision: str | None
    embedding_code_revision: str | None
    passage_task: str
    query_task: str

    def dense_search(
        self,
        query_vector: Sequence[float],
        *,
        domain: str,
        limit: int = 20,
        embedding_task: str = "retrieval.query",
    ) -> list[SearchHit]:
        """Search active, verified points inside one domain."""


class AnalysisDomainResolver:
    """Conservative rule-based domain resolution for ``DocumentAnalysis``.

    An explicit active-domain value wins. Otherwise the resolver combines the
    classified document type with summary, keyword, subject and request signals.
    Close cross-domain scores fail closed instead of issuing a broad dense query.
    """

    DOCUMENT_TYPE_HINTS: dict[str, tuple[str, int]] = {
        "yol_bakim_talebi": ("kgm_infrastructure", 7),
        "trafik_guvenligi_bildirimi": ("kgm_infrastructure", 7),
        "hasar_bildirimi": ("kgm_infrastructure", 6),
        "ust_yazi": ("official_writing", 6),
        "bilgi_talebi": ("general_application", 3),
        "sikayet": ("general_application", 3),
        "dilekce": ("general_application", 4),
        "genel_basvuru": ("general_application", 4),
    }
    DOMAIN_MARKERS: dict[str, tuple[tuple[str, int], ...]] = {
        "kgm_infrastructure": (
            ("yol bakım", 8),
            ("trafik güven", 7),
            ("trafik işaret", 6),
            ("karayolu altyap", 8),
            ("yol hasar", 7),
            ("kamulaştır", 7),
            ("asfalt", 6),
            ("çukur", 6),
            ("bariyer", 5),
            ("otoyol", 5),
            ("köprü", 5),
            ("tünel", 5),
            ("viyadük", 5),
            ("levha", 4),
            ("onarım", 4),
        ),
        "road_transport": (
            ("karayolu taşıma", 10),
            ("karayolu taşımac", 10),
            ("yolcu taşı", 8),
            ("eşya taşı", 8),
            ("yük taşı", 8),
            ("yetki belgesi", 8),
            ("araç muayene", 8),
            ("yola elverişlilik", 8),
            ("taşıt kart", 7),
            ("takograf", 7),
            ("ubak", 7),
            ("kış lastiği", 7),
            ("mesleki yeterlilik", 6),
            ("terminal", 5),
            ("şoför", 4),
        ),
        "official_writing": (
            ("resmî yazış", 10),
            ("resmi yazış", 10),
            ("standart dosya plan", 8),
            ("elektronik belge yönet", 8),
            ("üst yazı", 6),
        ),
        "general_application": (
            ("bilgi edinme", 9),
            ("dilekçe hakk", 9),
            ("kişisel veri", 8),
            ("genel başvuru", 6),
            ("başvuru usul", 5),
        ),
    }

    def resolve(
        self,
        analysis: DocumentAnalysis | Mapping[str, Any],
    ) -> DomainResolution:
        explicit = self._explicit_domain(analysis)
        if explicit is not None:
            if explicit not in ACTIVE_RETRIEVAL_DOMAINS:
                raise DomainResolutionError(
                    f"Analizdeki açık domain aktif retrieval kapsamında değil: {explicit!r}."
                )
            return DomainResolution(
                domain=explicit,
                confidence=1.0,
                source="explicit",
                evidence=(f"analysis.domain={explicit}",),
            )

        document_type = _string_value(
            _read_value(analysis, "operational_category")
        ) or _string_value(_read_value(analysis, "document_type"))
        query_text = build_analysis_query(analysis)
        normalized = normalize_for_search(query_text)
        scores = {domain: 0 for domain in ACTIVE_RETRIEVAL_DOMAINS}
        evidence: dict[str, list[str]] = {
            domain: [] for domain in ACTIVE_RETRIEVAL_DOMAINS
        }

        type_hint = self.DOCUMENT_TYPE_HINTS.get(document_type)
        if type_hint is not None:
            domain, weight = type_hint
            scores[domain] += weight
            evidence[domain].append(f"document_type={document_type} (+{weight})")

        for domain, rules in self.DOMAIN_MARKERS.items():
            for marker, weight in rules:
                if marker in normalized:
                    scores[domain] += weight
                    evidence[domain].append(f"{marker!r} (+{weight})")

        ranked = sorted(scores.items(), key=lambda item: (-item[1], item[0]))
        domain, top_score = ranked[0]
        if top_score <= 0:
            raise DomainResolutionError(
                "Analizden aktif dense retrieval domain'i çözülemedi."
            )

        second_domain, second_score = ranked[1]
        if second_score >= 5 and second_score >= top_score * 0.80:
            raise DomainResolutionError(
                "Analiz birden fazla retrieval domain'i arasında belirsiz: "
                f"{domain}={top_score}, {second_domain}={second_score}."
            )

        total_score = sum(scores.values())
        confidence = top_score / total_score if total_score else 0.0
        return DomainResolution(
            domain=domain,
            confidence=round(confidence, 4),
            source="analysis_rules",
            evidence=tuple(evidence[domain]),
        )

    @staticmethod
    def _explicit_domain(
        analysis: DocumentAnalysis | Mapping[str, Any],
    ) -> str | None:
        direct = _read_value(analysis, "domain")
        if direct is None:
            fields = _read_value(analysis, "fields")
            if isinstance(fields, Mapping):
                direct = _read_value(fields.get("domain"), "value")
        if direct is None:
            return None
        enum_value = getattr(direct, "value", direct)
        normalized = str(enum_value).strip().casefold()
        return None if not normalized or normalized == "unknown" else normalized


class ArchiveWideDomainResolver:
    """Opt-in resolver for exploratory search across a fixed snapshot corpus."""

    def resolve(
        self,
        analysis: DocumentAnalysis | Mapping[str, Any],
    ) -> DomainResolution:
        del analysis
        return DomainResolution(
            domain=ALL_DOMAINS_FILTER,
            confidence=1.0,
            source="archive_wide_opt_in",
            evidence=("snapshot_relevance_policy=lexical_overlap",),
        )


class DomainAwareDenseRetriever:
    """Adapt query text to Jina ``retrieval.query`` plus filtered Qdrant search."""

    def __init__(
        self,
        embedding_provider: EmbeddingProvider,
        vector_store: DenseVectorStore,
        analysis: DocumentAnalysis | Mapping[str, Any],
        *,
        domain_resolver: DomainResolver | None = None,
    ) -> None:
        self.embedding_provider = embedding_provider
        self.vector_store = vector_store
        self.analysis = analysis
        self.domain_resolver = domain_resolver or AnalysisDomainResolver()
        self.last_resolution: DomainResolution | None = None

    def search(self, query: str, top_k: int = 5) -> list[SearchHit]:
        if not isinstance(query, str) or not query.strip():
            raise ValueError("Dense retrieval sorgusu boş olamaz.")
        if isinstance(top_k, bool) or not isinstance(top_k, int) or top_k < 1:
            raise ValueError("top_k pozitif bir tam sayı olmalıdır.")

        # Resolution and contract checks intentionally happen inside search.
        # HybridRetriever can therefore observe the failure and perform its
        # explicit BM25-only fallback instead of failing before either channel.
        resolution = self.domain_resolver.resolve(self.analysis)
        validate_embedding_store_contract(
            self.embedding_provider,
            self.vector_store,
        )
        vectors = self.embedding_provider.embed_queries([query])
        if len(vectors) != 1:
            raise RuntimeContractError(
                "EmbeddingProvider tek sorgu için tam olarak bir vektör döndürmelidir."
            )
        query_task = _task_name(self.embedding_provider.query_metadata)
        hits = self.vector_store.dense_search(
            vectors[0],
            domain=resolution.domain,
            limit=top_k,
            embedding_task=query_task,
        )
        self.last_resolution = resolution
        return list(hits)


class AnalysisAwareHybridRetriever:
    """Build the analysis query and delegate lexical+dense fusion to HybridRetriever."""

    analysis_aware = True
    retrieval_mode = "hybrid"

    def __init__(
        self,
        lexical_retriever: RankedRetriever,
        embedding_provider: EmbeddingProvider,
        vector_store: DenseVectorStore,
        *,
        domain_resolver: DomainResolver | None = None,
        channel_top_n: int = DEFAULT_CHANNEL_TOP_N,
        rrf_k: int = DEFAULT_RRF_K,
    ) -> None:
        self.lexical_retriever = lexical_retriever
        self.embedding_provider = embedding_provider
        self.vector_store = vector_store
        self.domain_resolver = domain_resolver or AnalysisDomainResolver()
        self.channel_top_n = channel_top_n
        self.rrf_k = rrf_k

    def bind(
        self,
        analysis: DocumentAnalysis | Mapping[str, Any],
    ) -> HybridRetriever:
        dense = DomainAwareDenseRetriever(
            self.embedding_provider,
            self.vector_store,
            analysis,
            domain_resolver=self.domain_resolver,
        )
        return HybridRetriever(
            self.lexical_retriever,
            dense,
            channel_top_n=self.channel_top_n,
            rrf_k=self.rrf_k,
        )

    def search(
        self,
        analysis: DocumentAnalysis | Mapping[str, Any],
        top_k: int = 5,
    ) -> list[HybridSearchHit]:
        return self.search_with_diagnostics(analysis, top_k=top_k).hits

    def search_as_search_hits(
        self,
        analysis: DocumentAnalysis | Mapping[str, Any],
        top_k: int = 5,
    ) -> list[SearchHit]:
        return [hit.to_search_hit() for hit in self.search(analysis, top_k=top_k)]

    def search_with_diagnostics(
        self,
        analysis: DocumentAnalysis | Mapping[str, Any],
        top_k: int = 5,
    ) -> HybridSearchResponse:
        query = build_analysis_query(analysis)
        return self.bind(analysis).search_with_diagnostics(query, top_k=top_k)

    def search_for_analysis(
        self,
        query: str,
        analysis: DocumentAnalysis | Mapping[str, Any],
        top_k: int = 5,
    ) -> HybridSearchResponse:
        """Search an already-enriched query while retaining analysis context."""

        return self.bind(analysis).search_with_diagnostics(query, top_k=top_k)


@dataclass(frozen=True, slots=True)
class RetrievalRuntime:
    """Configured, still-lazy production retrieval components."""

    embedding_provider: EmbeddingProvider
    qdrant_store: QdrantStore
    corpus_binding: CorpusBinding
    domain_resolver: DomainResolver = field(default_factory=AnalysisDomainResolver)

    def __post_init__(self) -> None:
        self.qdrant_store.bind_corpus(self.corpus_binding)
        validate_embedding_store_contract(
            self.embedding_provider,
            self.qdrant_store,
        )

    def dense_for(
        self,
        analysis: DocumentAnalysis | Mapping[str, Any],
    ) -> DomainAwareDenseRetriever:
        return DomainAwareDenseRetriever(
            self.embedding_provider,
            self.qdrant_store,
            analysis,
            domain_resolver=self.domain_resolver,
        )

    def hybrid_for(
        self,
        lexical_retriever: RankedRetriever,
        *,
        channel_top_n: int = DEFAULT_CHANNEL_TOP_N,
        rrf_k: int = DEFAULT_RRF_K,
    ) -> AnalysisAwareHybridRetriever:
        return AnalysisAwareHybridRetriever(
            lexical_retriever,
            self.embedding_provider,
            self.qdrant_store,
            domain_resolver=self.domain_resolver,
            channel_top_n=channel_top_n,
            rrf_k=rrf_k,
        )

    def indexing_service(self, *, batch_size: int = 16) -> Any:
        # Local import prevents a module cycle while keeping this convenience
        # method available to ingestion/CLI wiring.
        from .vector_indexing import VectorIndexingService

        return VectorIndexingService(
            self.embedding_provider,
            self.qdrant_store,
            batch_size=batch_size,
        )


def build_analysis_query(
    analysis: DocumentAnalysis | Mapping[str, Any],
) -> str:
    """Create the same enriched query shape for lexical and dense channels."""

    parts: list[str] = []
    document_type = _string_value(_read_value(analysis, "document_type"))
    if document_type:
        parts.append(document_type.replace("_", " "))
    operational_category = _string_value(
        _read_value(analysis, "operational_category")
    )
    if operational_category:
        parts.append(operational_category.replace("_", " "))
    summary = _string_value(_read_value(analysis, "summary"))
    if summary:
        parts.append(summary)

    keywords = _read_value(analysis, "keywords")
    if isinstance(keywords, Sequence) and not isinstance(keywords, (str, bytes)):
        parts.extend(value for item in keywords if (value := _string_value(item)))

    fields = _read_value(analysis, "fields")
    if isinstance(fields, Mapping):
        for field_name in ("konu", "talep"):
            value = _string_value(_read_value(fields.get(field_name), "value"))
            if value:
                parts.append(value)

    unique: list[str] = []
    seen: set[str] = set()
    for part in parts:
        normalized = normalize_whitespace(part)
        key = normalize_for_search(normalized)
        if normalized and key not in seen:
            seen.add(key)
            unique.append(normalized)
    query = " ".join(unique)
    if not query:
        raise ValueError("DocumentAnalysis retrieval sorgusu üretmek için boş olamaz.")
    return query


def validate_embedding_store_contract(
    embedding_provider: EmbeddingProvider,
    vector_store: DenseVectorStore,
) -> None:
    """Fail early if indexing/query vectors could target an incompatible store."""

    passage = embedding_provider.passage_metadata
    query = embedding_provider.query_metadata
    expected = {
        "embedding_model": passage.model_name,
        "embedding_dimension": passage.dimension,
        "embedding_model_revision": passage.model_revision,
        "embedding_code_revision": passage.code_revision,
        "passage_task": _task_name(passage),
        "query_task": _task_name(query),
    }
    actual = {
        "embedding_model": getattr(vector_store, "embedding_model", None),
        "embedding_dimension": getattr(vector_store, "embedding_dimension", None),
        "embedding_model_revision": getattr(
            vector_store, "embedding_model_revision", None
        ),
        "embedding_code_revision": getattr(
            vector_store, "embedding_code_revision", None
        ),
        "passage_task": getattr(vector_store, "passage_task", None),
        "query_task": getattr(vector_store, "query_task", None),
    }
    mismatches = [
        f"{name}: provider={expected[name]!r}, store={actual[name]!r}"
        for name in expected
        if expected[name] != actual[name]
    ]
    if query.model_name != passage.model_name or query.dimension != passage.dimension:
        mismatches.append("provider query/passage model veya boyutu kendi içinde farklı")
    if mismatches:
        raise RuntimeContractError(
            "Embedding/Qdrant sözleşmesi uyuşmuyor: " + "; ".join(mismatches) + "."
        )


def build_retrieval_runtime(
    settings: Any | None = None,
    *,
    embedding_provider: EmbeddingProvider | None = None,
    vector_store: QdrantStore | None = None,
    qdrant_client: Any | None = None,
    domain_resolver: DomainResolver | None = None,
    corpus_binding: CorpusBinding | None = None,
) -> RetrievalRuntime:
    """Construct configured Jina/Qdrant adapters without loading optional deps."""

    if settings is None:
        from karayol_agent.config import settings as project_settings

        settings = project_settings
    if vector_store is not None and qdrant_client is not None:
        raise ValueError("vector_store ve qdrant_client birlikte verilemez.")

    provider = embedding_provider
    if provider is None:
        provider = JinaEmbeddingProvider(
            model_name=getattr(settings, "embedding_model", DEFAULT_JINA_MODEL),
            dimension=getattr(
                settings,
                "embedding_dimension",
                DEFAULT_EMBEDDING_DIMENSION,
            ),
            backend=getattr(settings, "embedding_backend", "transformers"),
            model_revision=getattr(
                settings,
                "embedding_revision",
                JINA_EMBEDDINGS_V3_REVISION,
            ),
            code_revision=getattr(
                settings,
                "embedding_code_revision",
                JINA_EMBEDDINGS_V3_CODE_REVISION,
            ),
            local_files_only=bool(
                getattr(settings, "embedding_local_files_only", False)
            ),
            device=getattr(settings, "embedding_device", None),
            batch_size=getattr(settings, "embedding_batch_size", 16),
            max_length=getattr(settings, "embedding_max_length", None),
        )

    store = vector_store
    if store is None:
        passage_metadata = provider.passage_metadata
        query_metadata = provider.query_metadata
        qdrant_url = getattr(settings, "qdrant_url", None)
        store = QdrantStore(
            client=qdrant_client,
            url=qdrant_url or "http://localhost:6333",
            path=getattr(settings, "qdrant_path", None),
            api_key=getattr(settings, "qdrant_api_key", None),
            timeout=getattr(settings, "qdrant_timeout_seconds", 10.0),
            prefer_grpc=bool(getattr(settings, "qdrant_prefer_grpc", False)),
            collection_name=getattr(
                settings,
                "qdrant_collection",
                DEFAULT_COLLECTION_NAME,
            ),
            vector_name=getattr(settings, "qdrant_vector_name", None),
            embedding_model=passage_metadata.model_name,
            embedding_dimension=passage_metadata.dimension,
            embedding_model_revision=passage_metadata.model_revision,
            embedding_code_revision=passage_metadata.code_revision,
            passage_task=_task_name(passage_metadata),
            query_task=_task_name(query_metadata),
            index_version=getattr(settings, "index_version", DEFAULT_INDEX_VERSION),
            corpus_mode=getattr(settings, "corpus_mode", "verified_public"),
        )

    effective_binding = corpus_binding or store.corpus_binding
    if effective_binding is None:
        raise RuntimeContractError(
            "Retrieval runtime corpus binding olmadan oluşturulamaz; "
            "aktif korpus fingerprint ve chunk ID sözleşmesi zorunludur."
        )
    store.bind_corpus(effective_binding)

    return RetrievalRuntime(
        embedding_provider=provider,
        qdrant_store=store,
        corpus_binding=effective_binding,
        domain_resolver=domain_resolver or AnalysisDomainResolver(),
    )


def _task_name(metadata: EmbeddingMetadata) -> str:
    task = getattr(metadata.task, "value", metadata.task)
    return str(task)


def _read_value(value: Any, name: str) -> Any:
    if value is None:
        return None
    if isinstance(value, Mapping):
        return value.get(name)
    return getattr(value, name, None)


def _string_value(value: Any) -> str:
    if value is None:
        return ""
    enum_value = getattr(value, "value", value)
    return str(enum_value).strip()


create_retrieval_runtime = build_retrieval_runtime
JinaQdrantRuntime = RetrievalRuntime


__all__ = [
    "ACTIVE_RETRIEVAL_DOMAINS",
    "AnalysisAwareHybridRetriever",
    "AnalysisDomainResolver",
    "ArchiveWideDomainResolver",
    "DenseVectorStore",
    "DomainAwareDenseRetriever",
    "DomainResolution",
    "DomainResolutionError",
    "DomainResolver",
    "JinaQdrantRuntime",
    "RetrievalRuntime",
    "RuntimeContractError",
    "build_analysis_query",
    "build_retrieval_runtime",
    "create_retrieval_runtime",
    "validate_embedding_store_contract",
]
