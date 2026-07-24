"""CLI: gate whether a replay artifact's judge tally is internally consistent.

  python -m scripts.tally_integrity result.json
  python -m scripts.tally_integrity result.json --strict

With --strict the process exits non-zero when tally accounting is inconsistent.
"""

from __future__ import annotations

import argparse
import json
import sys

from benchmark.tally_integrity import check_tally_integrity, integrity_headline
from scripts.artifact_io import load_artifact  # re-exported for tests / callers

__all__ = ["load_artifact", "main"]

def main() -> None:
    ap = argparse.ArgumentParser(description="Gate a replay artifact on judge tally integrity")
    ap.add_argument("artifact", help="path to a run_eval --out JSON artifact")
    ap.add_argument("--strict", action="store_true",
                    help="exit 1 when the tally integrity gate fails (for CI gating)")
    args = ap.parse_args()

    artifact = load_artifact(args.artifact)

    result = check_tally_integrity(artifact)
    print(integrity_headline(result), file=sys.stderr)
    for check in result["checks"]:
        mark = "PASS" if check["passed"] else "FAIL"
        print(f"  [{mark}] {check['name']}: {check['detail']}", file=sys.stderr)

    print(json.dumps(result, indent=2))

    if args.strict and not result["passed"]:
        sys.exit(1)

if __name__ == "__main__":
    main()
