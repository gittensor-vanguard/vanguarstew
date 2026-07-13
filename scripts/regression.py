"""CLI: gate a candidate run against a baseline run for regressions.

  python -m scripts.regression baseline.json candidate.json
  python -m scripts.regression baseline.json candidate.json --max-composite-drop 0.01 --strict

Both are ``run_eval --out`` artifacts (``baseline`` = last accepted run, ``candidate`` = this
run). With --strict, exits non-zero when the candidate regressed.
"""

from __future__ import annotations

import argparse
import json
import sys

from benchmark.regression import (
    DEFAULT_MAX_COMPOSITE_DROP,
    DEFAULT_MAX_DISAGREEMENT_INCREASE,
    check_regression,
    regression_headline,
)


def load_artifact(path: str) -> dict:
    """Load a JSON-object artifact, exiting with a clear message on a bad path or bad JSON."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        print(f"artifact not found: {path}", file=sys.stderr)
        raise SystemExit(1) from None
    except PermissionError:
        print(f"artifact is not readable (check file permissions): {path}", file=sys.stderr)
        raise SystemExit(1) from None
    except IsADirectoryError:
        print(f"artifact path is a directory, not a file: {path}", file=sys.stderr)
        raise SystemExit(1) from None
    except OSError as exc:
        print(f"cannot read artifact ({path}): {exc}", file=sys.stderr)
        raise SystemExit(1) from None
    except ValueError as exc:
        # json.load raises a plain ValueError (not JSONDecodeError) on an integer literal
        # beyond the int-string-conversion limit (py3.11+); JSONDecodeError subclasses it.
        print(f"artifact is not valid JSON ({path}): {exc}", file=sys.stderr)
        raise SystemExit(1) from None
    if not isinstance(data, dict):
        raise ValueError(f"artifact must be a JSON object: {path}")
    return data


def main() -> None:
    ap = argparse.ArgumentParser(description="Gate a candidate run against a baseline for regressions")
    ap.add_argument("baseline", help="the last accepted run_eval --out JSON artifact")
    ap.add_argument("candidate", help="this run's run_eval --out JSON artifact")
    ap.add_argument("--max-composite-drop", type=float, default=DEFAULT_MAX_COMPOSITE_DROP,
                    help=f"max allowed composite drop (default {DEFAULT_MAX_COMPOSITE_DROP})")
    ap.add_argument("--max-disagreement-increase", type=float,
                    default=DEFAULT_MAX_DISAGREEMENT_INCREASE,
                    help=f"max allowed judge disagreement rise (default {DEFAULT_MAX_DISAGREEMENT_INCREASE})")
    ap.add_argument("--strict", action="store_true",
                    help="exit 1 when the candidate regressed (for CI gating)")
    args = ap.parse_args()

    try:
        candidate = load_artifact(args.candidate)
        baseline = load_artifact(args.baseline)
    except SystemExit as exc:
        raise SystemExit(exc.code) from None
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)

    result = check_regression(
        candidate, baseline,
        max_composite_drop=args.max_composite_drop,
        max_disagreement_increase=args.max_disagreement_increase,
    )
    print(regression_headline(result), file=sys.stderr)
    for check in result["checks"]:
        mark = "PASS" if check["passed"] else "FAIL"
        print(f"  [{mark}] {check['name']}: {check['detail']}", file=sys.stderr)

    print(json.dumps(result, indent=2))

    if args.strict and not result["passed"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
