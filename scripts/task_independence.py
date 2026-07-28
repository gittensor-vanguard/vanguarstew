"""CLI: gate whether a benchmark task set's replay windows are independent.

  python -m scripts.task_independence tasks.json
  python -m scripts.task_independence tasks.json --horizon 5 --strict

The argument is a JSON array of task objects (``{"freeze_commit", "freeze_index", "revealed"}``),
as produced by ``taskgen.generate_tasks``. Pass the ``--horizon`` the tasks were generated with.
With --strict, exits non-zero when any two tasks' replay windows overlap.
"""

from __future__ import annotations

import argparse
import errno
import json
import os
import sys

from benchmark.task_independence import (
    DEFAULT_HORIZON,
    check_task_independence,
    task_independence_headline,
)


def load_tasks(path: str):
    """Load a JSON task array, exiting with a clear message on a bad path or bad JSON.

    Path problems get a specific, actionable message instead of a raw errno string: a broken
    symlink (dangling target), a symlink loop, ``FileNotFoundError`` (missing),
    ``PermissionError`` (unreadable -- including a directory on Windows), ``IsADirectoryError``
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
            print(f"task file is a broken symlink (target does not exist): {path}", file=sys.stderr)
        else:
            print(f"task file not found: {path}", file=sys.stderr)
        raise SystemExit(2) from None
    except PermissionError:
        # Windows raises PermissionError (not IsADirectoryError) when ``path`` is a directory.
        print(f"task file is not readable (check file permissions): {path}", file=sys.stderr)
        raise SystemExit(2) from None
    except IsADirectoryError:
        print(f"task file path is a directory, not a file: {path}", file=sys.stderr)
        raise SystemExit(2) from None
    except OSError as exc:
        if getattr(exc, "errno", None) == errno.ELOOP:
            print(f"task file path is a symlink loop: {path}", file=sys.stderr)
        else:
            print(f"cannot read task file ({path}): {exc}", file=sys.stderr)
        raise SystemExit(2) from None
    except ValueError as exc:
        # json.load raises a plain ValueError (not JSONDecodeError) on an integer literal
        # beyond the int-string-conversion limit (py3.11+); JSONDecodeError subclasses it.
        print(f"task file is not valid JSON ({path}): {exc}", file=sys.stderr)
        raise SystemExit(2) from None
    return data


def run(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Gate whether a task set's replay windows are independent")
    ap.add_argument("tasks", help="a JSON array of task objects to check")
    ap.add_argument("--horizon", type=int, default=DEFAULT_HORIZON,
                    help=f"replay horizon the tasks were generated with (default {DEFAULT_HORIZON})")
    ap.add_argument("--strict", action="store_true",
                    help="exit 1 when the replay windows overlap (for CI gating)")
    args = ap.parse_args(argv)

    result = check_task_independence(load_tasks(args.tasks), horizon=args.horizon)
    print(task_independence_headline(result), file=sys.stderr)
    for check in result["checks"]:
        mark = "PASS" if check["passed"] else "FAIL"
        print(f"  [{mark}] {check['name']}: {check['detail']}", file=sys.stderr)

    print(json.dumps(result, indent=2))

    return 1 if (args.strict and not result["passed"]) else 0


def main() -> None:
    sys.exit(run())


if __name__ == "__main__":
    main()
