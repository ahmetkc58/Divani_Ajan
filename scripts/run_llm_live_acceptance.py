"""Repeatable live acceptance for the configured structured LLM provider."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
BASE_URL = os.getenv("KARAYOL_ACCEPTANCE_BASE_URL", "http://127.0.0.1:8010").rstrip(
    "/"
)
MAX_ATTEMPTS = 3


def request_json(path: str, *, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    body = None
    method = "GET"
    headers = {"Accept": "application/json"}
    if payload is not None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        method = "POST"
        headers["Content-Type"] = "application/json; charset=utf-8"
    request = Request(BASE_URL + path, data=body, headers=headers, method=method)
    try:
        with urlopen(request, timeout=75) as response:  # noqa: S310 - fixed localhost
            result = json.loads(response.read().decode("utf-8"))
    except (HTTPError, URLError, TimeoutError) as exc:
        raise RuntimeError(f"Yerel kabul isteği başarısız: {type(exc).__name__}") from exc
    if not isinstance(result, dict):
        raise RuntimeError("Yerel kabul yanıtı JSON nesnesi değil.")
    return result


def llm_steps(state: dict[str, Any]) -> list[dict[str, Any]]:
    trace = state.get("llm_trace")
    if not isinstance(trace, dict):
        return []
    steps = trace.get("steps")
    if not isinstance(steps, list):
        return []
    return [step for step in steps if isinstance(step, dict)]


def live_success(state: dict[str, Any]) -> bool:
    steps = llm_steps(state)
    return (
        len(steps) == 2
        and [step.get("role") for step in steps]
        == ["document_understanding", "adjudicator"]
        and [step.get("status") for step in steps] == ["success", "success"]
        and [step.get("data_classification") for step in steps]
        == ["synthetic", "public"]
        and all(step.get("network_attempted") is True for step in steps)
    )


def retryable_failure(state: dict[str, Any]) -> bool:
    failed = [step for step in llm_steps(state) if step.get("status") != "success"]
    return bool(failed) and all(step.get("retryable") is True for step in failed)


def main() -> int:
    ready = request_json("/ready")
    expected_provider = os.getenv("KARAYOL_LLM_PROVIDER", "ollama")
    expected_model = os.getenv("KARAYOL_LLM_MODEL", "qwen2.5:0.5b")
    required_ready = {
        "ready": True,
        "llm_enabled": True,
        "llm_provider": expected_provider,
        "llm_model": expected_model,
        "evidence_graph_ready": True,
    }
    for field, expected in required_ready.items():
        if ready.get(field) != expected:
            raise RuntimeError(f"Readiness alanı beklenenden farklı: {field}")

    fixtures = json.loads(
        (ROOT / "data" / "synthetic_ui_fixtures.json").read_text("utf-8")
    )
    record = fixtures["records"][0]
    state: dict[str, Any] | None = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        state = request_json(
            "/v1/process/text",
            payload={
                "text": record["text"],
                "source_name": record["source_name"],
                "compile_pdf": False,
            },
        )
        if live_success(state):
            break
        if attempt == MAX_ATTEMPTS or not retryable_failure(state):
            raise RuntimeError("LLM rolleri canlı kabul sözleşmesini geçmedi.")
        time.sleep(attempt * 2)
    assert state is not None

    altered = request_json(
        "/v1/process/text",
        payload={
            "text": record["text"] + "\nKullanıcı tarafından değiştirilmiş satır.",
            "source_name": "degistirilmis-demo.txt",
            "compile_pdf": False,
        },
    )
    altered_steps = llm_steps(altered)
    if expected_provider == "ollama":
        if (
            not altered_steps
            or any(step.get("status") != "success" for step in altered_steps)
            or any(step.get("local_execution") is not True for step in altered_steps)
            or any(step.get("network_attempted") is not True for step in altered_steps)
        ):
            raise RuntimeError("Değiştirilmiş fixture yerel Ollama ile işlenemedi.")
        altered_handling = "processed_locally"
    else:
        if (
            not altered_steps
            or any(step.get("status") != "policy_rejected" for step in altered_steps)
            or any(step.get("network_attempted") is True for step in altered_steps)
        ):
            raise RuntimeError("Değiştirilmiş fixture haricî ağdan önce engellenmedi.")
        altered_handling = "blocked_before_external_network"

    summary = {
        "status": "passed",
        "provider": state["llm_trace"]["provider"],
        "model": state["llm_trace"]["model"],
        "live_steps": [
            {
                "role": step["role"],
                "status": step["status"],
                "classification": step["data_classification"],
                "network_attempted": step["network_attempted"],
                "decision_applied": step.get("decision_applied"),
            }
            for step in llm_steps(state)
        ],
        "altered_fixture_handling": altered_handling,
        "document_id": state["document_id"],
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
