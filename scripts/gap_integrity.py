"""CLI: gate whether a generalization artifact's gap matches its partition scores.

  python -m scripts.gap_integrity report.json
  python -m scripts.gap_integrity report.json --tolerance 0.001 --strict

With --strict the process exits non-zero when the gap integrity gate fails.
"""

from __future__ import annotations

import argparse
import json
import sys

from benchmark.gap_integrity import (
    DEFAULT_TOLERANCE,
    check_gap_integrity,
    integrity_headline,
)


def load_artifact(path: str) -> dict:
    """Load a JSON-object artifact, exiting with a clear message on a bad path or bad JSON.

    The common ``OSError`` subclasses are handled distinctly so the user gets an actionable
    message instead of a raw errno string: ``FileNotFoundError`` (missing), ``PermissionError``
    (unreadable), ``IsADirectoryError`` (a directory, not a file), and any other ``OSError``.
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
    except OSError as exc:
        print(f"cannot read artifact ({path}): {exc}", file=sys.stderr)
        raise SystemExit(1) from None
    except ValueError as exc:
        # json.JSONDecodeError subclasses ValueError; a plain ValueError is also raised for an
        # integer literal beyond the int-string-conversion limit (py3.11+) - same message either way.
        print(f"artifact is not valid JSON ({path}): {exc}", file=sys.stderr)
        raise SystemExit(1) from None
    if not isinstance(data, dict):
        print(f"artifact must be a JSON object: {path}", file=sys.stderr)
        raise SystemExit(1)
    return data


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Gate a --generalization artifact on generalization-gap integrity",
    )
    ap.add_argument("artifact", help="path to a run_eval --generalization JSON artifact")
    ap.add_argument("--tolerance", type=float, default=DEFAULT_TOLERANCE,
                    help=("max allowed |round(reported,3) - round(tuned-held_out,3)| "
                          f"(default {DEFAULT_TOLERANCE}; use for float-noisy artifacts)"))
    ap.add_argument("--strict", action="store_true",
                    help="exit 1 when the gap integrity gate fails (for CI gating)")
    args = ap.parse_args()

    artifact = load_artifact(args.artifact)

    result = check_gap_integrity(artifact, tolerance=args.tolerance)
    print(integrity_headline(result), file=sys.stderr)
    for check in result["checks"]:
        mark = "PASS" if check["passed"] else "FAIL"
        print(f"  [{mark}] {check['name']}: {check['detail']}", file=sys.stderr)

    print(json.dumps(result, indent=2))

    if args.strict and not result["passed"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
