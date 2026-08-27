from pathlib import Path

import pytest

from karayol_agent.config import Settings


def test_embedded_qdrant_path_env_resolves_under_project_root(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.delenv("QDRANT_URL", raising=False)
    monkeypatch.setenv("KARAYOL_QDRANT_PATH", "runtime/qdrant-local")

    configured = Settings(project_root=tmp_path)

    assert configured.qdrant_url is None
    assert configured.qdrant_path == (tmp_path / "runtime/qdrant-local").resolve()


def test_qdrant_server_url_behavior_is_preserved(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("QDRANT_URL", "http://qdrant.test:6333")
    monkeypatch.delenv("KARAYOL_QDRANT_PATH", raising=False)

    configured = Settings()

    assert configured.qdrant_url == "http://qdrant.test:6333"
    assert configured.qdrant_path is None


def test_qdrant_url_and_embedded_path_are_mutually_exclusive(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("QDRANT_URL", "http://qdrant.test:6333")
    monkeypatch.setenv("KARAYOL_QDRANT_PATH", "runtime/qdrant-local")

    with pytest.raises(ValueError, match="aynı anda"):
        Settings()


def test_competition_snapshot_mode_uses_separate_corpus_and_collection(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.delenv("QDRANT_URL", raising=False)
    monkeypatch.delenv("KARAYOL_QDRANT_PATH", raising=False)
    monkeypatch.delenv("KARAYOL_QDRANT_COLLECTION", raising=False)
    monkeypatch.setenv("KARAYOL_CORPUS_MODE", "competition_snapshot")
    monkeypatch.setenv(
        "KARAYOL_COMPETITION_SNAPSHOT_PATH",
        "data/processed/competition_snapshot.json",
    )

    configured = Settings(project_root=tmp_path)

    assert configured.corpus_mode == "competition_snapshot"
    assert configured.qdrant_collection == "competition_snapshot_chunks_v1"
    assert configured.retrieval_corpus_path == (
        tmp_path / "data/processed/competition_snapshot.json"
    )


def test_unknown_corpus_mode_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("KARAYOL_CORPUS_MODE", "unsafe")

    with pytest.raises(ValueError, match="KARAYOL_CORPUS_MODE"):
        Settings()


def test_cuda_embedding_device_is_normalized(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("KARAYOL_EMBEDDING_DEVICE", "CUDA:0")

    assert Settings().embedding_device == "cuda:0"


def test_invalid_embedding_device_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("KARAYOL_EMBEDDING_DEVICE", "gpu")

    with pytest.raises(ValueError, match="KARAYOL_EMBEDDING_DEVICE"):
        Settings()
