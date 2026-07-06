"""CLI: track the benchmark score across a series of saved replay artifacts.

  python -m scripts.trend run1.json run2.json run3.json
  python -m scripts.trend --threshold 0.05 --fail-on-regression runs/*.json

Artifacts are read in the order given (treated as chronological). Prints a per-point table and
a headline, and — with --fail-on-regression — exits non-zero if any consecutive drop exceeds
the threshold, for CI trend-gating.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

from benchmark.trend import DEFAULT_REGRESSION_THRESHOLD, trend, trend_headline


def load_artifact(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError(f"artifact must be a JSON object: {path}")
    return data


def _fmt(value) -> str:
    return f"{value:.3f}" if isinstance(value, (int, float)) and not isinstance(value, bool) else "n/a"


def main() -> None:
    ap = argparse.ArgumentParser(description="Trend the benchmark score across saved artifacts")
    ap.add_argument("artifacts", nargs="+", help="two or more result JSON files, in order")
    ap.add_argument("--threshold", type=float, default=DEFAULT_REGRESSION_THRESHOLD,
                    help=f"regression drop threshold (default {DEFAULT_REGRESSION_THRESHOLD})")
    ap.add_argument("--fail-on-regression", action="store_true",
                    help="exit 1 if any consecutive drop exceeds the threshold (CI gating)")
    args = ap.parse_args()

    # OSError covers FileNotFoundError, PermissionError, and IsADirectoryError alike;
    # json.JSONDecodeError is invalid JSON; ValueError is a valid-JSON non-object artifact.
    # Same guard as the acceptance/promotion/repeatability/compare_eval/leaderboard/report CLIs.
    try:
        series = [(os.path.basename(p), load_artifact(p)) for p in args.artifacts]
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)

    # A loadable artifact can still be arbitrarily malformed inside (miner/CI-controlled
    # content), so the analysis and rendering paths get the same clean-error treatment as
    # loading -- a CI step must never see a raw traceback from a bad artifact.
    try:
        summary = trend(series, regression_threshold=args.threshold)
        print(trend_headline(summary), file=sys.stderr)
        for point in summary["points"]:
            delta = point["delta"]
            delta_txt = f" ({delta:+.3f})" if isinstance(delta, (int, float)) and not isinstance(delta, bool) else ""
            print(f"  {point['label']}: {_fmt(point['composite_mean'])}{delta_txt}", file=sys.stderr)
        for reg in summary["regressions"]:
            print(f"  REGRESSION {reg['from_label']} -> {reg['to_label']}: -{reg['drop']:.3f}", file=sys.stderr)
        print(json.dumps(summary, indent=2))
    except (KeyError, TypeError, ValueError) as exc:
        print(f"trend: cannot analyze artifacts: {exc!r}", file=sys.stderr)
        sys.exit(1)

    if args.fail_on_regression and summary["regressions"]:
        print(f"trend: {len(summary['regressions'])} regression(s) exceed the threshold",
              file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
