"""CLI: replay the offline pairwise-judge golden corpus.

  python -m scripts.calibrate_judge
  python -m scripts.calibrate_judge --strict

With ``--strict`` the process exits non-zero when any scenario fails, so judge substance
heuristics can be gated in CI without git clones or live LLM calls.
"""

from __future__ import annotations

import argparse
import json
import sys

from benchmark.judge_calibration import (
    calibration_headline,
    check_calibration,
    failed_scenarios,
    load_corpus,
)


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Replay the offline pairwise-judge golden corpus",
    )
    ap.add_argument(
        "--corpus-root",
        default=None,
        help="optional alternate corpus root (defaults to benchmark/judge_corpus)",
    )
    ap.add_argument(
        "--strict",
        action="store_true",
        help="exit 1 when any scenario fails (for CI gating)",
    )
    args = ap.parse_args()

    try:
        corpus = load_corpus(args.corpus_root) if args.corpus_root else load_corpus()
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)

    result = check_calibration(corpus)
    print(calibration_headline(result), file=sys.stderr)
    for row in result["results"]:
        mark = "PASS" if row["passed"] else "FAIL"
        print(f"  [{mark}] {row['id']}: {row['detail']}", file=sys.stderr)
    for row in result.get("symmetry_checks") or []:
        mark = "PASS" if row["passed"] else "FAIL"
        print(f"  [{mark}] {row['id']} (symmetry): {row['detail']}", file=sys.stderr)

    print(json.dumps(result, indent=2))

    if args.strict and not result["passed"]:
        failed = failed_scenarios(result)
        print(f"failed scenarios: {', '.join(failed)}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
