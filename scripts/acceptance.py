"""CLI: gate a ``--generalization`` result against the M3/M4 acceptance criteria.

  python -m scripts.acceptance gen.json                       # report PASS/FAIL
  python -m scripts.acceptance gen.json --max-gap 0.10 --strict   # exit 1 on FAIL (CI gate)

``gen.json`` is a ``run_eval --generalization --out`` artifact. With --strict the process exits
non-zero when the acceptance checks fail, so the M3/M4 acceptance run can gate CI.
"""

from __future__ import annotations

import argparse
import json
import sys

from benchmark.acceptance import (
    DEFAULT_MAX_GAP,
    DEFAULT_MIN_SCORED_REPOS,
    acceptance_headline,
    check_acceptance,
)


def load_artifact(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError(f"artifact must be a JSON object: {path}")
    return data


def main() -> None:
    ap = argparse.ArgumentParser(description="Gate a --generalization result on M3/M4 acceptance")
    ap.add_argument("artifact", help="path to a run_eval --generalization --out JSON artifact")
    ap.add_argument("--max-gap", type=float, default=DEFAULT_MAX_GAP,
                    help=f"max acceptable tuned-minus-held-out gap (default {DEFAULT_MAX_GAP})")
    ap.add_argument("--min-scored-repos", type=int, default=DEFAULT_MIN_SCORED_REPOS,
                    help=f"min scored repos per partition (default {DEFAULT_MIN_SCORED_REPOS})")
    ap.add_argument("--strict", action="store_true",
                    help="exit 1 when the acceptance checks fail (for CI gating)")
    args = ap.parse_args()

    try:
        artifact = load_artifact(args.artifact)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)

    result = check_acceptance(artifact,
                              max_gap=args.max_gap, min_scored_repos=args.min_scored_repos)
    print(acceptance_headline(result), file=sys.stderr)
    for check in result["checks"]:
        mark = "PASS" if check["passed"] else "FAIL"
        print(f"  [{mark}] {check['name']}: {check['detail']}", file=sys.stderr)

    print(json.dumps(result, indent=2))

    if args.strict and not result["passed"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
