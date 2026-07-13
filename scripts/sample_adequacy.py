"""CLI: gate whether a run judged and accounted for enough tasks to be trustworthy.

  python -m scripts.sample_adequacy run.json
  python -m scripts.sample_adequacy run.json --min-tasks 5 --strict

The argument is a ``run_eval --out`` artifact (single- or multi-repo). With --strict, exits
non-zero when the run judged fewer than ``--min-tasks`` tasks or didn't account for all of them.
"""

from __future__ import annotations

import argparse
import json
import sys

from benchmark.sample_adequacy import (
    DEFAULT_MIN_TASKS,
    check_sample_adequacy,
    sample_adequacy_headline,
)


def load_artifact(path: str) -> dict:
    """Load a JSON-object artifact, exiting with a clear message on a bad path or bad JSON.

    A path that reaches ``open()`` can raise ``OSError`` for several distinct reasons; each is
    reported with an actionable message (and exit code 2) rather than a raw traceback: the path is
    a directory, the file is unreadable (permission denied), or any other read failure. A broken
    symlink surfaces as ``FileNotFoundError`` (the target is missing) and is reported as not found.
    """
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        print(f"artifact not found: {path}", file=sys.stderr)
        raise SystemExit(2) from None
    except IsADirectoryError:
        print(f"artifact path is a directory, not a file: {path}", file=sys.stderr)
        raise SystemExit(2) from None
    except PermissionError as exc:
        print(f"permission denied reading artifact ({path}): {exc}", file=sys.stderr)
        raise SystemExit(2) from None
    except OSError as exc:
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
