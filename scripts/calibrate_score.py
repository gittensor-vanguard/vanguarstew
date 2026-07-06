"""CLI: replay the offline objective-scoring golden corpus.

  python -m scripts.calibrate_score
  python -m scripts.calibrate_score --strict

With ``--strict`` the process exits non-zero when any scenario fails.
"""

from __future__ import annotations

import argparse
import json
import sys

from benchmark.score_calibration import (
    DEFAULT_TOLERANCE,
    calibration_headline,
    check_calibration,
    failed_scenarios,
    load_corpus,
)


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Replay the offline objective-scoring golden corpus",
    )
    ap.add_argument(
        "--corpus-root",
        default=None,
        help="optional alternate corpus root (defaults to benchmark/score_corpus)",
    )
    ap.add_argument(
        "--tolerance",
        type=float,
        default=DEFAULT_TOLERANCE,
        help=f"max allowed numeric delta per field (default {DEFAULT_TOLERANCE})",
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

    result = check_calibration(corpus, tolerance=args.tolerance)
    print(calibration_headline(result), file=sys.stderr)
    for row in result["results"]:
        mark = "PASS" if row["passed"] else "FAIL"
        print(f"  [{mark}] {row['id']}: {row['detail']}", file=sys.stderr)

    print(json.dumps(result, indent=2))

    if args.strict and not result["passed"]:
        failed = failed_scenarios(result)
        print(f"failed scenarios: {', '.join(failed)}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
