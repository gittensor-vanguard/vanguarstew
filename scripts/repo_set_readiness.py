"""CLI: gate whether a repo-set config is ready for a leakage-safe acceptance run.

  python -m scripts.repo_set_readiness benchmark/repo_sets/curated.json
  python -m scripts.repo_set_readiness my-set.json --min-tuned 3 --strict

With --strict the process exits non-zero when the readiness gate fails.
"""

from __future__ import annotations

import argparse
import json
import sys

from benchmark.repo_set_readiness import (
    DEFAULT_MIN_HELD_OUT,
    DEFAULT_MIN_TUNED,
    check_readiness,
    readiness_headline,
)


def load_config(path: str) -> dict:
    """Load a JSON-object repo-set config, exiting with a clear message on a bad path or bad JSON.

    The common ``OSError`` subclasses are handled distinctly so the user gets an actionable
    message instead of a raw errno: ``FileNotFoundError`` (missing), ``PermissionError``
    (unreadable), ``IsADirectoryError`` (a directory, not a file), and any other ``OSError``.
    """
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except FileNotFoundError:
        print(f"config not found: {path}", file=sys.stderr)
        raise SystemExit(1) from None
    except PermissionError:
        print(f"config is not readable (check file permissions): {path}", file=sys.stderr)
        raise SystemExit(1) from None
    except IsADirectoryError:
        print(f"config path is a directory, not a file: {path}", file=sys.stderr)
        raise SystemExit(1) from None
    except OSError as exc:
        print(f"cannot read config ({path}): {exc}", file=sys.stderr)
        raise SystemExit(1) from None
    except ValueError as exc:
        # json.load raises a plain ValueError (not JSONDecodeError) on an integer literal
        # beyond the int-string-conversion limit (py3.11+); JSONDecodeError subclasses it.
        print(f"config is not valid JSON ({path}): {exc}", file=sys.stderr)
        raise SystemExit(1) from None
    if not isinstance(data, dict):
        raise ValueError(f"config must be a JSON object: {path}")
    return data


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Gate a repo-set config on acceptance-readiness criteria",
    )
    ap.add_argument("config", help="path to a repo-set JSON config")
    ap.add_argument("--min-tuned", type=int, default=DEFAULT_MIN_TUNED,
                    help=f"minimum tuned repos (default {DEFAULT_MIN_TUNED})")
    ap.add_argument("--min-held-out", type=int, default=DEFAULT_MIN_HELD_OUT,
                    help=f"minimum held-out repos (default {DEFAULT_MIN_HELD_OUT})")
    ap.add_argument("--strict", action="store_true",
                    help="exit 1 when the readiness gate fails (for CI gating)")
    args = ap.parse_args()

    try:
        config = load_config(args.config)
    except SystemExit as exc:
        raise SystemExit(exc.code) from None
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)

    result = check_readiness(config,
                             min_tuned=args.min_tuned,
                             min_held_out=args.min_held_out)
    print(readiness_headline(result), file=sys.stderr)
    for check in result["checks"]:
        mark = "PASS" if check["passed"] else "FAIL"
        print(f"  [{mark}] {check['name']}: {check['detail']}", file=sys.stderr)

    print(json.dumps(result, indent=2))

    if args.strict and not result["passed"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
