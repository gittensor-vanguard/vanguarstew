"""CLI: gate whether a multi-repo replay run covered enough breadth.

  python -m scripts.repo_coverage result.json                     # report SUFFICIENT / INSUFFICIENT
  python -m scripts.repo_coverage result.json --min-repos 3 --strict   # exit 1 on insufficient

``result.json`` is a ``run_eval --out`` artifact (multi-repo or --generalization). With --strict
the process exits non-zero when the coverage gate fails.
"""

from __future__ import annotations

import argparse
import json
import sys

from benchmark.coverage import (
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
    ap = argparse.ArgumentParser(description="Gate a multi-repo replay run on coverage breadth")
    ap.add_argument("artifact", help="path to a run_eval --out JSON artifact")
    ap.add_argument("--min-repos", type=int, default=DEFAULT_MIN_REPOS,
                    help=f"minimum scored repos (default {DEFAULT_MIN_REPOS})")
    ap.add_argument("--max-skipped", type=int, default=DEFAULT_MAX_SKIPPED,
                    help=f"maximum skipped repos (default {DEFAULT_MAX_SKIPPED})")
    ap.add_argument("--min-tasks", type=int, default=DEFAULT_MIN_TASKS,
                    help=f"minimum total tasks across scored repos (default {DEFAULT_MIN_TASKS})")
    ap.add_argument("--strict", action="store_true",
                    help="exit 1 when the coverage gate fails (for CI gating)")
    args = ap.parse_args()

    try:
        artifact = load_artifact(args.artifact)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)

    result = check_coverage(artifact,
                            min_repos=args.min_repos,
                            max_skipped=args.max_skipped,
                            min_tasks=args.min_tasks)
    print(coverage_headline(result), file=sys.stderr)
    for check in result["checks"]:
        mark = "PASS" if check["passed"] else "FAIL"
        print(f"  [{mark}] {check['name']}: {check['detail']}", file=sys.stderr)

    print(json.dumps(result, indent=2))

    if args.strict and not result["passed"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
