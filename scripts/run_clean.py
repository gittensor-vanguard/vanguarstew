"""CLI: gate whether a replay artifact completed without recorded errors.

  python -m scripts.run_clean result.json
  python -m scripts.run_clean result.json --strict

``--strict``: exit 1 when any error is present (CI gate). Without ``--strict``, prints the
report and exits 0.

Path / JSON failures exit 2 (via ``scripts.artifact_io``).
"""

from __future__ import annotations

import argparse
import json
import sys

from benchmark.run_clean import check_run_clean, run_clean_headline
from scripts.artifact_io import load_artifact  # re-exported for tests / callers

__all__ = ["load_artifact", "main", "run"]


def run(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Gate whether a replay artifact has no errors")
    ap.add_argument("artifact", help="run_eval --out JSON artifact")
    ap.add_argument("--strict", action="store_true",
                    help="exit 1 when errors are present (CI gate)")
    args = ap.parse_args(argv)
    try:
        artifact = load_artifact(args.artifact)
    except SystemExit as exc:
        return int(exc.code)
    result = check_run_clean(artifact)
    print(run_clean_headline(result), file=sys.stderr)
    print(json.dumps(result, indent=2))
    if args.strict and not result["passed"]:
        return 1
    return 0


def main() -> None:
    raise SystemExit(run())


if __name__ == "__main__":
    main()
