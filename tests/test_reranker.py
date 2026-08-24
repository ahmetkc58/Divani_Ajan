from __future__ import annotations

from types import SimpleNamespace

import pytest

import karayol_agent.retrieval.reranker as reranker_module
from karayol_agent.retrieval.hybrid import HybridRetriever
from karayol_agent.retrieval.reranker import (
    JinaRerankerProvider,
    RerankerUnavailableError,
    RerankerValidationError,
    RerankingRetriever,
)
from karayol_agent.schemas import LegislationChunk, SearchHit


def _chunk(chunk_id: str, text: str) -> LegislationChunk:
    return LegislationChunk(
        chunk_id=chunk_id,
        title="Sentetik Kural",
        section="Test",
        article="Kural 1",
        text=text,
        context_text=f"Sentetik Kural > Test > {chunk_id}",
        source="synthetic.json",
        source_kind="synthetic",
        status="sentetik_demo_kurali",
    )


class _Ranked:
    def __init__(self, hits: list[SearchHit]) -> None:
        self.hits = hits

    def search(self, query: str, top_k: int = 5) -> list[SearchHit]:
        return self.hits[:top_k]


class _Reranker:
    model_name = "test/reranker"
    revision = "weights"
    code_revision = "code"

    def score(self, query: str, passages: list[str]) -> list[float]:
        return [0.1, 0.9]


def test_reranking_reorders_candidates_and_preserves_rrf_evidence() -> None:
    first = SearchHit(chunk=_chunk("A", "asfalt"), score=2.0)
    second = SearchHit(chunk=_chunk("B", "bakım"), score=1.0)
    hybrid = HybridRetriever(_Ranked([first, second]), channel_top_n=20)
    retriever = RerankingRetriever(hybrid, _Reranker(), candidate_top_k=2)

    response = retriever.search_with_diagnostics("onarım", top_k=2)

    assert [hit.chunk.chunk_id for hit in response.hits] == ["B", "A"]
    assert response.hits[0].fusion_method == "rrf+reranker:test/reranker"
    assert response.reranker_candidate_count == 2
    assert response.diagnostics.lexical_candidate_count == 2


def test_jina_reranker_is_lazy_and_pins_custom_code(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: dict[str, object] = {}

    class _Model:
        def to(self, device: str) -> "_Model":
            observed["device"] = device
            return self

        def eval(self) -> None:
            observed["eval"] = True

        def predict(self, pairs: list[tuple[str, str]], batch_size: int) -> list[float]:
            observed["pairs"] = pairs
            observed["batch_size"] = batch_size
            return [0.8, 0.2]

    class _Auto:
        @staticmethod
        def from_pretrained(model_name: str, **kwargs: object) -> _Model:
            observed["model_name"] = model_name
            observed["kwargs"] = kwargs
            return _Model()

    monkeypatch.setattr(
        reranker_module,
        "import_module",
        lambda name: SimpleNamespace(AutoModelForSequenceClassification=_Auto),
    )
    provider = JinaRerankerProvider(
        revision="1" * 40,
        code_revision="2" * 40,
        local_files_only=True,
        batch_size=2,
    )

    assert provider.is_loaded is False
    scores = provider.score("sorgu", ["bir", "iki"])

    assert scores == [0.8, 0.2]
    assert provider.is_loaded is True
    assert observed["kwargs"] == {
        "trust_remote_code": True,
        "local_files_only": True,
        "torch_dtype": "auto",
        "use_flash_attn": False,
        "revision": "1" * 40,
        "code_revision": "2" * 40,
    }


def test_reranker_remote_and_lazy_tokenizers_share_exact_offline_pin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tokenizer_loads: list[dict[str, object]] = []

    class _Tokenizer:
        @classmethod
        def from_pretrained(cls, model_name: str, **kwargs: object) -> object:
            tokenizer_loads.append({"model": model_name, **kwargs})
            return object()

    class _Model:
        def to(self, device: str) -> "_Model":
            return self

        def eval(self) -> None:
            return None

        def predict(
            self,
            pairs: list[tuple[str, str]],
            batch_size: int,
        ) -> list[float]:
            assert hasattr(self, "_tokenizer")
            return [0.75]

    class _Auto:
        @staticmethod
        def from_pretrained(model_name: str, **kwargs: object) -> _Model:
            # Reproduce remote model construction dropping the outer pin.
            _Tokenizer.from_pretrained(model_name, trust_remote_code=True)
            return _Model()

    module = SimpleNamespace(
        AutoModelForSequenceClassification=_Auto,
        AutoTokenizer=_Tokenizer,
    )
    monkeypatch.setattr(reranker_module, "import_module", lambda name: module)
    provider = JinaRerankerProvider(
        revision="1" * 40,
        code_revision="2" * 40,
        local_files_only=True,
    )

    assert provider.score("sorgu", ["hüküm"]) == [0.75]
    assert len(tokenizer_loads) == 2
    assert all(load["revision"] == "1" * 40 for load in tokenizer_loads)
    assert all(load["local_files_only"] is True for load in tokenizer_loads)


def test_reranker_rejects_wrong_score_count() -> None:
    class _Bad(_Reranker):
        def score(self, query: str, passages: list[str]) -> list[float]:
            return [0.5]

    hybrid = HybridRetriever(
        _Ranked(
            [
                SearchHit(chunk=_chunk("A", "asfalt"), score=2.0),
                SearchHit(chunk=_chunk("B", "bakım"), score=1.0),
            ]
        )
    )

    with pytest.raises(RerankerValidationError, match="aday sayısıyla"):
        RerankingRetriever(hybrid, _Bad(), candidate_top_k=2).search("onarım", 2)


def test_zero_top_k_does_not_invoke_any_retrieval_channel() -> None:
    class _NeverCalled:
        def search(self, query: str, top_k: int = 5) -> list[SearchHit]:
            raise AssertionError("zero-result request must not touch retrieval")

    hybrid = HybridRetriever(_NeverCalled(), _NeverCalled(), channel_top_n=7, rrf_k=42)
    response = RerankingRetriever(hybrid, _Reranker()).search_with_diagnostics(
        "onarım",
        top_k=0,
    )

    assert response.hits == []
    assert response.reranker_candidate_count == 0
    assert response.diagnostics.channel_top_n == 7
    assert response.diagnostics.rrf_k == 42


def test_internal_type_error_is_not_retried(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0

    class _Model:
        def to(self, device: str) -> "_Model":
            return self

        def eval(self) -> None:
            return None

        def predict(
            self,
            pairs: list[tuple[str, str]],
            batch_size: int,
        ) -> list[float]:
            nonlocal calls
            calls += 1
            raise TypeError("model implementation failed")

    class _Auto:
        @staticmethod
        def from_pretrained(model_name: str, **kwargs: object) -> _Model:
            return _Model()

    monkeypatch.setattr(
        reranker_module,
        "import_module",
        lambda name: SimpleNamespace(AutoModelForSequenceClassification=_Auto),
    )
    provider = JinaRerankerProvider()

    with pytest.raises(RerankerUnavailableError, match="çıkarımı çalıştırılamadı"):
        provider.score("sorgu", ["metin"])

    assert calls == 1


@pytest.mark.parametrize(
    ("field", "value"),
    [("revision", "main"), ("code_revision", "g" * 40)],
)
def test_reranker_rejects_mutable_or_non_hex_remote_code_pins(
    field: str,
    value: str,
) -> None:
    with pytest.raises(ValueError, match="40-hex"):
        JinaRerankerProvider(**{field: value})
