"""CLI: gate whether a repo-set config is ready for an acceptance run.

  python -m scripts.repo_set_readiness benchmark/repo_sets/curated.json
  python -m scripts.repo_set_readiness cfg.json --min-tuned 3 --min-held-out 2 --strict

Prints each readiness check; with --strict, exits non-zero when the set is not ready.
"""

from __future__ import annotations

import argparse
import json
import sys

from benchmark.repo_set_readiness import (
    DEFAULT_MIN_HELD_OUT,
    DEFAULT_MIN_TUNED,
    check_readiness,
    readiness_headline,
)


def load_config(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def main() -> None:
    ap = argparse.ArgumentParser(description="Gate a repo-set config's readiness for an acceptance run")
    ap.add_argument("config", help="path to a repo-set JSON config")
    ap.add_argument("--min-tuned", type=int, default=DEFAULT_MIN_TUNED,
                    help=f"minimum tuned repos (default {DEFAULT_MIN_TUNED})")
    ap.add_argument("--min-held-out", type=int, default=DEFAULT_MIN_HELD_OUT,
                    help=f"minimum held-out repos (default {DEFAULT_MIN_HELD_OUT})")
    ap.add_argument("--strict", action="store_true",
                    help="exit 1 when the set is not ready (for CI gating)")
    args = ap.parse_args()

    result = check_readiness(load_config(args.config),
                             min_tuned=args.min_tuned, min_held_out=args.min_held_out)
    print(readiness_headline(result), file=sys.stderr)
    for check in result["checks"]:
        mark = "PASS" if check["passed"] else "FAIL"
        print(f"  [{mark}] {check['name']}: {check['detail']}", file=sys.stderr)

    print(json.dumps(result, indent=2))

    if args.strict and not result["passed"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
