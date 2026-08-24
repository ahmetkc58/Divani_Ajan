"""Measure intent-and-visible-text relevance against a running local API.

This is an engineering evaluation for the fixed competition snapshot.  It is
not a legal-currentness or legal-applicability validation.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import subprocess
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATASET = ROOT / "data" / "evaluation" / "competition_snapshot_relevance_v1.json"


def _post_json(url: str, payload: dict[str, Any]) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=600) as response:
        return json.load(response)


def _get_json(url: str) -> dict[str, Any]:
    with urllib.request.urlopen(url, timeout=60) as response:
        return json.load(response)


def _dcg(grades: list[int]) -> float:
    return sum(
        (2**grade - 1) / math.log2(rank + 1)
        for rank, grade in enumerate(grades, start=1)
    )


def _query_metrics(
    query: dict[str, Any], ranked_ids: list[str], *, k: int, min_grade: int
) -> dict[str, Any]:
    judgments = {
        item["chunk_id"]: item for item in query.get("judgments", [])
    }
    strict_ids = {
        chunk_id
        for chunk_id, item in judgments.items()
        if int(item["grade"]) >= min_grade
    }
    top_ids = ranked_ids[:k]
    grades = [int(judgments.get(chunk_id, {}).get("grade", 0)) for chunk_id in top_ids]
    strict_flags = [grade >= min_grade for grade in grades]
    relevant_count = sum(strict_flags)
    first_relevant_rank = next(
        (rank for rank, relevant in enumerate(strict_flags, start=1) if relevant),
        None,
    )
    ideal_grades = sorted(
        (int(item["grade"]) for item in judgments.values()), reverse=True
    )[:k]
    ideal_dcg = _dcg(ideal_grades)
    strict_families = {
        item["provision_family"]
        for item in judgments.values()
        if int(item["grade"]) >= min_grade
    }
    returned_families = {
        judgments[chunk_id]["provision_family"]
        for chunk_id in top_ids
        if chunk_id in strict_ids
    }
    hard_negatives = set(query.get("hard_negative_chunk_ids", []))
    return {
        "returned_count": len(top_ids),
        "strict_relevant_returned": relevant_count,
        "precision_at_returned": (
            relevant_count / len(top_ids) if top_ids else 0.0
        ),
        "precision_at_k": relevant_count / k,
        "recall_at_k": (
            len(set(top_ids) & strict_ids) / len(strict_ids) if strict_ids else 0.0
        ),
        "family_recall_at_k": (
            len(returned_families) / len(strict_families)
            if strict_families
            else 0.0
        ),
        "reciprocal_rank": (
            1.0 / first_relevant_rank if first_relevant_rank is not None else 0.0
        ),
        "ndcg_at_k": _dcg(grades) / ideal_dcg if ideal_dcg else 0.0,
        "hard_negative_count_at_k": len(set(top_ids) & hard_negatives),
        "grades_by_rank": grades,
        "first_relevant_rank": first_relevant_rank,
    }


def _mean(items: list[dict[str, Any]], key: str) -> float:
    return sum(float(item[key]) for item in items) / len(items) if items else 0.0


def _report_path(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(ROOT))
    except ValueError:
        return str(path.resolve())


def _git_revision() -> dict[str, Any]:
    try:
        revision = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        dirty = bool(
            subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=ROOT,
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
        )
    except (OSError, subprocess.CalledProcessError):
        return {"git_commit": None, "git_dirty": None}
    return {"git_commit": revision or None, "git_dirty": dirty}


def run(base_url: str, dataset_path: Path, variant: str) -> dict[str, Any]:
    raw_dataset = dataset_path.read_bytes()
    dataset = json.loads(raw_dataset.decode("utf-8"))
    readiness = _get_json(f"{base_url.rstrip('/')}/ready")
    expected_fingerprint = dataset["corpus"]["fingerprint"]
    actual_fingerprint = readiness.get("corpus_fingerprint")
    if actual_fingerprint != expected_fingerprint:
        raise RuntimeError(
            "Canlı korpus fingerprint'i gold setiyle uyuşmuyor: "
            f"expected={expected_fingerprint}, actual={actual_fingerprint}"
        )

    k = int(dataset["k"])
    min_grade = int(dataset["binary_relevance_min_grade"])
    results: list[dict[str, Any]] = []
    for query in dataset["queries"]:
        state = _post_json(
            f"{base_url.rstrip('/')}/v1/process/text",
            {
                "text": query["input_text"],
                "source_name": f"relevance_{query['query_id']}.txt",
                "compile_pdf": False,
            },
        )
        hits = state.get("search_hits") or []
        ranked_ids = [hit["chunk"]["chunk_id"] for hit in hits]
        references = state.get("verified_references") or []
        verified_ids = [
            item["chunk_id"] for item in references if item.get("verified")
        ]
        diagnostics = state.get("retrieval_diagnostics") or {}
        metrics = _query_metrics(query, ranked_ids, k=k, min_grade=min_grade)
        expected_document_type = query["expected_document_type"]
        actual_document_type = (state.get("analysis") or {}).get("document_type")
        expected_profile = query.get("profile")
        actual_profile = diagnostics.get("relevance_profile")
        expected_abstain = bool(query.get("expected_abstain", False))
        actual_abstain = not ranked_ids
        classification_correct = actual_document_type == expected_document_type
        profile_correct = actual_profile == expected_profile
        abstention_correct = actual_abstain == expected_abstain
        relevance_metadata_valid = (
            not hits
            if expected_abstain
            else bool(hits)
            and all(
                hit.get("relevance_accepted") is True
                and hit.get("relevance_profile") == expected_profile
                for hit in hits
            )
        )
        if expected_abstain:
            case_passed = (
                classification_correct
                and profile_correct
                and abstention_correct
                and not verified_ids
                and diagnostics.get("relevance_abstained") is True
                and diagnostics.get("relevance_query_supported") is False
            )
        else:
            case_passed = (
                classification_correct
                and profile_correct
                and abstention_correct
                and relevance_metadata_valid
                and metrics["precision_at_returned"] == 1.0
                and metrics["recall_at_k"] == 1.0
                and set(verified_ids) == set(ranked_ids)
            )
        results.append(
            {
                "query_id": query["query_id"],
                "profile": query["profile"],
                "document_id": state.get("document_id"),
                "expected_document_type": expected_document_type,
                "actual_document_type": actual_document_type,
                "expected_profile": expected_profile,
                "actual_profile": actual_profile,
                "expected_abstain": expected_abstain,
                "actual_abstain": actual_abstain,
                "classification_correct": classification_correct,
                "profile_correct": profile_correct,
                "abstention_correct": abstention_correct,
                "relevance_metadata_valid": relevance_metadata_valid,
                "case_passed": case_passed,
                "ranked_chunk_ids": ranked_ids,
                "verified_chunk_ids": verified_ids,
                "ranked_results": [
                    {
                        "rank": rank,
                        "chunk_id": hit["chunk"]["chunk_id"],
                        "title": hit["chunk"].get("title"),
                        "article": hit["chunk"].get("article"),
                        "text": hit["chunk"].get("text"),
                        "retrieval_score": hit.get("score"),
                        "relevance_score": hit.get("relevance_score"),
                        "relevance_accepted": hit.get("relevance_accepted"),
                        "relevance_reasons": hit.get("relevance_reasons") or [],
                    }
                    for rank, hit in enumerate(hits[:k], start=1)
                ],
                "retrieval_diagnostics": diagnostics,
                "metrics": metrics,
            }
        )

    metric_keys = (
        "precision_at_returned",
        "precision_at_k",
        "recall_at_k",
        "family_recall_at_k",
        "reciprocal_rank",
        "ndcg_at_k",
        "hard_negative_count_at_k",
    )
    answerable_results = [
        result for result in results if not result["expected_abstain"]
    ]
    query_metrics = [result["metrics"] for result in answerable_results]
    verified_relevant = 0
    verified_total = 0
    for result, query in zip(results, dataset["queries"], strict=True):
        if result["expected_abstain"]:
            continue
        strict_ids = {
            item["chunk_id"]
            for item in query.get("judgments", [])
            if int(item["grade"]) >= min_grade
        }
        verified_ids = result["verified_chunk_ids"]
        verified_total += len(verified_ids)
        verified_relevant += len(set(verified_ids) & strict_ids)
    control_metrics = {
        "classification_accuracy": sum(
            result["classification_correct"] for result in results
        )
        / len(results),
        "profile_accuracy": sum(result["profile_correct"] for result in results)
        / len(results),
        "abstention_accuracy": sum(
            result["abstention_correct"] for result in results
        )
        / len(results),
        "false_answer_count": sum(
            result["expected_abstain"] and not result["actual_abstain"]
            for result in results
        ),
        "false_abstention_count": sum(
            not result["expected_abstain"] and result["actual_abstain"]
            for result in results
        ),
        "verified_relevance_precision": (
            verified_relevant / verified_total if verified_total else 0.0
        ),
        "case_pass_rate": sum(result["case_passed"] for result in results)
        / len(results),
    }
    return {
        "schema_version": "2.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "variant": variant,
        "production_legal_evidence": False,
        "dataset": {
            "path": _report_path(dataset_path),
            "sha256": hashlib.sha256(raw_dataset).hexdigest(),
            "name": dataset["dataset_name"],
            "version": dataset["version"],
        },
        "corpus": dataset["corpus"],
        "runtime": {
            "base_url": base_url,
            "retrieval_mode": readiness.get("retrieval_mode"),
            "collection": readiness.get("collection"),
            "corpus_fingerprint": actual_fingerprint,
            "embedding_model": readiness.get("embedding_model"),
            "embedding_dimension": readiness.get("embedding_dimension"),
            "currentness_verified": readiness.get("currentness_verified"),
            "legal_reliance_allowed": readiness.get("legal_reliance_allowed"),
            "observed_relevance_thresholds": sorted(
                {
                    result["retrieval_diagnostics"].get("relevance_threshold")
                    for result in results
                    if result["retrieval_diagnostics"].get("relevance_threshold")
                    is not None
                }
            ),
            "observed_candidate_top_k": sorted(
                {
                    result["retrieval_diagnostics"].get(
                        "relevance_candidate_top_k"
                    )
                    for result in answerable_results
                    if result["retrieval_diagnostics"].get(
                        "relevance_candidate_top_k"
                    )
                    is not None
                }
            ),
        },
        "code": _git_revision(),
        "passed": all(result["case_passed"] for result in results),
        "aggregate": {
            **{key: _mean(query_metrics, key) for key in metric_keys},
            **control_metrics,
        },
        "query_count": len(results),
        "answerable_query_count": len(answerable_results),
        "no_answer_query_count": len(results) - len(answerable_results),
        "results": results,
        "limitations": dataset.get("limitations", []),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8010")
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--variant", required=True)
    parser.add_argument("--output", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = run(args.base_url, args.dataset.resolve(), args.variant)
    rendered = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output is not None:
        args.output.resolve().parent.mkdir(parents=True, exist_ok=True)
        args.output.resolve().write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
