"""CLI: assess whether repeated benchmark runs of the same config are stable.

  python -m scripts.repeatability run1.json run2.json run3.json
  python -m scripts.repeatability --max-cv 0.03 --strict runs/*.json

The artifacts are repeats of the same configuration. Prints the distribution and a STABLE /
UNSTABLE verdict; with --strict, exits non-zero when the runs are not stable (CI reproducibility
gate).
"""

from __future__ import annotations

import argparse
import json
import sys

from benchmark.repeatability import (
    DEFAULT_MAX_CV,
    DEFAULT_MIN_RUNS,
    assess_repeatability,
    repeatability_headline,
)


def load_artifact(path: str) -> dict:
    """Load a JSON-object artifact, exiting with a clear message on a bad path or bad JSON.

    The common ``OSError`` subclasses are handled distinctly so the user gets an actionable
    message instead of a raw errno / traceback: ``FileNotFoundError`` (missing),
    ``PermissionError`` (unreadable), ``IsADirectoryError`` (a directory, not a file), and any
    other ``OSError``.
    """
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
    ap = argparse.ArgumentParser(description="Assess repeated-run stability of the same config")
    ap.add_argument("artifacts", nargs="+", help="two or more repeat-run result JSON files")
    ap.add_argument("--max-cv", type=float, default=DEFAULT_MAX_CV,
                    help=f"max acceptable coefficient of variation (default {DEFAULT_MAX_CV})")
    ap.add_argument("--min-runs", type=int, default=DEFAULT_MIN_RUNS,
                    help=f"min scored repeats required (default {DEFAULT_MIN_RUNS})")
    ap.add_argument("--strict", action="store_true",
                    help="exit 1 when the runs are not stable (CI reproducibility gate)")
    args = ap.parse_args()

    try:
        artifacts = [load_artifact(p) for p in args.artifacts]
    except SystemExit as exc:
        raise SystemExit(exc.code) from None
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)

    result = assess_repeatability(artifacts, max_cv=args.max_cv, min_runs=args.min_runs)
    print(repeatability_headline(result), file=sys.stderr)
    if result["reason"]:
        print(f"  {result['reason']}", file=sys.stderr)
    print(json.dumps(result, indent=2))

    if args.strict and not result["stable"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
