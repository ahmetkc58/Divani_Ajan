"""Optional multilingual cross-encoder reranking for fused retrieval hits."""

from __future__ import annotations

import math
import threading
from collections.abc import Sequence
from importlib import import_module
from inspect import Parameter, signature
from time import perf_counter
from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field

from karayol_agent.revision_pins import require_full_commit
from karayol_agent.retrieval.hf_loading import pinned_auto_tokenizer_loading
from karayol_agent.retrieval.hybrid import (
    HybridRetrievalDiagnostics,
    HybridRetriever,
)
from karayol_agent.retrieval.vector_indexing import build_passage_text
from karayol_agent.schemas import SearchHit


DEFAULT_JINA_RERANKER_MODEL = "jinaai/jina-reranker-v2-base-multilingual"
DEFAULT_JINA_RERANKER_REVISION = "9cfeff2df7d40d1b78e75e5e9cebec92a99813c9"
DEFAULT_RERANK_CANDIDATE_TOP_K = 30


class RerankerUnavailableError(RuntimeError):
    """The configured cross-encoder cannot be loaded or invoked."""


class RerankerValidationError(ValueError):
    """The reranker returned malformed or non-finite scores."""


@runtime_checkable
class RerankerProvider(Protocol):
    model_name: str
    revision: str | None
    code_revision: str | None

    def score(self, query: str, passages: Sequence[str]) -> list[float]: ...


class JinaRerankerProvider:
    """Lazy local provider for Jina's multilingual reranker v2.

    The model and its custom code live in the same Hugging Face repository, so
    both pins default to the same verified commit. Flash attention is disabled
    by default for portable CPU/demo operation.
    """

    def __init__(
        self,
        *,
        model_name: str = DEFAULT_JINA_RERANKER_MODEL,
        revision: str = DEFAULT_JINA_RERANKER_REVISION,
        code_revision: str = DEFAULT_JINA_RERANKER_REVISION,
        local_files_only: bool = False,
        device: str = "cpu",
        batch_size: int = 8,
        trust_remote_code: bool = True,
        use_flash_attn: bool = False,
    ) -> None:
        if not model_name.strip():
            raise ValueError("reranker model_name boş olamaz.")
        if isinstance(batch_size, bool) or not isinstance(batch_size, int) or batch_size < 1:
            raise ValueError("reranker batch_size pozitif bir tam sayı olmalıdır.")
        self.model_name = model_name.strip()
        self.revision = require_full_commit(
            revision,
            field_name="reranker revision",
        )
        self.code_revision = require_full_commit(
            code_revision,
            field_name="reranker code_revision",
        )
        self.local_files_only = local_files_only
        self.device = device
        self.batch_size = batch_size
        self.trust_remote_code = trust_remote_code
        self.use_flash_attn = use_flash_attn
        self._model: Any | None = None
        self._load_lock = threading.Lock()
        self._inference_lock = threading.RLock()
        self.score_calls = 0
        self.score_seconds = 0.0

    @property
    def is_loaded(self) -> bool:
        return self._model is not None

    def score(self, query: str, passages: Sequence[str]) -> list[float]:
        if not isinstance(query, str) or not query.strip():
            raise ValueError("reranker query boş olamaz.")
        if isinstance(passages, (str, bytes)):
            raise TypeError("passages tek bir str değil, metin dizisi olmalıdır.")
        values = list(passages)
        if any(not isinstance(value, str) or not value.strip() for value in values):
            raise ValueError("reranker passage değerleri boş olmayan str olmalıdır.")
        if not values:
            return []

        model = self._get_model()
        pairs = [(query, passage) for passage in values]
        started = perf_counter()
        try:
            with self._inference_lock:
                raw_scores = model.predict(
                    pairs,
                    **_supported_predict_kwargs(
                        model.predict,
                        batch_size=self.batch_size,
                    ),
                )
        except Exception as exc:
            raise RerankerUnavailableError(
                f"{self.model_name!r} reranker çıkarımı çalıştırılamadı."
            ) from exc
        finally:
            self.score_calls += 1
            self.score_seconds += perf_counter() - started
        return _coerce_scores(raw_scores, expected_count=len(values))

    def _get_model(self) -> Any:
        if self._model is not None:
            return self._model
        with self._load_lock:
            if self._model is not None:
                return self._model
            try:
                module = import_module("transformers")
                model_type = getattr(module, "AutoModelForSequenceClassification")
                kwargs: dict[str, Any] = {
                    "trust_remote_code": self.trust_remote_code,
                    "local_files_only": self.local_files_only,
                    "torch_dtype": "auto",
                    "use_flash_attn": self.use_flash_attn,
                }
                if self.revision is not None:
                    kwargs["revision"] = self.revision
                if self.code_revision is not None:
                    kwargs["code_revision"] = self.code_revision
                with pinned_auto_tokenizer_loading(
                    module,
                    model_name=self.model_name,
                    revision=self.revision,
                    local_files_only=self.local_files_only,
                    trust_remote_code=self.trust_remote_code,
                ):
                    model = model_type.from_pretrained(self.model_name, **kwargs)
                    tokenizer_type = getattr(module, "AutoTokenizer", None)
                    if tokenizer_type is not None:
                        # Jina's remote ``predict`` path otherwise performs a
                        # second, lazy unpinned tokenizer lookup via _tokenizer.
                        model._tokenizer = tokenizer_type.from_pretrained(
                            self.model_name,
                            trust_remote_code=self.trust_remote_code,
                        )
                model = model.to(self.device)
                model.eval()
                if not callable(getattr(model, "predict", None)):
                    raise RerankerUnavailableError(
                        "Yüklenen Jina reranker beklenen predict metodunu sağlamıyor."
                    )
            except RerankerUnavailableError:
                raise
            except Exception as exc:
                raise RerankerUnavailableError(
                    f"{self.model_name!r} yerel reranker modeli yüklenemedi."
                ) from exc
            self._model = model
            return model


class RerankedSearchResponse(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    hits: list[SearchHit] = Field(default_factory=list)
    diagnostics: HybridRetrievalDiagnostics
    reranker_model: str
    reranker_candidate_count: int = Field(ge=0)
    reranker_seconds: float = Field(ge=0)


class RerankingRetriever:
    """Retrieve a broad RRF set, then cross-encode and return the strongest K."""

    retrieval_mode = "hybrid"
    analysis_aware = False

    def __init__(
        self,
        hybrid_retriever: HybridRetriever,
        reranker: RerankerProvider,
        *,
        candidate_top_k: int = DEFAULT_RERANK_CANDIDATE_TOP_K,
    ) -> None:
        if (
            isinstance(candidate_top_k, bool)
            or not isinstance(candidate_top_k, int)
            or candidate_top_k < 1
        ):
            raise ValueError("candidate_top_k pozitif bir tam sayı olmalıdır.")
        self.hybrid_retriever = hybrid_retriever
        self.reranker = reranker
        self.candidate_top_k = candidate_top_k

    def search(self, query: str, top_k: int = 5) -> list[SearchHit]:
        return self.search_with_diagnostics(query, top_k=top_k).hits

    def search_with_diagnostics(
        self,
        query: str,
        top_k: int = 5,
    ) -> RerankedSearchResponse:
        if not isinstance(query, str) or not query.strip():
            raise ValueError("reranker query boş olamaz.")
        if isinstance(top_k, bool) or not isinstance(top_k, int) or top_k < 0:
            raise ValueError("top_k negatif olmayan bir tam sayı olmalıdır.")
        if top_k == 0:
            return RerankedSearchResponse(
                hits=[],
                diagnostics=HybridRetrievalDiagnostics(
                    dense_status="empty",
                    fallback_used=False,
                    lexical_candidate_count=0,
                    dense_candidate_count=0,
                    fused_candidate_count=0,
                    channel_top_n=self.hybrid_retriever.channel_top_n,
                    rrf_k=self.hybrid_retriever.rrf_k,
                ),
                reranker_model=self.reranker.model_name,
                reranker_candidate_count=0,
                reranker_seconds=0.0,
            )
        candidate_response = self.hybrid_retriever.search_with_diagnostics(
            query,
            top_k=max(top_k, self.candidate_top_k),
        )
        candidates = list(candidate_response.hits)
        if not candidates:
            return RerankedSearchResponse(
                hits=[],
                diagnostics=candidate_response.diagnostics,
                reranker_model=self.reranker.model_name,
                reranker_candidate_count=len(candidates),
                reranker_seconds=0.0,
            )

        passages = [build_passage_text(hit.chunk) for hit in candidates]
        started = perf_counter()
        scores = self.reranker.score(query, passages)
        elapsed = perf_counter() - started
        if len(scores) != len(candidates):
            raise RerankerValidationError(
                "Reranker skor sayısı aday sayısıyla eşleşmiyor."
            )
        reranked = [
            SearchHit(
                chunk=hit.chunk,
                score=score,
                matched_terms=list(hit.matched_terms),
                fusion_method=(
                    f"{hit.fusion_method or 'rrf'}+reranker:"
                    f"{self.reranker.model_name}"
                ),
                channel_contributions=list(hit.channel_contributions),
            )
            for hit, score in zip(candidates, scores, strict=True)
        ]
        reranked.sort(key=lambda hit: (-hit.score, hit.chunk.chunk_id))
        return RerankedSearchResponse(
            hits=reranked[:top_k],
            diagnostics=candidate_response.diagnostics,
            reranker_model=self.reranker.model_name,
            reranker_candidate_count=len(candidates),
            reranker_seconds=round(elapsed, 6),
        )


def _supported_predict_kwargs(
    predict: Any,
    *,
    batch_size: int,
) -> dict[str, int]:
    """Pass ``batch_size`` only when the loaded API explicitly accepts it.

    A broad ``TypeError`` retry would execute inference twice when the model's
    own implementation raises that exception. Signature inspection keeps each
    request single-shot and remains compatible with older pinned revisions.
    """

    try:
        parameters = signature(predict).parameters.values()
    except (TypeError, ValueError):
        return {}
    accepts_batch_size = any(
        parameter.name == "batch_size" or parameter.kind is Parameter.VAR_KEYWORD
        for parameter in parameters
    )
    return {"batch_size": batch_size} if accepts_batch_size else {}


def _coerce_scores(raw_scores: Any, *, expected_count: int) -> list[float]:
    converted = raw_scores
    for method_name in ("detach", "cpu"):
        method = getattr(converted, method_name, None)
        if callable(method):
            converted = method()
    tolist = getattr(converted, "tolist", None)
    if callable(tolist):
        converted = tolist()
    try:
        raw_values = list(converted)
    except TypeError as exc:
        raise RerankerValidationError("Reranker bir skor dizisi döndürmedi.") from exc
    values: list[float] = []
    for raw in raw_values:
        if isinstance(raw, Sequence) and not isinstance(raw, (str, bytes)):
            nested = list(raw)
            if len(nested) != 1:
                raise RerankerValidationError(
                    "Reranker her aday için tek bir skor döndürmelidir."
                )
            raw = nested[0]
        try:
            score = float(raw)
        except (TypeError, ValueError) as exc:
            raise RerankerValidationError("Reranker skoru sayısal değil.") from exc
        if not math.isfinite(score):
            raise RerankerValidationError("Reranker skoru sonlu değil.")
        values.append(score)
    if len(values) != expected_count:
        raise RerankerValidationError(
            "Reranker skor batch boyutu eşleşmiyor: "
            f"beklenen={expected_count}, alınan={len(values)}."
        )
    return values


__all__ = [
    "DEFAULT_JINA_RERANKER_MODEL",
    "DEFAULT_JINA_RERANKER_REVISION",
    "DEFAULT_RERANK_CANDIDATE_TOP_K",
    "JinaRerankerProvider",
    "RerankedSearchResponse",
    "RerankerProvider",
    "RerankerUnavailableError",
    "RerankerValidationError",
    "RerankingRetriever",
]
