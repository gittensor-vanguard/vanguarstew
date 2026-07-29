"""CLI: gate whether a candidate run improved enough over a baseline to adopt it.

  python -m scripts.improvement baseline.json candidate.json
  python -m scripts.improvement baseline.json candidate.json --min-gain 0.05 --strict

Both are ``run_eval --out`` artifacts (``baseline`` = current best, ``candidate`` = new run).
With --strict, exits non-zero when the candidate did not improve by at least the margin.
"""

from __future__ import annotations

import argparse
import errno
import json
import os
import sys

from benchmark.improvement import (
    DEFAULT_MIN_GAIN,
    check_improvement,
    improvement_headline,
)


def load_artifact(path: str) -> dict:
    """Load a JSON-object artifact, exiting with a clear message on a bad path or bad JSON.

    The path failure modes are handled distinctly so the user gets an actionable message
    instead of a raw errno string or a mislabel: ``FileNotFoundError`` (a missing path, or a
    **broken symlink** whose target is gone — distinguished via ``os.path.islink``),
    ``PermissionError`` (unreadable), ``IsADirectoryError`` (a directory, not a file), a
    **symlink loop** (``ELOOP``), and any other ``OSError`` (e.g. an I/O error, whose message
    is echoed). Mirrors the merged ``objective_integrity`` / ``freeze_coverage`` /
    ``promotion`` CLIs.

    Broken-symlink detection runs *after* ``open`` fails (``FileNotFoundError`` + ``islink``),
    so there is no ``exists``/``open`` TOCTOU pre-check that can raise on a symlink loop. The
    ``islink`` probe is itself guarded: on a pathological path where ``lstat`` raises, it falls
    back to the plain "not found" message rather than crashing the classifier.
    """
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        # open() already failed; classify dangling symlink vs missing path without a prior
        # exists() probe (which can raise on a symlink loop and races with open). islink()
        # can itself raise OSError on a pathological path, so treat that as "not a link".
        try:
            is_link = os.path.islink(path)
        except OSError:
            is_link = False
        if is_link:
            print(f"artifact is a broken symlink (target does not exist): {path}", file=sys.stderr)
        else:
            print(f"artifact not found: {path}", file=sys.stderr)
        raise SystemExit(2) from None
    except PermissionError:
        # Windows raises PermissionError (not IsADirectoryError) when ``path`` is a directory.
        print(f"artifact is not readable (check file permissions): {path}", file=sys.stderr)
        raise SystemExit(2) from None
    except IsADirectoryError:
        print(f"artifact path is a directory, not a file: {path}", file=sys.stderr)
        raise SystemExit(2) from None
    except OSError as exc:
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
    ap = argparse.ArgumentParser(description="Gate whether a candidate improved over a baseline")
    ap.add_argument("baseline", help="the current-best run_eval --out JSON artifact")
    ap.add_argument("candidate", help="the new run's run_eval --out JSON artifact")
    ap.add_argument("--min-gain", type=float, default=DEFAULT_MIN_GAIN,
                    help=f"minimum composite gain to adopt (default {DEFAULT_MIN_GAIN})")
    ap.add_argument("--strict", action="store_true",
                    help="exit 1 when the candidate did not improve enough (for CI gating)")
    args = ap.parse_args()

    result = check_improvement(load_artifact(args.candidate), load_artifact(args.baseline),
                               min_gain=args.min_gain)
    print(improvement_headline(result), file=sys.stderr)
    for check in result["checks"]:
        mark = "PASS" if check["passed"] else "FAIL"
        print(f"  [{mark}] {check['name']}: {check['detail']}", file=sys.stderr)

    print(json.dumps(result, indent=2))

    if args.strict and not result["passed"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
