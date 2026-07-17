"""CLI: gate whether a multi-repo replay run covered enough breadth.

  python -m scripts.repo_coverage result.json                     # report SUFFICIENT / INSUFFICIENT
  python -m scripts.repo_coverage result.json --min-repos 3 --strict   # exit 1 on insufficient

``result.json`` is a ``run_eval --out`` artifact (multi-repo or --generalization). With --strict
the process exits non-zero when the coverage gate fails.
"""

from __future__ import annotations

import argparse
import errno
import json
import os
import sys

from benchmark.coverage import (
    DEFAULT_MAX_SKIPPED,
    DEFAULT_MIN_REPOS,
    DEFAULT_MIN_TASKS,
    check_coverage,
    coverage_headline,
)


def load_artifact(path: str) -> dict:
    """Load a JSON-object artifact, exiting with a clear message on a bad path or bad JSON.

    Path problems get a specific, actionable message instead of a bare exception string: a
    broken symlink (dangling target), a symlink loop, ``FileNotFoundError`` (missing),
    ``PermissionError`` (unreadable -- including a directory on Windows), ``IsADirectoryError``
    (a directory on POSIX), and any other ``OSError``.

    Broken-symlink detection runs *after* ``open`` fails (``FileNotFoundError`` + ``islink``),
    so there is no ``exists``/``open`` TOCTOU pre-check that can raise on a symlink loop.
    """
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        if os.path.islink(path):
            print(f"artifact is a broken symlink (target does not exist): {path}", file=sys.stderr)
        else:
            print(f"artifact not found: {path}", file=sys.stderr)
        raise SystemExit(1) from None
    except PermissionError:
        print(f"artifact is not readable (check file permissions): {path}", file=sys.stderr)
        raise SystemExit(1) from None
    except IsADirectoryError:
        print(f"artifact path is a directory, not a file: {path}", file=sys.stderr)
        raise SystemExit(1) from None
    except OSError as exc:
        if getattr(exc, "errno", None) == errno.ELOOP:
            print(f"artifact path is a symlink loop: {path}", file=sys.stderr)
        else:
            print(f"cannot read artifact ({path}): {exc}", file=sys.stderr)
        raise SystemExit(1) from None
    except ValueError as exc:
        # json.load raises a plain ValueError (not JSONDecodeError) on an integer literal
        # beyond the int-string-conversion limit (py3.11+); JSONDecodeError subclasses it.
        print(f"artifact is not valid JSON ({path}): {exc}", file=sys.stderr)
        raise SystemExit(1) from None
    if not isinstance(data, dict):
        print(f"artifact must be a JSON object: {path}", file=sys.stderr)
        raise SystemExit(1) from None
    return data


def main() -> None:
    ap = argparse.ArgumentParser(description="Gate a multi-repo replay run on coverage breadth")
    ap.add_argument("artifact", help="path to a run_eval --out JSON artifact")
    ap.add_argument("--min-repos", type=int, default=DEFAULT_MIN_REPOS,
                    help=f"minimum scored repos (default {DEFAULT_MIN_REPOS})")
    ap.add_argument("--max-skipped", type=int, default=DEFAULT_MAX_SKIPPED,
                    help=f"maximum skipped repos (default {DEFAULT_MAX_SKIPPED})")
    ap.add_argument("--min-tasks", type=int, default=DEFAULT_MIN_TASKS,
                    help=f"minimum total tasks across scored repos (default {DEFAULT_MIN_TASKS})")
    ap.add_argument("--strict", action="store_true",
                    help="exit 1 when the coverage gate fails (for CI gating)")
    args = ap.parse_args()

    artifact = load_artifact(args.artifact)

    result = check_coverage(artifact,
                            min_repos=args.min_repos,
                            max_skipped=args.max_skipped,
                            min_tasks=args.min_tasks)
    print(coverage_headline(result), file=sys.stderr)
    for check in result["checks"]:
        mark = "PASS" if check["passed"] else "FAIL"
        print(f"  [{mark}] {check['name']}: {check['detail']}", file=sys.stderr)

    print(json.dumps(result, indent=2))

    if args.strict and not result["passed"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
