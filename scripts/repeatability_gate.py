"""CLI: gate whether repeated benchmark runs of the same config are stable.

  python -m scripts.repeatability_gate run1.json run2.json run3.json
  python -m scripts.repeatability_gate --max-cv 0.03 --strict runs/*.json

Prints named pass/fail checks and exits non-zero when the repeatability gate fails.
"""

from __future__ import annotations

import argparse
import json
import sys

from benchmark.repeatability_gate import (
    DEFAULT_MAX_CV,
    DEFAULT_MIN_RUNS,
    check_repeatability,
    repeatability_gate_headline,
)


def load_artifact(path: str) -> dict:
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except OSError as exc:
        # Covers missing file, permission denied, and "is a directory".
        print(f"cannot read artifact ({path}): {exc}", file=sys.stderr)
        raise SystemExit(2) from None
    except ValueError as exc:
        # json.load raises a plain ValueError (not JSONDecodeError) on an integer literal
        # beyond the int-string-conversion limit (py3.11+); JSONDecodeError subclasses it.
        print(f"artifact is not valid JSON ({path}): {exc}", file=sys.stderr)
        raise SystemExit(2) from None
    if not isinstance(data, dict):
        print(f"artifact must be a JSON object: {path}", file=sys.stderr)
        raise SystemExit(2)
    return data


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Gate whether repeated runs of the same config are stable",
    )
    ap.add_argument("artifacts", nargs="+", help="two or more repeat-run result JSON files")
    ap.add_argument("--max-cv", type=float, default=DEFAULT_MAX_CV,
                    help=f"max acceptable coefficient of variation (default {DEFAULT_MAX_CV})")
    ap.add_argument("--min-runs", type=int, default=DEFAULT_MIN_RUNS,
                    help=f"min scored repeats required (default {DEFAULT_MIN_RUNS})")
    ap.add_argument("--strict", action="store_true",
                    help="exit 1 when the repeatability gate fails (for CI gating)")
    args = ap.parse_args()

    artifacts = [load_artifact(path) for path in args.artifacts]
    result = check_repeatability(artifacts, max_cv=args.max_cv, min_runs=args.min_runs)
    print(repeatability_gate_headline(result), file=sys.stderr)
    for check in result["checks"]:
        mark = "PASS" if check["passed"] else "FAIL"
        print(f"  [{mark}] {check['name']}: {check['detail']}", file=sys.stderr)
    if result.get("reason"):
        print(f"  {result['reason']}", file=sys.stderr)

    print(json.dumps(result, indent=2))

    if args.strict and not result["passed"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
