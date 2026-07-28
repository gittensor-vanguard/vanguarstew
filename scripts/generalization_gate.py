"""CLI: gate whether a --generalization run generalized to its held-out repos.

  python -m scripts.generalization_gate run.json
  python -m scripts.generalization_gate run.json --max-gap 0.08 --min-held-out-repos 4 --strict

The argument is a ``run_multi_replay --generalization --out`` artifact. With --strict, exits
non-zero when the run did not generalize (too large a tuned-vs-held-out gap, or too few held-out
repos).
"""

from __future__ import annotations

import argparse
import errno
import json
import os
import sys

from benchmark.generalization_gate import (
    DEFAULT_MAX_GAP,
    DEFAULT_MIN_HELD_OUT_REPOS,
    check_generalization,
    generalization_headline,
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


def main() -> None:
    ap = argparse.ArgumentParser(description="Gate whether a --generalization run generalized")
    ap.add_argument("run", help="the run_multi_replay --generalization --out JSON artifact")
    ap.add_argument("--max-gap", type=float, default=DEFAULT_MAX_GAP,
                    help=f"maximum tuned-minus-held-out composite drop (default {DEFAULT_MAX_GAP})")
    ap.add_argument("--min-held-out-repos", type=int, default=DEFAULT_MIN_HELD_OUT_REPOS,
                    help=f"minimum held-out repos scored (default {DEFAULT_MIN_HELD_OUT_REPOS})")
    ap.add_argument("--strict", action="store_true",
                    help="exit 1 when the run did not generalize (for CI gating)")
    args = ap.parse_args()

    result = check_generalization(load_artifact(args.run), max_gap=args.max_gap,
                                  min_held_out_repos=args.min_held_out_repos)
    print(generalization_headline(result), file=sys.stderr)
    for check in result["checks"]:
        mark = "PASS" if check["passed"] else "FAIL"
        print(f"  [{mark}] {check['name']}: {check['detail']}", file=sys.stderr)

    print(json.dumps(result, indent=2))

    if args.strict and not result["passed"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
