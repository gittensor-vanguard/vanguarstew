"""CLI: gate a candidate run against a baseline run for regressions.

  python -m scripts.regression baseline.json candidate.json
  python -m scripts.regression baseline.json candidate.json --max-composite-drop 0.01 --strict

Both are ``run_eval --out`` artifacts (``baseline`` = last accepted run, ``candidate`` = this
run). With --strict, exits non-zero when the candidate regressed.

Path / JSON failures exit 2 (via ``scripts.artifact_io``), distinct from the gating exit 1.
"""

from __future__ import annotations

import argparse
import json
import sys

from benchmark.regression import (
    DEFAULT_MAX_COMPOSITE_DROP,
    DEFAULT_MAX_DISAGREEMENT_INCREASE,
    check_regression,
    regression_headline,
)
from scripts.artifact_io import load_artifact  # re-exported for tests / callers

__all__ = ["load_artifact", "main"]


def main() -> None:
    ap = argparse.ArgumentParser(description="Gate a candidate run against a baseline for regressions")
    ap.add_argument("baseline", help="the last accepted run_eval --out JSON artifact")
    ap.add_argument("candidate", help="this run's run_eval --out JSON artifact")
    ap.add_argument("--max-composite-drop", type=float, default=DEFAULT_MAX_COMPOSITE_DROP,
                    help=f"max allowed composite drop (default {DEFAULT_MAX_COMPOSITE_DROP})")
    ap.add_argument("--max-disagreement-increase", type=float,
                    default=DEFAULT_MAX_DISAGREEMENT_INCREASE,
                    help=f"max allowed judge disagreement rise (default {DEFAULT_MAX_DISAGREEMENT_INCREASE})")
    ap.add_argument("--strict", action="store_true",
                    help="exit 1 when the candidate regressed (for CI gating)")
    args = ap.parse_args()

    candidate = load_artifact(args.candidate)
    baseline = load_artifact(args.baseline)

    result = check_regression(
        candidate, baseline,
        max_composite_drop=args.max_composite_drop,
        max_disagreement_increase=args.max_disagreement_increase,
    )
    print(regression_headline(result), file=sys.stderr)
    for check in result["checks"]:
        mark = "PASS" if check["passed"] else "FAIL"
        print(f"  [{mark}] {check['name']}: {check['detail']}", file=sys.stderr)

    print(json.dumps(result, indent=2))

    if args.strict and not result["passed"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
