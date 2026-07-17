"""CLI: gate whether a run judged and accounted for enough tasks to be trustworthy.

  python -m scripts.sample_adequacy run.json
  python -m scripts.sample_adequacy run.json --min-tasks 5 --strict

The argument is a ``run_eval --out`` artifact (single- or multi-repo). With --strict, exits
non-zero when the run judged fewer than ``--min-tasks`` tasks or didn't account for all of them.
"""

from __future__ import annotations

import argparse
import errno
import json
import os
import sys

from benchmark.sample_adequacy import (
    DEFAULT_MIN_TASKS,
    check_sample_adequacy,
    sample_adequacy_headline,
)


def load_artifact(path: str) -> dict:
    """Load a JSON-object artifact, exiting with a clear message on a bad path or bad JSON.

    Path problems get a specific, actionable message instead of a raw traceback / errno string:
    a broken symlink (dangling target), a symlink loop, ``FileNotFoundError`` (missing),
    ``PermissionError`` (unreadable — including a directory on Windows), ``IsADirectoryError``
    (a directory on POSIX), and any other ``OSError``.

    Broken-symlink detection runs *after* ``open`` fails (``FileNotFoundError`` + ``islink``),
    so there is no ``exists``/``open`` TOCTOU pre-check that can raise on a symlink loop.
    """
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        # open() already failed; classify dangling symlink vs missing path without a prior
        # exists() probe (which can raise on a symlink loop and races with open).
        if os.path.islink(path):
            print(f"artifact is a broken symlink (target does not exist): {path}", file=sys.stderr)
        else:
            print(f"artifact not found: {path}", file=sys.stderr)
        raise SystemExit(2) from None
    except IsADirectoryError:
        print(f"artifact path is a directory, not a file: {path}", file=sys.stderr)
        raise SystemExit(2) from None
    except PermissionError as exc:
        # Windows raises PermissionError (not IsADirectoryError) when ``path`` is a directory.
        print(f"permission denied reading artifact ({path}): {exc}", file=sys.stderr)
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
    ap = argparse.ArgumentParser(description="Gate whether a run judged enough tasks to trust")
    ap.add_argument("run", help="the run_eval --out JSON artifact to check")
    ap.add_argument("--min-tasks", type=int, default=DEFAULT_MIN_TASKS,
                    help=f"minimum number of tasks required (default {DEFAULT_MIN_TASKS})")
    ap.add_argument("--strict", action="store_true",
                    help="exit 1 when the sample is inadequate (for CI gating)")
    args = ap.parse_args()

    result = check_sample_adequacy(load_artifact(args.run), min_tasks=args.min_tasks)
    print(sample_adequacy_headline(result), file=sys.stderr)
    for check in result["checks"]:
        mark = "PASS" if check["passed"] else "FAIL"
        print(f"  [{mark}] {check['name']}: {check['detail']}", file=sys.stderr)

    print(json.dumps(result, indent=2))

    if args.strict and not result["passed"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
