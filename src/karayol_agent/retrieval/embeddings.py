"""Task-aware embedding providers used by the dense retrieval layer.

The public API deliberately separates passage and query encoding. Jina
Embeddings v3 uses different LoRA adapters for the two sides of asymmetric
retrieval, so accepting an arbitrary task string at call sites would make an
incorrect index very easy to create.

No production fallback is selected in this module. Callers may catch
``EmbeddingUnavailableError`` and explicitly continue with BM25, while the
deterministic hash provider below is visibly marked as test/development-only.
"""

from __future__ import annotations

import math
import threading
from collections.abc import Sequence
from dataclasses import dataclass
from enum import Enum
from hashlib import sha256
from importlib import import_module
from typing import Any, Literal, Protocol, runtime_checkable

from karayol_agent.revision_pins import (
    JINA_EMBEDDINGS_V3_CODE_REVISION,
    JINA_EMBEDDINGS_V3_REVISION,
    require_full_commit,
)
from karayol_agent.retrieval.hf_loading import pinned_auto_tokenizer_loading


DEFAULT_JINA_MODEL = "jinaai/jina-embeddings-v3"
DEFAULT_EMBEDDING_DIMENSION = 1024
JINA_NATIVE_DIMENSION = 1024
JINA_MATRYOSHKA_DIMENSIONS = frozenset({32, 64, 128, 256, 512, 768, 1024})


class EmbeddingUnavailableError(RuntimeError):
    """Raised when the configured local embedding backend cannot be used."""


class EmbeddingValidationError(ValueError):
    """Raised when an embedding backend violates the vector contract."""


class EmbeddingTask(str, Enum):
    """The only task adapters allowed by the retrieval embedding contract."""

    PASSAGE = "retrieval.passage"
    QUERY = "retrieval.query"


@dataclass(frozen=True, slots=True)
class EmbeddingMetadata:
    """Version information that can be copied into an index payload."""

    model_name: str
    dimension: int
    task: EmbeddingTask
    backend: str
    model_revision: str | None = None
    code_revision: str | None = None

    def as_payload(self) -> dict[str, str | int]:
        payload: dict[str, str | int] = {
            "embedding_model": self.model_name,
            "embedding_dimension": self.dimension,
            "embedding_task": self.task.value,
            "embedding_backend": self.backend,
        }
        if self.model_revision is not None:
            payload["embedding_model_revision"] = self.model_revision
        if self.code_revision is not None:
            payload["embedding_code_revision"] = self.code_revision
        return payload


@runtime_checkable
class EmbeddingProvider(Protocol):
    """Minimal batch contract consumed by indexing and query-time retrieval."""

    model_name: str
    dimension: int
    model_revision: str | None
    code_revision: str | None

    @property
    def passage_metadata(self) -> EmbeddingMetadata:
        """Return metadata for vectors stored in the passage index."""

    @property
    def query_metadata(self) -> EmbeddingMetadata:
        """Return metadata for query vectors."""

    def embed_passages(self, texts: Sequence[str]) -> list[list[float]]:
        """Embed a batch using the mandatory ``retrieval.passage`` adapter."""

    def embed_queries(self, texts: Sequence[str]) -> list[list[float]]:
        """Embed a batch using the mandatory ``retrieval.query`` adapter."""


class _TaskSeparatedProvider:
    """Shared public API that keeps task choice out of application call sites."""

    model_name: str
    dimension: int
    model_revision: str | None
    code_revision: str | None
    backend: str

    @property
    def passage_metadata(self) -> EmbeddingMetadata:
        return self._metadata(EmbeddingTask.PASSAGE)

    @property
    def query_metadata(self) -> EmbeddingMetadata:
        return self._metadata(EmbeddingTask.QUERY)

    def embed_passages(self, texts: Sequence[str]) -> list[list[float]]:
        return self._embed_task(_validate_text_batch(texts), EmbeddingTask.PASSAGE)

    def embed_queries(self, texts: Sequence[str]) -> list[list[float]]:
        return self._embed_task(_validate_text_batch(texts), EmbeddingTask.QUERY)

    def embed_passage(self, text: str) -> list[float]:
        """Convenience wrapper that still fixes the passage task explicitly."""

        return self.embed_passages([text])[0]

    def embed_query(self, text: str) -> list[float]:
        """Convenience wrapper that still fixes the query task explicitly."""

        return self.embed_queries([text])[0]

    def _metadata(self, task: EmbeddingTask) -> EmbeddingMetadata:
        return EmbeddingMetadata(
            model_name=self.model_name,
            dimension=self.dimension,
            task=task,
            backend=self.backend,
            model_revision=self.model_revision,
            code_revision=self.code_revision,
        )

    def _embed_task(
        self,
        texts: list[str],
        task: EmbeddingTask,
    ) -> list[list[float]]:
        raise NotImplementedError


class JinaEmbeddingProvider(_TaskSeparatedProvider):
    """Lazy, local provider for ``jinaai/jina-embeddings-v3``.

    ``transformers`` is the default backend because the model's remote-code
    ``encode`` method accepts the task adapter directly. The optional
    ``sentence-transformers`` backend follows the model card's ``default_task``
    contract and serializes adapter switching for thread safety.

    Model weights are never downloaded by this module until the first non-empty
    embedding request. Set ``local_files_only=True`` for strict offline use.
    ``model_revision`` pins weights/model files and ``code_revision`` separately
    pins code loaded when ``trust_remote_code`` is enabled.
    """

    _BACKEND_ALIASES = {
        "transformers": "transformers",
        "sentence-transformers": "sentence-transformers",
        "sentence_transformers": "sentence-transformers",
    }

    def __init__(
        self,
        *,
        model_name: str = DEFAULT_JINA_MODEL,
        dimension: int = DEFAULT_EMBEDDING_DIMENSION,
        backend: Literal[
            "transformers", "sentence-transformers", "sentence_transformers"
        ] = "transformers",
        model_revision: str = JINA_EMBEDDINGS_V3_REVISION,
        code_revision: str = JINA_EMBEDDINGS_V3_CODE_REVISION,
        trust_remote_code: bool = True,
        local_files_only: bool = False,
        device: str | None = None,
        batch_size: int = 32,
        max_length: int | None = None,
    ) -> None:
        if not isinstance(model_name, str) or not model_name.strip():
            raise ValueError("model_name boş olamaz.")
        if (
            isinstance(dimension, bool)
            or not isinstance(dimension, int)
            or dimension not in JINA_MATRYOSHKA_DIMENSIONS
        ):
            supported = ", ".join(
                str(value) for value in sorted(JINA_MATRYOSHKA_DIMENSIONS)
            )
            raise ValueError(
                f"Jina embedding dimension desteklenmiyor: {dimension!r}; "
                f"desteklenen boyutlar: {supported}."
            )
        try:
            resolved_backend = self._BACKEND_ALIASES[backend]
        except KeyError as exc:
            raise ValueError(f"Desteklenmeyen embedding backend'i: {backend!r}.") from exc
        if (
            isinstance(batch_size, bool)
            or not isinstance(batch_size, int)
            or batch_size < 1
        ):
            raise ValueError("batch_size pozitif bir tam sayı olmalıdır.")
        if max_length is not None and (
            isinstance(max_length, bool)
            or not isinstance(max_length, int)
            or max_length < 1
            or max_length > 8192
        ):
            raise ValueError("max_length 1 ile 8192 arasında olmalıdır.")

        self.model_name = model_name.strip()
        self.dimension = dimension
        self.backend = resolved_backend
        self.model_revision = require_full_commit(
            model_revision,
            field_name="model_revision",
        )
        self.code_revision = require_full_commit(
            code_revision,
            field_name="code_revision",
        )
        self.trust_remote_code = trust_remote_code
        self.local_files_only = local_files_only
        self.device = device
        self.batch_size = batch_size
        self.max_length = max_length

        self._model: Any | None = None
        self._load_lock = threading.Lock()
        self._inference_lock = threading.RLock()

    @property
    def is_loaded(self) -> bool:
        """Whether the optional backend and model have already been loaded."""

        return self._model is not None

    def _embed_task(
        self,
        texts: list[str],
        task: EmbeddingTask,
    ) -> list[list[float]]:
        if not texts:
            return []

        model = self._get_model()
        try:
            with self._inference_lock:
                if self.backend == "transformers":
                    raw_vectors = self._encode_with_transformers(model, texts, task)
                else:
                    raw_vectors = self._encode_with_sentence_transformers(
                        model, texts, task
                    )
        except EmbeddingValidationError:
            raise
        except Exception as exc:
            raise EmbeddingUnavailableError(
                f"{self.model_name!r} modeli {task.value!r} göreviyle "
                "yerel olarak çalıştırılamadı."
            ) from exc

        return _validate_and_normalize_vectors(
            raw_vectors,
            expected_count=len(texts),
            expected_dimension=self.dimension,
        )

    def _get_model(self) -> Any:
        model = self._model
        if model is not None:
            return model

        with self._load_lock:
            if self._model is not None:
                return self._model
            try:
                if self.backend == "transformers":
                    model = self._load_transformers_model()
                else:
                    model = self._load_sentence_transformer_model()
            except EmbeddingUnavailableError:
                raise
            except Exception as exc:
                offline_note = (
                    " Model yerel önbellekte bulunamadı."
                    if self.local_files_only
                    else " Model dosyaları/bağımlılıkları kullanılamıyor."
                )
                raise EmbeddingUnavailableError(
                    f"{self.model_name!r} yerel embedding modeli yüklenemedi."
                    + offline_note
                ) from exc
            self._model = model
            return model

    def _load_transformers_model(self) -> Any:
        module = _import_optional_backend("transformers")
        try:
            auto_model = module.AutoModel
        except AttributeError as exc:
            raise EmbeddingUnavailableError(
                "transformers.AutoModel bulunamadı; transformers kurulumu geçersiz."
            ) from exc

        load_kwargs: dict[str, Any] = {
            "trust_remote_code": self.trust_remote_code,
            "local_files_only": self.local_files_only,
        }
        if self.model_revision is not None:
            load_kwargs["revision"] = self.model_revision
        if self.code_revision is not None:
            load_kwargs["code_revision"] = self.code_revision

        with pinned_auto_tokenizer_loading(
            module,
            model_name=self.model_name,
            revision=self.model_revision,
            local_files_only=self.local_files_only,
            trust_remote_code=self.trust_remote_code,
        ):
            model = auto_model.from_pretrained(self.model_name, **load_kwargs)
        if self.device is not None:
            model = model.to(self.device)
        if hasattr(model, "eval"):
            model.eval()
        if not callable(getattr(model, "encode", None)):
            raise EmbeddingUnavailableError(
                "Yüklenen Jina modelinde beklenen encode metodu bulunamadı."
            )
        return model

    def _load_sentence_transformer_model(self) -> Any:
        module = _import_optional_backend("sentence_transformers")
        try:
            sentence_transformer = module.SentenceTransformer
        except AttributeError as exc:
            raise EmbeddingUnavailableError(
                "sentence_transformers.SentenceTransformer bulunamadı."
            ) from exc

        load_kwargs: dict[str, Any] = {
            "trust_remote_code": self.trust_remote_code,
            "local_files_only": self.local_files_only,
            "truncate_dim": self.dimension,
        }
        if self.model_revision is not None:
            load_kwargs["revision"] = self.model_revision
        if self.code_revision is not None:
            # SentenceTransformers forwards model_kwargs to AutoModel.
            load_kwargs["model_kwargs"] = {"code_revision": self.code_revision}
        if self.device is not None:
            load_kwargs["device"] = self.device

        transformers_module = _import_optional_backend("transformers")
        with pinned_auto_tokenizer_loading(
            transformers_module,
            model_name=self.model_name,
            revision=self.model_revision,
            local_files_only=self.local_files_only,
            trust_remote_code=self.trust_remote_code,
        ):
            model = sentence_transformer(self.model_name, **load_kwargs)
        if not callable(getattr(model, "encode", None)):
            raise EmbeddingUnavailableError(
                "Yüklenen SentenceTransformer modelinde encode metodu bulunamadı."
            )
        return model

    def _encode_with_transformers(
        self,
        model: Any,
        texts: list[str],
        task: EmbeddingTask,
    ) -> Any:
        encode_kwargs: dict[str, Any] = {
            "task": task.value,
            "truncate_dim": self.dimension,
            "batch_size": self.batch_size,
        }
        if self.max_length is not None:
            encode_kwargs["max_length"] = self.max_length
        return model.encode(texts, **encode_kwargs)

    def _encode_with_sentence_transformers(
        self,
        model: Any,
        texts: list[str],
        task: EmbeddingTask,
    ) -> Any:
        first_module = self._first_sentence_transformer_module(model)
        sentinel = object()
        previous_task = getattr(first_module, "default_task", sentinel)
        setattr(first_module, "default_task", task.value)
        encode_kwargs: dict[str, Any] = {
            "batch_size": self.batch_size,
            "show_progress_bar": False,
            "convert_to_numpy": False,
            "normalize_embeddings": False,
        }
        if self.max_length is not None:
            encode_kwargs["max_length"] = self.max_length
        try:
            return model.encode(texts, **encode_kwargs)
        finally:
            if previous_task is sentinel:
                try:
                    delattr(first_module, "default_task")
                except AttributeError:
                    pass
            else:
                setattr(first_module, "default_task", previous_task)

    @staticmethod
    def _first_sentence_transformer_module(model: Any) -> Any:
        first_module_method = getattr(model, "_first_module", None)
        if callable(first_module_method):
            return first_module_method()
        try:
            return model[0]
        except (KeyError, IndexError, TypeError) as exc:
            raise EmbeddingUnavailableError(
                "SentenceTransformer Jina görev adaptörü bulunamadı."
            ) from exc


class DeterministicHashEmbeddingProvider(_TaskSeparatedProvider):
    """Dependency-free deterministic vectors for tests and development only.

    This class is intentionally not selected by ``JinaEmbeddingProvider`` and
    never acts as an automatic production fallback. ``usage`` is restricted to
    make that boundary machine-checkable as well as visible in metadata.
    """

    def __init__(
        self,
        *,
        dimension: int = DEFAULT_EMBEDDING_DIMENSION,
        seed: str = "karayol-agent-embedding-test-v1",
        usage: Literal["test", "development"] = "test",
    ) -> None:
        if (
            isinstance(dimension, bool)
            or not isinstance(dimension, int)
            or dimension < 1
        ):
            raise ValueError("dimension pozitif bir tam sayı olmalıdır.")
        if usage not in {"test", "development"}:
            raise ValueError(
                "DeterministicHashEmbeddingProvider yalnız test/geliştirme içindir."
            )
        if not isinstance(seed, str) or not seed:
            raise ValueError("seed boş olamaz.")

        self.dimension = dimension
        self.usage = usage
        self.backend = f"deterministic-hash-{usage}-only"
        self.model_name = f"deterministic-hash/{usage}-only"
        self.model_revision = sha256(seed.encode("utf-8")).hexdigest()[:16]
        self.code_revision = None
        self._seed = seed.encode("utf-8")

    @property
    def production_safe(self) -> bool:
        return False

    def _embed_task(
        self,
        texts: list[str],
        task: EmbeddingTask,
    ) -> list[list[float]]:
        raw_vectors = [self._vector_for(text, task) for text in texts]
        return _validate_and_normalize_vectors(
            raw_vectors,
            expected_count=len(texts),
            expected_dimension=self.dimension,
        )

    def _vector_for(self, text: str, task: EmbeddingTask) -> list[float]:
        prefix = b"\x00".join(
            [self._seed, task.value.encode("ascii"), text.encode("utf-8")]
        )
        values: list[float] = []
        counter = 0
        while len(values) < self.dimension:
            digest = sha256(prefix + counter.to_bytes(8, "big")).digest()
            values.extend((byte - 127.5) / 127.5 for byte in digest)
            counter += 1
        return values[: self.dimension]


def _validate_text_batch(texts: Sequence[str]) -> list[str]:
    if isinstance(texts, (str, bytes)):
        raise TypeError("Batch API tek bir str değil, bir metin dizisi bekler.")
    try:
        values = list(texts)
    except TypeError as exc:
        raise TypeError("texts yinelenebilir bir metin dizisi olmalıdır.") from exc
    for index, value in enumerate(values):
        if not isinstance(value, str):
            raise TypeError(
                f"texts[{index}] str olmalıdır; {type(value).__name__} alındı."
            )
    return values


def _import_optional_backend(module_name: str) -> Any:
    try:
        return import_module(module_name)
    except Exception as exc:
        raise EmbeddingUnavailableError(
            f"İsteğe bağlı {module_name!r} embedding bağımlılığı kullanılamıyor."
        ) from exc


def _validate_and_normalize_vectors(
    raw_vectors: Any,
    *,
    expected_count: int,
    expected_dimension: int,
) -> list[list[float]]:
    converted = raw_vectors
    for method_name in ("detach", "cpu"):
        method = getattr(converted, method_name, None)
        if callable(method):
            converted = method()
    tolist = getattr(converted, "tolist", None)
    if callable(tolist):
        converted = tolist()

    try:
        vectors = list(converted)
    except (TypeError, ValueError) as exc:
        raise EmbeddingValidationError(
            "Embedding backend'i iki boyutlu bir batch döndürmedi."
        ) from exc
    if len(vectors) != expected_count:
        raise EmbeddingValidationError(
            "Embedding batch boyutu eşleşmiyor: "
            f"beklenen={expected_count}, alınan={len(vectors)}."
        )

    normalized: list[list[float]] = []
    for vector_index, vector in enumerate(vectors):
        vector_value = vector
        vector_tolist = getattr(vector_value, "tolist", None)
        if callable(vector_tolist):
            vector_value = vector_tolist()
        try:
            coordinates = list(vector_value)
        except (TypeError, ValueError) as exc:
            raise EmbeddingValidationError(
                f"Embedding vektörü {vector_index} bir sayı dizisi değil."
            ) from exc
        if len(coordinates) != expected_dimension:
            raise EmbeddingValidationError(
                f"Embedding vektörü {vector_index} yanlış boyutta: "
                f"beklenen={expected_dimension}, alınan={len(coordinates)}."
            )

        floats: list[float] = []
        for coordinate_index, coordinate in enumerate(coordinates):
            if isinstance(coordinate, bool):
                raise EmbeddingValidationError(
                    f"Embedding [{vector_index}][{coordinate_index}] bool olamaz."
                )
            try:
                number = float(coordinate)
            except (TypeError, ValueError, OverflowError) as exc:
                raise EmbeddingValidationError(
                    f"Embedding [{vector_index}][{coordinate_index}] sayısal değil."
                ) from exc
            if not math.isfinite(number):
                raise EmbeddingValidationError(
                    f"Embedding [{vector_index}][{coordinate_index}] sonlu değil."
                )
            floats.append(number)

        norm = math.sqrt(math.fsum(number * number for number in floats))
        if not math.isfinite(norm) or norm <= 0.0:
            raise EmbeddingValidationError(
                f"Embedding vektörü {vector_index} sıfır veya geçersiz norma sahip."
            )
        normalized.append([number / norm for number in floats])
    return normalized


# Explicit aliases ease integration without introducing a fallback factory.
JinaEmbeddingsV3Provider = JinaEmbeddingProvider
HashEmbeddingProvider = DeterministicHashEmbeddingProvider


__all__ = [
    "DEFAULT_EMBEDDING_DIMENSION",
    "DEFAULT_JINA_MODEL",
    "DeterministicHashEmbeddingProvider",
    "EmbeddingMetadata",
    "EmbeddingProvider",
    "EmbeddingTask",
    "EmbeddingUnavailableError",
    "EmbeddingValidationError",
    "HashEmbeddingProvider",
    "JINA_EMBEDDINGS_V3_CODE_REVISION",
    "JINA_EMBEDDINGS_V3_REVISION",
    "JINA_MATRYOSHKA_DIMENSIONS",
    "JinaEmbeddingProvider",
    "JinaEmbeddingsV3Provider",
]
