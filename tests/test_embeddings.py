from __future__ import annotations

import math
from types import SimpleNamespace
from typing import Any

import pytest

from karayol_agent.retrieval import embeddings
from karayol_agent.retrieval.embeddings import (
    DEFAULT_JINA_MODEL,
    DeterministicHashEmbeddingProvider,
    EmbeddingProvider,
    EmbeddingUnavailableError,
    EmbeddingValidationError,
    JINA_EMBEDDINGS_V3_CODE_REVISION,
    JINA_EMBEDDINGS_V3_REVISION,
    JinaEmbeddingProvider,
)


class _FakeTransformersModel:
    def __init__(self, *, dimension: int = 1024) -> None:
        self.dimension = dimension
        self.calls: list[tuple[list[str], dict[str, Any]]] = []
        self.eval_called = False

    def eval(self) -> None:
        self.eval_called = True

    def encode(self, texts: list[str], **kwargs: Any) -> list[list[float]]:
        self.calls.append((texts, kwargs))
        return [[3.0, 4.0, *([0.0] * (self.dimension - 2))] for _ in texts]


def _install_fake_transformers(
    monkeypatch: pytest.MonkeyPatch,
    model: _FakeTransformersModel,
) -> tuple[list[str], list[tuple[str, dict[str, Any]]]]:
    imports: list[str] = []
    loads: list[tuple[str, dict[str, Any]]] = []

    class FakeAutoModel:
        @staticmethod
        def from_pretrained(model_name: str, **kwargs: Any) -> _FakeTransformersModel:
            loads.append((model_name, kwargs))
            return model

    def fake_import(module_name: str) -> Any:
        imports.append(module_name)
        if module_name == "transformers":
            return SimpleNamespace(AutoModel=FakeAutoModel)
        raise ModuleNotFoundError(module_name)

    monkeypatch.setattr(embeddings, "import_module", fake_import)
    return imports, loads


def test_jina_provider_is_lazy_and_pins_model_and_code_revisions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    model = _FakeTransformersModel()
    imports, loads = _install_fake_transformers(monkeypatch, model)
    provider = JinaEmbeddingProvider(
        model_revision="1" * 40,
        code_revision="2" * 40,
        local_files_only=True,
    )

    assert not provider.is_loaded
    assert imports == []
    assert provider.embed_queries([]) == []
    assert imports == []

    vectors = provider.embed_queries(["Yol bakım talebi", "Köprü denetimi"])

    assert provider.is_loaded
    assert imports == ["transformers"]
    assert loads == [
        (
            DEFAULT_JINA_MODEL,
            {
                "trust_remote_code": True,
                "local_files_only": True,
                "revision": "1" * 40,
                "code_revision": "2" * 40,
            },
        )
    ]
    assert model.eval_called
    assert len(vectors) == 2
    assert all(len(vector) == 1024 for vector in vectors)
    assert vectors[0][:2] == pytest.approx([0.6, 0.8])
    norm = math.sqrt(sum(value * value for value in vectors[0]))
    assert norm == pytest.approx(1.0)


def test_jina_provider_enforces_query_and_passage_tasks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    model = _FakeTransformersModel()
    _install_fake_transformers(monkeypatch, model)
    provider = JinaEmbeddingProvider(batch_size=7, max_length=2048)

    provider.embed_passages(["Bağlam ile asıl mevzuat hükmü"])
    provider.embed_queries(["Hangi madde uygulanır?"])

    assert [call[1]["task"] for call in model.calls] == [
        "retrieval.passage",
        "retrieval.query",
    ]
    assert all(call[1]["truncate_dim"] == 1024 for call in model.calls)
    assert all(call[1]["batch_size"] == 7 for call in model.calls)
    assert all(call[1]["max_length"] == 2048 for call in model.calls)
    assert provider.passage_metadata.as_payload()["embedding_task"] == (
        "retrieval.passage"
    )
    assert provider.query_metadata.as_payload()["embedding_task"] == "retrieval.query"


def test_sentence_transformers_backend_switches_and_restores_task(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    component = SimpleNamespace(default_task="classification")
    seen_tasks: list[str] = []
    loads: list[tuple[str, dict[str, Any]]] = []

    class FakeSentenceTransformer:
        def __init__(self, model_name: str, **kwargs: Any) -> None:
            loads.append((model_name, kwargs))

        def _first_module(self) -> Any:
            return component

        def encode(self, texts: list[str], **kwargs: Any) -> list[list[float]]:
            seen_tasks.append(component.default_task)
            return [[1.0] * 1024 for _ in texts]

    def fake_import(module_name: str) -> Any:
        if module_name == "sentence_transformers":
            return SimpleNamespace(SentenceTransformer=FakeSentenceTransformer)
        if module_name == "transformers":
            return SimpleNamespace()
        raise ModuleNotFoundError(module_name)

    monkeypatch.setattr(embeddings, "import_module", fake_import)
    provider = JinaEmbeddingProvider(
        backend="sentence-transformers",
        model_revision="3" * 40,
        code_revision="4" * 40,
    )

    provider.embed_passages(["Hüküm"])
    provider.embed_queries(["Sorgu"])

    assert seen_tasks == ["retrieval.passage", "retrieval.query"]
    assert component.default_task == "classification"
    assert loads == [
        (
            DEFAULT_JINA_MODEL,
            {
                "trust_remote_code": True,
                "local_files_only": False,
                "truncate_dim": 1024,
                "revision": "3" * 40,
                "model_kwargs": {"code_revision": "4" * 40},
            },
        )
    ]


def test_remote_model_tokenizer_inherits_exact_revision_and_offline_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    model = _FakeTransformersModel()
    tokenizer_loads: list[tuple[str, dict[str, Any]]] = []

    class FakeAutoTokenizer:
        @classmethod
        def from_pretrained(cls, model_name: str, **kwargs: Any) -> object:
            tokenizer_loads.append((model_name, kwargs))
            return object()

    class FakeAutoModel:
        @staticmethod
        def from_pretrained(model_name: str, **kwargs: Any) -> _FakeTransformersModel:
            # Reproduce Jina's pinned remote code omitting both arguments.
            FakeAutoTokenizer.from_pretrained(
                model_name,
                trust_remote_code=True,
            )
            return model

    module = SimpleNamespace(
        AutoModel=FakeAutoModel,
        AutoTokenizer=FakeAutoTokenizer,
    )
    monkeypatch.setattr(embeddings, "import_module", lambda name: module)
    provider = JinaEmbeddingProvider(
        model_revision="1" * 40,
        code_revision="2" * 40,
        local_files_only=True,
    )

    provider.embed_queries(["sorgu"])

    assert tokenizer_loads == [
        (
            DEFAULT_JINA_MODEL,
            {
                "trust_remote_code": True,
                "revision": "1" * 40,
                "local_files_only": True,
            },
        )
    ]


def test_missing_optional_backend_raises_explicit_unavailable_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def missing_import(module_name: str) -> Any:
        raise ModuleNotFoundError(module_name)

    monkeypatch.setattr(embeddings, "import_module", missing_import)
    provider = JinaEmbeddingProvider(local_files_only=True)

    with pytest.raises(EmbeddingUnavailableError, match="transformers"):
        provider.embed_queries(["sorgu"])


def test_jina_provider_defaults_to_verified_full_model_and_code_commits() -> None:
    provider = JinaEmbeddingProvider()

    assert provider.model_revision == JINA_EMBEDDINGS_V3_REVISION
    assert provider.code_revision == JINA_EMBEDDINGS_V3_CODE_REVISION
    assert len(provider.model_revision) == len(provider.code_revision) == 40


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("model_revision", None),
        ("model_revision", "main"),
        ("model_revision", "a" * 39),
        ("code_revision", "g" * 40),
        ("code_revision", "a" * 41),
    ],
)
def test_jina_provider_rejects_unpinned_or_non_commit_revisions(
    field: str,
    value: object,
) -> None:
    kwargs = {field: value}

    with pytest.raises(ValueError, match="40-hex"):
        JinaEmbeddingProvider(**kwargs)  # type: ignore[arg-type]


@pytest.mark.parametrize("dimension", [1023, 1025])
def test_jina_provider_rejects_wrong_vector_dimension(
    monkeypatch: pytest.MonkeyPatch,
    dimension: int,
) -> None:
    model = _FakeTransformersModel(dimension=dimension)
    _install_fake_transformers(monkeypatch, model)

    with pytest.raises(EmbeddingValidationError, match="yanlış boyutta"):
        JinaEmbeddingProvider().embed_passages(["hüküm"])


def test_jina_provider_rejects_non_finite_and_zero_vectors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    model = _FakeTransformersModel()
    _install_fake_transformers(monkeypatch, model)
    provider = JinaEmbeddingProvider()
    model.encode = lambda texts, **kwargs: [[float("nan"), *([0.0] * 1023)]]

    with pytest.raises(EmbeddingValidationError, match="sonlu değil"):
        provider.embed_queries(["sorgu"])

    model.encode = lambda texts, **kwargs: [[0.0] * 1024]
    with pytest.raises(EmbeddingValidationError, match="sıfır"):
        provider.embed_queries(["sorgu"])


def test_deterministic_hash_provider_is_explicit_test_only_and_task_aware() -> None:
    provider = DeterministicHashEmbeddingProvider(dimension=16, seed="fixed")

    first = provider.embed_queries(["aynı metin", "ikinci metin"])
    repeated = provider.embed_queries(["aynı metin", "ikinci metin"])
    passage = provider.embed_passages(["aynı metin"])

    assert isinstance(provider, EmbeddingProvider)
    assert provider.production_safe is False
    assert provider.backend.endswith("test-only")
    assert first == repeated
    assert first[0] != passage[0]
    assert all(len(vector) == 16 for vector in first)
    assert all(
        math.sqrt(sum(value * value for value in vector)) == pytest.approx(1.0)
        for vector in first
    )


def test_batch_api_rejects_bare_string_and_non_string_member() -> None:
    provider = DeterministicHashEmbeddingProvider(dimension=8)

    with pytest.raises(TypeError, match="tek bir str"):
        provider.embed_queries("batch değil")  # type: ignore[arg-type]
    with pytest.raises(TypeError, match=r"texts\[1\]"):
        provider.embed_passages(["metin", 42])  # type: ignore[list-item]


def test_hash_provider_refuses_production_usage() -> None:
    with pytest.raises(ValueError, match="yalnız test/geliştirme"):
        DeterministicHashEmbeddingProvider(usage="production")  # type: ignore[arg-type]
