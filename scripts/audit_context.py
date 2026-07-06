"""CLI: audit a frozen context (``.vanguarstew_context.json``) for residual leaks.

  python -m scripts.audit_context path/to/.vanguarstew_context.json
  python -m scripts.audit_context ctx.json --strict   # exit 1 if any leak is found (CI gate)

Prints each residual forward-reference finding and a headline. With --strict it exits non-zero
when the context is not leakage-clean, so it can gate a pipeline the way --fail-under gates a
score.
"""

from __future__ import annotations

import argparse
import json
import sys

from benchmark.leakage_audit import audit_context, audit_headline


def load_context(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError(f"context must be a JSON object: {path}")
    return data


def main() -> None:
    ap = argparse.ArgumentParser(description="Audit a frozen context for forward-reference leaks")
    ap.add_argument("context", help="path to a frozen .vanguarstew_context.json")
    ap.add_argument("--strict", action="store_true",
                    help="exit 1 when any leak is found (for CI leakage-gating)")
    args = ap.parse_args()

    findings = audit_context(load_context(args.context))
    print(audit_headline(findings), file=sys.stderr)
    for finding in findings:
        print(f"  {finding['field']}: {finding['text']!r} -> {finding['scrubbed']!r}",
              file=sys.stderr)

    print(json.dumps(findings, indent=2))

    if args.strict and findings:
        sys.exit(1)


if __name__ == "__main__":
    main()
