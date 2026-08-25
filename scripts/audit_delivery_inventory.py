"""Create a deterministic inventory for data-bearing delivery files.

The script never deletes files. It fails closed when a tracked in-scope file
has no policy rule or when a review-required item exists in strict mode.
"""

from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_POLICY = ROOT / "data" / "manifests" / "delivery_policy.json"
DEFAULT_OUTPUT = ROOT / "reports" / "delivery_inventory.json"


def _tracked_files() -> list[str]:
    completed = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=ROOT,
        check=True,
        capture_output=True,
    )
    return sorted(
        item.decode("utf-8")
        for item in completed.stdout.split(b"\0")
        if item
    )


def _matches(path: str, pattern: str) -> bool:
    return fnmatch.fnmatchcase(path, pattern)


def build_inventory(policy_path: Path) -> dict[str, Any]:
    policy_bytes = policy_path.read_bytes()
    policy = json.loads(policy_bytes.decode("utf-8"))
    scope = policy["scope"]
    rules = policy["rules"]
    items: list[dict[str, Any]] = []
    unresolved: list[str] = []
    counts: dict[str, int] = {"include": 0, "exclude": 0, "review_required": 0}

    for relative_path in _tracked_files():
        if not any(_matches(relative_path, pattern) for pattern in scope):
            continue
        rule = next(
            (item for item in rules if _matches(relative_path, item["pattern"])),
            None,
        )
        if rule is None:
            unresolved.append(relative_path)
            continue
        path = ROOT / relative_path
        content = path.read_bytes()
        decision = rule["decision"]
        counts[decision] = counts.get(decision, 0) + 1
        items.append(
            {
                "path": relative_path,
                "bytes": len(content),
                "sha256": hashlib.sha256(content).hexdigest(),
                "data_class": rule["data_class"],
                "decision": decision,
                "license": rule["license"],
                "reason": rule["reason"],
            }
        )

    return {
        "schema_version": "1.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "policy": {
            "path": str(policy_path.resolve().relative_to(ROOT)),
            "sha256": hashlib.sha256(policy_bytes).hexdigest(),
        },
        "summary": {
            "tracked_in_scope": len(items) + len(unresolved),
            **counts,
            "unresolved": len(unresolved),
        },
        "unresolved_paths": unresolved,
        "items": items,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--policy", type=Path, default=DEFAULT_POLICY)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--strict", action="store_true")
    args = parser.parse_args()
    report = build_inventory(args.policy.resolve())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report["summary"], ensure_ascii=False))
    if report["unresolved_paths"]:
        return 2
    if args.strict and report["summary"]["review_required"]:
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
