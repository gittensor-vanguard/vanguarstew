"""CLI: gate whether a multi-repo artifact's headline aggregates match per-repo means.

  python -m scripts.aggregate_integrity result.json
  python -m scripts.aggregate_integrity result.json --strict

``--strict``: exit with code 1 when :func:`benchmark.aggregate_integrity.check_aggregate_integrity`
reports ``passed: false``. Without ``--strict`` the JSON result is printed either way.
"""

from __future__ import annotations

import argparse
import json
import sys

from benchmark.aggregate_integrity import (
    DEFAULT_TOLERANCE,
    check_aggregate_integrity,
    integrity_headline,
)


def load_artifact(path: str) -> dict:
    """Load a JSON-object artifact, exiting with a clear message on a bad path or bad JSON.

    Each failure mode gets its own actionable message instead of a raw errno string: the path is
    missing, unreadable, or a directory; the file is not valid JSON; or the root value is not an
    object. Every case exits 1 via ``SystemExit`` so the caller needs no error handling.
    """
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except FileNotFoundError:
        print(f"artifact not found: {path}", file=sys.stderr)
        raise SystemExit(1) from None
    except PermissionError:
        print(f"artifact is not readable (check file permissions): {path}", file=sys.stderr)
        raise SystemExit(1) from None
    except IsADirectoryError:
        print(f"artifact path is a directory, not a file: {path}", file=sys.stderr)
        raise SystemExit(1) from None
    except OSError:
        print(f"cannot read artifact: {path}", file=sys.stderr)
        raise SystemExit(1) from None
    except ValueError as exc:
        # json.load raises JSONDecodeError (a ValueError) for malformed JSON, and a plain
        # ValueError for an integer literal beyond the int-string-conversion limit (py3.11+).
        print(f"artifact is not valid JSON ({path}): {exc}", file=sys.stderr)
        raise SystemExit(1) from None
    if not isinstance(data, dict):
        print(f"artifact must be a JSON object: {path}", file=sys.stderr)
        raise SystemExit(1)
    return data


def main() -> None:
    ap = argparse.ArgumentParser(description="Gate a multi-repo artifact on aggregate integrity")
    ap.add_argument("artifact", help="path to a run_eval --out JSON artifact")
    ap.add_argument("--tolerance", type=float, default=DEFAULT_TOLERANCE,
                    help=("max |round(headline,3) - round(per-repo mean,3)| "
                          f"(default {DEFAULT_TOLERANCE})"))
    ap.add_argument("--strict", action="store_true",
                    help="exit 1 when the aggregate integrity gate fails (for CI gating)")
    args = ap.parse_args()

    artifact = load_artifact(args.artifact)

    result = check_aggregate_integrity(artifact, tolerance=args.tolerance)
    print(integrity_headline(result), file=sys.stderr)
    for check in result["checks"]:
        mark = "PASS" if check["passed"] else "FAIL"
        print(f"  [{mark}] {check['name']}: {check['detail']}", file=sys.stderr)

    print(json.dumps(result, indent=2))

    if args.strict and not result["passed"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
