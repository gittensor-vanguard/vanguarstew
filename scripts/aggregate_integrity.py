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
    with open(path, "r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError(f"artifact must be a JSON object: {path}")
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

    try:
        artifact = load_artifact(args.artifact)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)

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
