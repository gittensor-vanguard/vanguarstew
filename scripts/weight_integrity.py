"""CLI: gate whether a replay artifact's blend weights are present and valid.

  python -m scripts.weight_integrity result.json
  python -m scripts.weight_integrity result.json --strict

With --strict the process exits non-zero when any scored slice's blend weights are missing,
negative/non-finite, or sum to a non-positive value.

Path / JSON failures exit 2 (via ``scripts.artifact_io``), distinct from the gating exit 1.
"""

from __future__ import annotations

import argparse
import json
import sys

from benchmark.weight_integrity import check_weight_integrity, integrity_headline
from scripts.artifact_io import load_artifact  # re-exported for tests / callers

__all__ = ["load_artifact", "main"]


def main() -> None:
    ap = argparse.ArgumentParser(description="Gate a replay artifact on blend-weight integrity")
    ap.add_argument("artifact", help="path to a run_eval --out JSON artifact")
    ap.add_argument("--strict", action="store_true",
                    help="exit 1 when the weight integrity gate fails (for CI gating)")
    args = ap.parse_args()

    artifact = load_artifact(args.artifact)

    result = check_weight_integrity(artifact)
    print(integrity_headline(result), file=sys.stderr)
    for check in result["checks"]:
        mark = "PASS" if check["passed"] else "FAIL"
        print(f"  [{mark}] {check['name']}: {check['detail']}", file=sys.stderr)

    print(json.dumps(result, indent=2))

    if args.strict and not result["passed"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
