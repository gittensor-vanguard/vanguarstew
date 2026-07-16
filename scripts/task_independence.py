"""CLI: gate whether a benchmark task set's replay windows are independent.

  python -m scripts.task_independence tasks.json
  python -m scripts.task_independence tasks.json --horizon 5 --strict

The argument is a JSON array of task objects (``{"freeze_commit", "freeze_index", "revealed"}``),
as produced by ``taskgen.generate_tasks``. Pass the ``--horizon`` the tasks were generated with.
With --strict, exits non-zero when any two tasks' replay windows overlap.
"""

from __future__ import annotations

import argparse
import json
import sys

from benchmark.task_independence import (
    DEFAULT_HORIZON,
    check_task_independence,
    task_independence_headline,
)


def load_tasks(path: str):
    """Load a JSON task array, exiting with a clear message on a bad path or bad JSON."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except OSError as exc:
        # Covers missing file, permission denied, and "is a directory".
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
