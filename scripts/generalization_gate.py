"""CLI: gate whether a --generalization run generalized to its held-out repos.

  python -m scripts.generalization_gate run.json
  python -m scripts.generalization_gate run.json --max-gap 0.08 --min-held-out-repos 4 --strict

The argument is a ``run_multi_replay --generalization --out`` artifact. With --strict, exits
non-zero when the run did not generalize (too large a tuned-vs-held-out gap, or too few held-out
repos).
"""

from __future__ import annotations

import argparse
import json
import sys

from benchmark.generalization_gate import (
    DEFAULT_MAX_GAP,
    DEFAULT_MIN_HELD_OUT_REPOS,
    check_generalization,
    generalization_headline,
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
    ap = argparse.ArgumentParser(description="Gate whether a --generalization run generalized")
    ap.add_argument("run", help="the run_multi_replay --generalization --out JSON artifact")
    ap.add_argument("--max-gap", type=float, default=DEFAULT_MAX_GAP,
                    help=f"maximum tuned-minus-held-out composite drop (default {DEFAULT_MAX_GAP})")
    ap.add_argument("--min-held-out-repos", type=int, default=DEFAULT_MIN_HELD_OUT_REPOS,
                    help=f"minimum held-out repos scored (default {DEFAULT_MIN_HELD_OUT_REPOS})")
    ap.add_argument("--strict", action="store_true",
                    help="exit 1 when the run did not generalize (for CI gating)")
    args = ap.parse_args()

    result = check_generalization(load_artifact(args.run), max_gap=args.max_gap,
                                  min_held_out_repos=args.min_held_out_repos)
    print(generalization_headline(result), file=sys.stderr)
    for check in result["checks"]:
        mark = "PASS" if check["passed"] else "FAIL"
        print(f"  [{mark}] {check['name']}: {check['detail']}", file=sys.stderr)

    print(json.dumps(result, indent=2))

    if args.strict and not result["passed"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
