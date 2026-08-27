from __future__ import annotations

import pytest

from karayol_agent.config import Settings
from karayol_agent.revision_pins import (
    JINA_EMBEDDINGS_V3_CODE_REVISION,
    JINA_EMBEDDINGS_V3_REVISION,
)


def test_settings_defaults_use_verified_embedding_commits() -> None:
    configured = Settings()

    assert configured.embedding_revision == JINA_EMBEDDINGS_V3_REVISION
    assert configured.embedding_code_revision == JINA_EMBEDDINGS_V3_CODE_REVISION
    assert configured.min_retrieval_score == 0.20


@pytest.mark.parametrize(
    "environment_name",
    [
        "KARAYOL_EMBEDDING_REVISION",
        "KARAYOL_EMBEDDING_CODE_REVISION",
        "KARAYOL_RERANKER_REVISION",
        "KARAYOL_RERANKER_CODE_REVISION",
    ],
)
def test_settings_rejects_non_commit_revision_environment_overrides(
    monkeypatch: pytest.MonkeyPatch,
    environment_name: str,
) -> None:
    monkeypatch.setenv(environment_name, "main")

    with pytest.raises(ValueError, match="40-hex"):
        Settings()


def test_settings_normalizes_full_commit_environment_overrides(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("KARAYOL_EMBEDDING_REVISION", "A" * 40)
    monkeypatch.setenv("KARAYOL_EMBEDDING_CODE_REVISION", "B" * 40)
    monkeypatch.setenv("KARAYOL_RERANKER_REVISION", "C" * 40)
    monkeypatch.setenv("KARAYOL_RERANKER_CODE_REVISION", "D" * 40)

    configured = Settings()

    assert configured.embedding_revision == "a" * 40
    assert configured.embedding_code_revision == "b" * 40
    assert configured.reranker_revision == "c" * 40
    assert configured.reranker_code_revision == "d" * 40


@pytest.mark.parametrize("value", ["-0.01", "1.01", "nan"])
def test_settings_rejects_invalid_dense_evidence_threshold(
    monkeypatch: pytest.MonkeyPatch,
    value: str,
) -> None:
    monkeypatch.setenv("KARAYOL_MIN_RETRIEVAL_SCORE", value)

    with pytest.raises(ValueError, match="0 ile 1"):
        Settings()
