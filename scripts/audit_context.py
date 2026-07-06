"""CLI: audit a frozen context JSON for residual forward-reference leaks.

  python -m scripts.audit_context path/to/.vanguarstew_context.json
  python -m scripts.audit_context path/to/context.json --strict   # exit 1 on any leak

Prints findings to stderr and the full JSON report on stdout. With ``--strict``, exits
non-zero when the context is not clean — a CI gate for leakage controls.
"""

from __future__ import annotations

import argparse
import json
import sys

from benchmark.leakage_audit import audit_context, audit_headline, is_clean


def load_context(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError(f"context must be a JSON object: {path}")
    return data


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Audit a frozen context for residual forward-reference leaks",
    )
    ap.add_argument("context", help="path to a frozen context JSON file")
    ap.add_argument(
        "--strict",
        action="store_true",
        help="exit 1 when the context is not clean (CI gating)",
    )
    args = ap.parse_args()

    try:
        context = load_context(args.context)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)

    findings = audit_context(context)
    report = {"clean": is_clean(context), "findings": findings}
    print(audit_headline(findings), file=sys.stderr)
    for row in findings:
        print(f"  {row['location']}: {row['value']!r} -> {row['masked']!r}", file=sys.stderr)
    print(json.dumps(report, indent=2))

    if args.strict and findings:
        sys.exit(1)


if __name__ == "__main__":
    main()
