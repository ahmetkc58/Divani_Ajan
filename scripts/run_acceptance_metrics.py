"""Generate one reproducible regression and latency acceptance report."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import subprocess
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from karayol_agent.config import Settings
from karayol_agent.evaluation import EvaluationService
from karayol_agent.llm import LLMConfig, LLMProviderName, StructuredLLMGateway
from karayol_agent.orchestrator import EvrakOrchestrator


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATASET = ROOT / "data" / "synthetic_gold.json"
DEFAULT_OUTPUT = ROOT / "reports" / "acceptance_metrics.json"


def percentile(values: list[float], percentile_value: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    rank = max(1, math.ceil(percentile_value * len(ordered)))
    return ordered[min(rank - 1, len(ordered) - 1)]


def _git_revision() -> dict[str, Any]:
    try:
        commit = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, check=True,
            capture_output=True, text=True,
        ).stdout.strip()
        dirty = bool(subprocess.run(
            ["git", "status", "--porcelain"], cwd=ROOT, check=True,
            capture_output=True, text=True,
        ).stdout.strip())
    except (OSError, subprocess.CalledProcessError):
        return {"commit": None, "dirty": None}
    return {"commit": commit, "dirty": dirty}


def _representative_records(dataset: dict[str, Any]) -> list[dict[str, str]]:
    records = dataset["data"]
    standard = next(
        record for record in records if "challenge_paraphrase" not in record["tags"]
    )
    paraphrase = next(
        record for record in records if "challenge_paraphrase" in record["tags"]
    )
    unknown = {
        "record_id": "NEAR-MISS-UNKNOWN",
        "text": "Gönderen: Test Kullanıcısı\nKonu: Tanımsız işlem\nGenel açıklama sunulmuştur.",
    }
    return [standard, paraphrase, unknown]


def run(dataset_path: Path, *, repetitions: int) -> dict[str, Any]:
    dataset_bytes = dataset_path.read_bytes()
    dataset = json.loads(dataset_bytes.decode("utf-8"))
    evaluator = EvaluationService(
        legislation_path=ROOT / "data" / "synthetic_legislation.json",
        units_path=ROOT / "data" / "synthetic_units.json",
    )
    evaluation = evaluator.evaluate(dataset_path).model_dump(mode="json")

    latency_results: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="karayol-acceptance-") as temp_dir:
        temp_root = Path(temp_dir)
        orchestrator = EvrakOrchestrator(
            Settings(
                project_root=ROOT,
                data_dir=ROOT / "data",
                templates_dir=ROOT / "templates",
                output_dir=temp_root / "output",
                runtime_dir=temp_root / "runtime",
            ),
            llm_gateway=StructuredLLMGateway(
                LLMConfig(
                    provider=LLMProviderName.GROQ,
                    model="llama-3.1-8b-instant",
                    api_key=None,
                    base_url="https://api.groq.com/openai/v1",
                )
            ),
        )
        for record in _representative_records(dataset):
            durations: list[float] = []
            failures: list[str] = []
            for _ in range(repetitions):
                started = time.perf_counter()
                try:
                    orchestrator.process_text(
                        record["text"],
                        source_name=f"acceptance-{record['record_id']}.txt",
                        compile_pdf=False,
                    )
                except Exception as exc:  # report the run; do not hide it
                    failures.append(type(exc).__name__)
                durations.append((time.perf_counter() - started) * 1000)
            latency_results.append(
                {
                    "scenario": record["record_id"],
                    "repetitions": repetitions,
                    "successes": repetitions - len(failures),
                    "failures": failures,
                    "p50_ms": round(percentile(durations, 0.50), 2),
                    "p95_ms": round(percentile(durations, 0.95), 2),
                    "max_ms": round(max(durations), 2),
                }
            )

    return {
        "schema_version": "1.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "claim_scope": "engineering_regression_not_independent_blind_evaluation",
        "independent_blind_evaluation": False,
        "dataset": {
            "path": str(dataset_path.resolve().relative_to(ROOT)),
            "sha256": hashlib.sha256(dataset_bytes).hexdigest(),
            "record_count": len(dataset["data"]),
        },
        "code": _git_revision(),
        "evaluation": evaluation,
        "latency": latency_results,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--repetitions", type=int, default=20)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    if args.repetitions < 20:
        parser.error("repetitions en az 20 olmalıdır")
    report = run(args.dataset.resolve(), repetitions=args.repetitions)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({
        "classification_accuracy": report["evaluation"]["metrics"]["classification_accuracy"]["value"],
        "latency": report["latency"],
    }, ensure_ascii=False))
    return 0 if all(not item["failures"] for item in report["latency"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
