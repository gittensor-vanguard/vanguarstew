"""CLI: gate whether a benchmark task set is well-formed and non-degenerate.

  python -m scripts.task_integrity tasks.json
  python -m scripts.task_integrity tasks.json --strict

The argument is a JSON array of task objects (``{"freeze_commit", "freeze_index", "revealed"}``),
as produced by ``taskgen.generate_tasks``. With --strict, exits non-zero when the task set is
degenerate (duplicate freeze points, empty revealed windows, malformed tasks).
"""

from __future__ import annotations

import argparse
import json
import sys

from benchmark.task_integrity import (
    check_task_integrity,
    task_integrity_headline,
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
    ap = argparse.ArgumentParser(description="Gate whether a benchmark task set is well-formed")
    ap.add_argument("tasks", help="a JSON array of task objects to check")
    ap.add_argument("--strict", action="store_true",
                    help="exit 1 when the task set is degenerate (for CI gating)")
    args = ap.parse_args(argv)

    result = check_task_integrity(load_tasks(args.tasks))
    print(task_integrity_headline(result), file=sys.stderr)
    for check in result["checks"]:
        mark = "PASS" if check["passed"] else "FAIL"
        print(f"  [{mark}] {check['name']}: {check['detail']}", file=sys.stderr)

    print(json.dumps(result, indent=2))

    return 1 if (args.strict and not result["passed"]) else 0


def main() -> None:
    sys.exit(run())


if __name__ == "__main__":
    main()
