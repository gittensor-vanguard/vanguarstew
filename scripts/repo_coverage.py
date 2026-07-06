"""CLI: gate whether a benchmark run covered enough diverse repos and tasks.

  python -m scripts.repo_coverage result.json                       # report OK / INSUFFICIENT
  python -m scripts.repo_coverage result.json --min-repos 5 --strict   # exit 1 if insufficient

``result.json`` is a ``run_eval --out`` multi-repo or --generalization artifact. With --strict
the process exits non-zero when coverage is insufficient.
"""

from __future__ import annotations

import argparse
import json
import sys

from benchmark.repo_coverage import (
    DEFAULT_MAX_SKIPPED,
    DEFAULT_MIN_REPOS,
    DEFAULT_MIN_TASKS,
    check_coverage,
    coverage_headline,
)


def load_artifact(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError(f"artifact must be a JSON object: {path}")
    return data


def main() -> None:
    ap = argparse.ArgumentParser(description="Gate a run's repo/task coverage breadth")
    ap.add_argument("artifact", help="path to a run_eval multi-repo / --generalization artifact")
    ap.add_argument("--min-repos", type=int, default=DEFAULT_MIN_REPOS,
                    help=f"minimum repos that must score (default {DEFAULT_MIN_REPOS})")
    ap.add_argument("--min-tasks", type=int, default=DEFAULT_MIN_TASKS,
                    help=f"minimum total tasks across scored repos (default {DEFAULT_MIN_TASKS})")
    ap.add_argument("--max-skipped", type=int, default=DEFAULT_MAX_SKIPPED,
                    help=f"max repos allowed to be skipped (default {DEFAULT_MAX_SKIPPED})")
    ap.add_argument("--strict", action="store_true",
                    help="exit 1 when coverage is insufficient (for CI gating)")
    args = ap.parse_args()

    result = check_coverage(load_artifact(args.artifact), min_repos=args.min_repos,
                            min_tasks=args.min_tasks, max_skipped=args.max_skipped)
    print(coverage_headline(result), file=sys.stderr)
    for check in result["checks"]:
        mark = "PASS" if check["passed"] else "FAIL"
        print(f"  [{mark}] {check['name']}: {check['detail']}", file=sys.stderr)

    print(json.dumps(result, indent=2))

    if args.strict and not result["passed"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
