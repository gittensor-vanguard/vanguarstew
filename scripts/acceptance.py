"""CLI: gate a ``--generalization`` result against the M3/M4 acceptance criteria.

  python -m scripts.acceptance gen.json                       # report PASS/FAIL
  python -m scripts.acceptance gen.json --max-gap 0.10 --strict   # exit 1 on FAIL (CI gate)

``gen.json`` is a ``run_eval --generalization --out`` artifact. With --strict the process exits
non-zero when the acceptance checks fail, so the M3/M4 acceptance run can gate CI.
"""

from __future__ import annotations

import argparse
import errno
import json
import os
import sys

from benchmark.acceptance import (
    DEFAULT_MAX_GAP,
    DEFAULT_MIN_SCORED_REPOS,
    acceptance_headline,
    check_acceptance,
)


def load_artifact(path: str) -> dict:
    """Load a JSON-object artifact, exiting with a clear message on a bad path or bad JSON.

    Path problems get a specific, actionable message instead of a raw traceback / errno string:
    a broken symlink (dangling target), a symlink loop, ``FileNotFoundError`` (missing),
    ``PermissionError`` (unreadable), ``IsADirectoryError`` (a directory, not a file), and any
    other ``OSError``.

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
        raise ValueError(f"artifact must be a JSON object: {path}")
    return data


def main() -> None:
    ap = argparse.ArgumentParser(description="Gate a --generalization result on M3/M4 acceptance")
    ap.add_argument("artifact", help="path to a run_eval --generalization --out JSON artifact")
    ap.add_argument("--max-gap", type=float, default=DEFAULT_MAX_GAP,
                    help=f"max acceptable tuned-minus-held-out gap (default {DEFAULT_MAX_GAP})")
    ap.add_argument("--min-scored-repos", type=int, default=DEFAULT_MIN_SCORED_REPOS,
                    help=f"min scored repos per partition (default {DEFAULT_MIN_SCORED_REPOS})")
    ap.add_argument("--strict", action="store_true",
                    help="exit 1 when the acceptance checks fail (for CI gating)")
    args = ap.parse_args()

    try:
        artifact = load_artifact(args.artifact)
    except SystemExit as exc:
        raise SystemExit(exc.code) from None
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)

    result = check_acceptance(artifact,
                              max_gap=args.max_gap, min_scored_repos=args.min_scored_repos)
    print(acceptance_headline(result), file=sys.stderr)
    for check in result["checks"]:
        mark = "PASS" if check["passed"] else "FAIL"
        print(f"  [{mark}] {check['name']}: {check['detail']}", file=sys.stderr)

    print(json.dumps(result, indent=2))

    if args.strict and not result["passed"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
