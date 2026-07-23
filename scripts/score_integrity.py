"""CLI: gate whether a replay artifact's composite score is internally consistent.

  python -m scripts.score_integrity result.json
  python -m scripts.score_integrity result.json --tolerance 0.005 --strict

``result.json`` is a ``run_eval --out`` artifact. With --strict the process exits non-zero when
the score integrity gate fails.
"""

from __future__ import annotations

import argparse
import json
import sys

from benchmark.score_integrity import (
    DEFAULT_TOLERANCE,
    check_score_integrity,
    integrity_headline,
)
from scripts.artifact_io import load_artifact  # re-exported for tests / callers

__all__ = ["load_artifact", "main"]

def main() -> None:
    ap = argparse.ArgumentParser(description="Gate a replay artifact on composite-score integrity")
    ap.add_argument("artifact", help="path to a run_eval --out JSON artifact")
    ap.add_argument("--tolerance", type=float, default=DEFAULT_TOLERANCE,
                    help=f"max allowed composite-vs-blend delta (default {DEFAULT_TOLERANCE})")
    ap.add_argument("--strict", action="store_true",
                    help="exit 1 when the integrity gate fails (for CI gating)")
    args = ap.parse_args()

    artifact = load_artifact(args.artifact)

    result = check_score_integrity(artifact, tolerance=args.tolerance)
    print(integrity_headline(result), file=sys.stderr)
    for check in result["checks"]:
        mark = "PASS" if check["passed"] else "FAIL"
        print(f"  [{mark}] {check['name']}: {check['detail']}", file=sys.stderr)

    print(json.dumps(result, indent=2))

    if args.strict and not result["passed"]:
        sys.exit(1)

if __name__ == "__main__":
    main()
