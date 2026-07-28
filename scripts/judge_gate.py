"""CLI: gate whether a run's pairwise judge was robust enough to trust.

  python -m scripts.judge_gate result.json
  python -m scripts.judge_gate result.json --max-disagreement 0.2 --strict

``result.json`` is a ``run_eval --out`` artifact. With --strict, exits non-zero when the judge
is not robust.
"""

from __future__ import annotations

import argparse
import errno
import json
import os
import sys

from benchmark.judge_gate import (
    DEFAULT_MAX_DISAGREEMENT,
    DEFAULT_MIN_DUAL_ORDER_TASKS,
    check_judge,
    judge_headline,
)


def load_artifact(path: str) -> dict:
    """Load a JSON-object artifact, exiting with a clear message on a bad path or bad JSON.

    Path problems get a specific, actionable message instead of a raw traceback / errno string:
    a broken symlink (dangling target), a symlink loop, ``FileNotFoundError`` (missing),
    ``PermissionError`` (unreadable — including a directory on Windows), ``IsADirectoryError``
    (a directory on POSIX), ``NotADirectoryError`` (a parent component is a file), and any
    other ``OSError``. Load errors exit 2 so CI can tell a bad path from a failed gate (exit 1).

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


def run(argv=None) -> int:
    """Parse ``argv``, evaluate the gate, print the result, and return the intended exit code."""
    ap = argparse.ArgumentParser(description="Gate a run on pairwise-judge robustness")
    ap.add_argument("artifact", help="path to a run_eval --out JSON artifact")
    ap.add_argument("--max-disagreement", type=float, default=DEFAULT_MAX_DISAGREEMENT,
                    help=f"max order-disagreement rate (default {DEFAULT_MAX_DISAGREEMENT})")
    ap.add_argument("--min-dual-order-tasks", type=int, default=DEFAULT_MIN_DUAL_ORDER_TASKS,
                    help=f"min tasks judged in both orders (default {DEFAULT_MIN_DUAL_ORDER_TASKS})")
    ap.add_argument("--strict", action="store_true",
                    help="exit 1 when the judge is not robust (for CI gating)")
    args = ap.parse_args(argv)

    try:
        artifact = load_artifact(args.artifact)
    except SystemExit as exc:
        return int(exc.code)

    # A loadable artifact can still be arbitrarily malformed inside, so the gate check and
    # rendering get the same clean-error treatment as loading -- a CI step must never see a
    # raw traceback from a bad artifact.
    try:
        result = check_judge(artifact,
                             max_disagreement=args.max_disagreement,
                             min_dual_order_tasks=args.min_dual_order_tasks)
        print(judge_headline(result), file=sys.stderr)
        for check in result["checks"]:
            mark = "PASS" if check["passed"] else "FAIL"
            print(f"  [{mark}] {check['name']}: {check['detail']}", file=sys.stderr)
        print(json.dumps(result, indent=2))
    except (KeyError, TypeError, ValueError) as exc:
        print(f"judge_gate: cannot evaluate artifact: {exc!r}", file=sys.stderr)
        return 1

    if args.strict and not result["passed"]:
        return 1
    return 0


def main() -> None:
    raise SystemExit(run())


if __name__ == "__main__":
    main()
