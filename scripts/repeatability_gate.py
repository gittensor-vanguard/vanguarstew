"""CLI: gate whether repeated benchmark runs of the same config are stable.

  python -m scripts.repeatability_gate run1.json run2.json run3.json
  python -m scripts.repeatability_gate --max-cv 0.03 --strict runs/*.json

Prints named pass/fail checks and exits non-zero when the repeatability gate fails.
"""

from __future__ import annotations

import argparse
import errno
import json
import os
import sys

from benchmark.repeatability_gate import (
    DEFAULT_MAX_CV,
    DEFAULT_MIN_RUNS,
    check_repeatability,
    repeatability_gate_headline,
)


def load_artifact(path: str) -> dict:
    """Load a JSON-object artifact, exiting with a clear message on a bad path or bad JSON.

    Path problems get a specific, actionable message instead of a raw traceback / errno string:
    a broken symlink (dangling target), a symlink loop, ``FileNotFoundError`` (missing),
    ``PermissionError`` (unreadable), ``IsADirectoryError`` (a directory, not a file),
    ``NotADirectoryError`` (a parent component is a file), and any other ``OSError``.

    Broken-symlink detection runs *after* ``open`` fails (``FileNotFoundError`` + ``islink``),
    so there is no ``exists``/``open`` TOCTOU pre-check that can itself raise on a symlink loop
    (``os.path.exists()`` swallows ``OSError(ELOOP)`` and returns ``False``, which a pre-check
    would misreport as a dangling target rather than a loop).
    """
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except FileNotFoundError:
        if os.path.islink(path):
            print(f"artifact is a broken symlink (target does not exist): {path}", file=sys.stderr)
        else:
            print(f"artifact not found: {path}", file=sys.stderr)
        raise SystemExit(2) from None
    except PermissionError:
        print(f"artifact is not readable (check file permissions): {path}", file=sys.stderr)
        raise SystemExit(2) from None
    except IsADirectoryError:
        print(f"artifact path is a directory, not a file: {path}", file=sys.stderr)
        raise SystemExit(2) from None
    except NotADirectoryError:
        print(f"artifact path is not a file (a parent component is not a directory): {path}",
              file=sys.stderr)
        raise SystemExit(2) from None
    except OSError as exc:
        # A symlink loop raises OSError(ELOOP), which none of the arms above catch. Name it
        # distinctly; any other real read failure keeps its underlying text with a clean exit.
        if getattr(exc, "errno", None) == errno.ELOOP:
            print(f"artifact path is a symlink loop: {path}", file=sys.stderr)
        else:
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
