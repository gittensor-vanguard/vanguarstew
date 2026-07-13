"""CLI: gate whether a multi-repo run scored enough of its repos to be trusted.

  python -m scripts.skip_budget run.json
  python -m scripts.skip_budget run.json --min-scored 5 --max-skip-rate 0.2 --strict

The argument is a ``run_multi_replay --out`` artifact. With --strict, exits non-zero when too few
repos scored or too many were skipped.
"""

from __future__ import annotations

import argparse
import json
import sys

from benchmark.skip_budget import (
    DEFAULT_MAX_SKIP_RATE,
    DEFAULT_MIN_SCORED,
    check_skip_budget,
    skip_budget_headline,
)


def load_artifact(path: str) -> dict:
    """Load a JSON-object artifact, exiting with a clear message on a bad path or bad JSON.

    The common ``OSError`` subclasses are handled distinctly so the user gets an actionable
    message instead of a raw traceback: ``FileNotFoundError`` (missing), ``PermissionError``
    (unreadable), ``IsADirectoryError`` (a directory, not a file), and any other ``OSError``
    (e.g. an I/O error, whose message is echoed). Mirrors the merged ``generalization_gate``
    (#1446) / ``objective_integrity`` (#1377) CLIs.
    """
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        print(f"artifact not found: {path}", file=sys.stderr)
        raise SystemExit(2) from None
    except PermissionError:
        print(f"artifact is not readable (check file permissions): {path}", file=sys.stderr)
        raise SystemExit(2) from None
    except IsADirectoryError:
        print(f"artifact path is a directory, not a file: {path}", file=sys.stderr)
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
