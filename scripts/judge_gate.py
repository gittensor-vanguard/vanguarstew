"""CLI: gate whether a run's pairwise judge was robust enough to trust.

  python -m scripts.judge_gate result.json
  python -m scripts.judge_gate result.json --max-disagreement 0.2 --strict

``result.json`` is a ``run_eval --out`` artifact. With --strict, exits non-zero when the judge
is not robust.
"""

from __future__ import annotations

import argparse
import json
import sys

from benchmark.judge_gate import (
    DEFAULT_MAX_DISAGREEMENT,
    DEFAULT_MIN_DUAL_ORDER_TASKS,
    check_judge,
    judge_headline,
)
from scripts.artifact_io import load_artifact  # re-exported for tests / callers

__all__ = ["load_artifact", "run"]

def run(argv=None) -> int:
    """Parse ``argv``, evaluate the gate, print the result, and return the intended exit code."""
    ap = argparse.ArgumentParser(description="Gate a run on pairwise-judge robustness")
    ap.add_argument("artifact", help="path to a run_eval --out JSON artifact")
    ap.add_argument("--max-disagreement", type=float, default=DEFAULT_MAX_DISAGREEMENT,
                    help=f"max order-disagreement rate (default {DEFAULT_MAX_DISAGREEMENT})")
    ap.add_argument("--min-dual-order-tasks", type=int, default=DEFAULT_MIN_DUAL_ORDER_TASKS,
                    help=f"min tasks judged in both orders (default {DEFAULT_MIN_DUAL_ORDER_TASKS})")
    ap.add_argument("--strict", action="store_true",
                    help="exit 1 when the judge is not robust (for CI gating)")
    args = ap.parse_args(argv)

    try:
        artifact = load_artifact(args.artifact)
    except SystemExit as exc:
        return int(exc.code)

    # A loadable artifact can still be arbitrarily malformed inside, so the gate check and
    # rendering get the same clean-error treatment as loading -- a CI step must never see a
    # raw traceback from a bad artifact.
    try:
        result = check_judge(artifact,
                             max_disagreement=args.max_disagreement,
                             min_dual_order_tasks=args.min_dual_order_tasks)
        print(judge_headline(result), file=sys.stderr)
        for check in result["checks"]:
            mark = "PASS" if check["passed"] else "FAIL"
            print(f"  [{mark}] {check['name']}: {check['detail']}", file=sys.stderr)
        print(json.dumps(result, indent=2))
    except (KeyError, TypeError, ValueError) as exc:
        print(f"judge_gate: cannot evaluate artifact: {exc!r}", file=sys.stderr)
        return 1

    if args.strict and not result["passed"]:
        return 1
    return 0

def main() -> None:
    raise SystemExit(run())

if __name__ == "__main__":
    main()
