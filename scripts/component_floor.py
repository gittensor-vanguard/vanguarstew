"""CLI: gate a run so each scoring component clears its own floor.

  python -m scripts.component_floor result.json
  python -m scripts.component_floor result.json --min-objective 0.5 --strict

``result.json`` is a ``run_eval --out`` artifact. A stricter gate than ``--fail-under``: it
floors the composite AND the judge and objective component means. With --strict, exits non-zero
when any floor is missed.
"""

from __future__ import annotations

import argparse
import json
import sys

from benchmark.component_floor import (
    DEFAULT_MIN_COMPOSITE,
    DEFAULT_MIN_JUDGE,
    DEFAULT_MIN_OBJECTIVE,
    check_component_floors,
    component_floor_headline,
)
from scripts.artifact_io import load_artifact  # re-exported for tests / callers

__all__ = ["load_artifact", "run"]

def run(argv=None) -> int:
    """Parse ``argv``, evaluate the floors, print the result, and return the intended exit code."""
    ap = argparse.ArgumentParser(description="Gate a run on per-component score floors")
    ap.add_argument("artifact", help="path to a run_eval --out JSON artifact")
    ap.add_argument("--min-composite", type=float, default=DEFAULT_MIN_COMPOSITE,
                    help=f"minimum composite_mean (default {DEFAULT_MIN_COMPOSITE})")
    ap.add_argument("--min-judge", type=float, default=DEFAULT_MIN_JUDGE,
                    help=f"minimum judge component mean (default {DEFAULT_MIN_JUDGE})")
    ap.add_argument("--min-objective", type=float, default=DEFAULT_MIN_OBJECTIVE,
                    help=f"minimum objective anchor mean (default {DEFAULT_MIN_OBJECTIVE})")
    ap.add_argument("--strict", action="store_true",
                    help="exit 1 when any floor is missed (for CI gating)")
    args = ap.parse_args(argv)

    try:
        artifact = load_artifact(args.artifact)
    except SystemExit as exc:
        return int(exc.code)

    # A loadable artifact can still be arbitrarily malformed inside, so the floor check and
    # rendering get the same clean-error treatment as loading -- a CI step must never see a
    # raw traceback from a bad artifact.
    try:
        result = check_component_floors(artifact,
                                        min_composite=args.min_composite,
                                        min_judge=args.min_judge,
                                        min_objective=args.min_objective)
        print(component_floor_headline(result), file=sys.stderr)
        for check in result["checks"]:
            mark = "PASS" if check["passed"] else "FAIL"
            print(f"  [{mark}] {check['name']}: {check['detail']}", file=sys.stderr)
        print(json.dumps(result, indent=2))
    except (KeyError, TypeError, ValueError) as exc:
        print(f"component_floor: cannot evaluate artifact: {exc!r}", file=sys.stderr)
        return 1

    if args.strict and not result["passed"]:
        return 1
    return 0

def main() -> None:
    raise SystemExit(run())

if __name__ == "__main__":
    main()
