"""CLI: gate whether a generalization artifact's gap matches its partition scores.

  python -m scripts.gap_integrity report.json
  python -m scripts.gap_integrity report.json --tolerance 0.001 --strict

Path/JSON failures exit 2. With --strict the process exits 1 when the gap integrity
gate fails (distinct from a bad artifact path).
"""

from __future__ import annotations

import argparse
import errno
import json
import os
import sys

from benchmark.gap_integrity import (
    DEFAULT_TOLERANCE,
    check_gap_integrity,
    integrity_headline,
)


def load_artifact(path: str) -> dict:
    """Load a JSON-object artifact, exiting with a clear message on a bad path or bad JSON.

    Path problems get a specific, actionable message instead of a raw errno string: a broken
    symlink (dangling target), a symlink loop, ``FileNotFoundError`` (missing),
    ``PermissionError`` (unreadable -- including a directory on Windows), ``IsADirectoryError``
    (a directory on POSIX), and any other ``OSError``. All path/JSON failures exit **2**, so
    they stay distinct from ``--strict`` gate failure (exit **1**).

    Broken-symlink detection runs *after* ``open`` fails (``FileNotFoundError`` + ``islink``),
    so there is no ``exists``/``open`` TOCTOU pre-check that can raise on a symlink loop.
    """
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except FileNotFoundError:
        # open() already failed; classify dangling symlink vs missing path without a prior
        # exists() probe (which can raise on a symlink loop and races with open).
        if os.path.islink(path):
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
    ap = argparse.ArgumentParser(
        description="Gate a --generalization artifact on generalization-gap integrity",
    )
    ap.add_argument("artifact", help="path to a run_eval --generalization JSON artifact")
    ap.add_argument("--tolerance", type=float, default=DEFAULT_TOLERANCE,
                    help=("max allowed |round(reported,3) - round(tuned-held_out,3)| "
                          f"(default {DEFAULT_TOLERANCE}; use for float-noisy artifacts)"))
    ap.add_argument("--strict", action="store_true",
                    help="exit 1 when the gap integrity gate fails (for CI gating)")
    args = ap.parse_args()

    artifact = load_artifact(args.artifact)

    result = check_gap_integrity(artifact, tolerance=args.tolerance)
    print(integrity_headline(result), file=sys.stderr)
    for check in result["checks"]:
        mark = "PASS" if check["passed"] else "FAIL"
        print(f"  [{mark}] {check['name']}: {check['detail']}", file=sys.stderr)

    print(json.dumps(result, indent=2))

    if args.strict and not result["passed"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
