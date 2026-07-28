"""CLI: gate whether a multi-repo run scored enough of its repos to be trusted.

  python -m scripts.skip_budget run.json
  python -m scripts.skip_budget run.json --min-scored 5 --max-skip-rate 0.2 --strict

The argument is a ``run_multi_replay --out`` artifact. With --strict, exits non-zero when too few
repos scored or too many were skipped.
"""

from __future__ import annotations

import argparse
import errno
import json
import os
import sys

from benchmark.skip_budget import (
    DEFAULT_MAX_SKIP_RATE,
    DEFAULT_MIN_SCORED,
    check_skip_budget,
    skip_budget_headline,
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


def run(argv=None) -> int:
    """Parse ``argv``, evaluate the gate, print the report, and return the intended exit code."""
    ap = argparse.ArgumentParser(description="Gate whether a multi-repo run scored enough repos")
    ap.add_argument("run", help="the run_multi_replay --out JSON artifact to check")
    ap.add_argument("--min-scored", type=int, default=DEFAULT_MIN_SCORED,
                    help=f"minimum repos that must score (default {DEFAULT_MIN_SCORED})")
    ap.add_argument("--max-skip-rate", type=float, default=DEFAULT_MAX_SKIP_RATE,
                    help=f"maximum skipped fraction (default {DEFAULT_MAX_SKIP_RATE})")
    ap.add_argument("--strict", action="store_true",
                    help="exit 1 when too many repos were skipped (for CI gating)")
    args = ap.parse_args(argv)

    result = check_skip_budget(load_artifact(args.run), min_scored=args.min_scored,
                               max_skip_rate=args.max_skip_rate)
    print(skip_budget_headline(result), file=sys.stderr)
    for check in result["checks"]:
        mark = "PASS" if check["passed"] else "FAIL"
        print(f"  [{mark}] {check['name']}: {check['detail']}", file=sys.stderr)

    print(json.dumps(result, indent=2))

    return 1 if (args.strict and not result["passed"]) else 0


def main() -> None:
    sys.exit(run())


if __name__ == "__main__":
    main()
