"""CLI: gate whether a candidate run improved enough over a baseline to adopt it.

  python -m scripts.improvement baseline.json candidate.json
  python -m scripts.improvement baseline.json candidate.json --min-gain 0.05 --strict

Both are ``run_eval --out`` artifacts (``baseline`` = current best, ``candidate`` = new run).
With --strict, exits non-zero when the candidate did not improve by at least the margin.
"""

from __future__ import annotations

import argparse
import json
import sys

from benchmark.improvement import (
    DEFAULT_MIN_GAIN,
    check_improvement,
    improvement_headline,
)


def load_artifact(path: str) -> dict:
    """Load a JSON-object artifact, exiting with a clear message on a bad path or bad JSON."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        print(f"artifact not found: {path}", file=sys.stderr)
        raise SystemExit(2) from None
    except json.JSONDecodeError as exc:
        print(f"artifact is not valid JSON ({path}): {exc}", file=sys.stderr)
        raise SystemExit(2) from None
    if not isinstance(data, dict):
        print(f"artifact must be a JSON object: {path}", file=sys.stderr)
        raise SystemExit(2)
    return data


def main() -> None:
    ap = argparse.ArgumentParser(description="Gate whether a candidate improved over a baseline")
    ap.add_argument("baseline", help="the current-best run_eval --out JSON artifact")
    ap.add_argument("candidate", help="the new run's run_eval --out JSON artifact")
    ap.add_argument("--min-gain", type=float, default=DEFAULT_MIN_GAIN,
                    help=f"minimum composite gain to adopt (default {DEFAULT_MIN_GAIN})")
    ap.add_argument("--strict", action="store_true",
                    help="exit 1 when the candidate did not improve enough (for CI gating)")
    args = ap.parse_args()

    result = check_improvement(load_artifact(args.candidate), load_artifact(args.baseline),
                               min_gain=args.min_gain)
    print(improvement_headline(result), file=sys.stderr)
    for check in result["checks"]:
        mark = "PASS" if check["passed"] else "FAIL"
        print(f"  [{mark}] {check['name']}: {check['detail']}", file=sys.stderr)

    print(json.dumps(result, indent=2))

    if args.strict and not result["passed"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
