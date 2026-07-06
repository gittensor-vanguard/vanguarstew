"""CLI: gate whether a candidate improved enough over a baseline.

  python -m scripts.min_improvement baseline.json candidate.json
  python -m scripts.min_improvement baseline.json candidate.json --min-improvement 0.02 --strict

``--strict``: exit 1 when the improvement threshold is not met.
"""

from __future__ import annotations

import argparse
import json
import sys

from benchmark.min_improvement import (
    DEFAULT_MIN_IMPROVEMENT,
    check_min_improvement,
    min_improvement_headline,
)


def load_artifact(path: str) -> dict:
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


def run(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Gate whether candidate improved enough over baseline")
    ap.add_argument("baseline", help="baseline run_eval --out JSON artifact")
    ap.add_argument("candidate", help="candidate run_eval --out JSON artifact")
    ap.add_argument("--min-improvement", type=float, default=DEFAULT_MIN_IMPROVEMENT,
                    help=f"minimum headline score gain required (default {DEFAULT_MIN_IMPROVEMENT})")
    ap.add_argument("--strict", action="store_true",
                    help="exit 1 when the improvement threshold is not met (CI gate)")
    args = ap.parse_args(argv)
    try:
        baseline = load_artifact(args.baseline)
        candidate = load_artifact(args.candidate)
    except SystemExit as exc:
        return int(exc.code)
    result = check_min_improvement(candidate, baseline, min_improvement=args.min_improvement)
    print(min_improvement_headline(result), file=sys.stderr)
    print(json.dumps(result, indent=2))
    if args.strict and not result["passed"]:
        return 1
    return 0


def main() -> None:
    raise SystemExit(run())


if __name__ == "__main__":
    main()
