"""CLI: gate whether a replay artifact's per-task objective dicts are valid.

  python -m scripts.objective_integrity result.json
  python -m scripts.objective_integrity result.json --strict

With --strict the process exits non-zero when objective inputs are invalid.
"""

from __future__ import annotations

import argparse
import errno
import json
import os
import sys

from benchmark.objective_integrity import (
    DEFAULT_TOLERANCE,
    check_objective_integrity,
    integrity_headline,
)


def load_artifact(path: str) -> dict:
    """Load a JSON artifact from ``path``, exiting with a clean error on failure.

    Distinguishes the path failure modes so the user gets an actionable message rather than a
    raw errno string or a mislabel:

    - ``FileNotFoundError``: a missing path, or a **broken symlink** (dangling target) —
      distinguished via ``os.path.islink`` so a dangling link is not blamed as merely missing.
    - ``PermissionError``: the file is not readable (also a directory on Windows).
    - ``IsADirectoryError``: the path is a directory, not a file (POSIX).
    - Other ``OSError``: a **symlink loop** (``ELOOP``) gets its own message; anything else
      keeps the raw ``str(exc)`` as a catch-all.

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
        description="Gate a replay artifact on per-task objective integrity",
    )
    ap.add_argument("artifact", help="path to a run_eval --out JSON artifact")
    ap.add_argument("--tolerance", type=float, default=DEFAULT_TOLERANCE,
                    help=f"max allowed objective_mean delta (default {DEFAULT_TOLERANCE})")
    ap.add_argument("--strict", action="store_true",
                    help="exit 1 when the objective integrity gate fails (for CI gating)")
    args = ap.parse_args()

    result = check_objective_integrity(load_artifact(args.artifact), tolerance=args.tolerance)
    print(integrity_headline(result), file=sys.stderr)
    for check in result["checks"]:
        mark = "PASS" if check["passed"] else "FAIL"
        print(f"  [{mark}] {check['name']}: {check['detail']}", file=sys.stderr)

    print(json.dumps(result, indent=2))

    if args.strict and not result["passed"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
