"""CLI: print judge disagreement outlook from a replay artifact.

  python -m scripts.disagreement_outlook result.json
  python -m scripts.disagreement_outlook result.json --stable-threshold 0.2

Path / JSON failures exit 2 (via ``scripts.artifact_io``).
"""

from __future__ import annotations

import argparse
import json
import sys

from benchmark.disagreement_outlook import (
    DEFAULT_STABLE_THRESHOLD,
    disagreement_outlook_headline,
    summarize_disagreement_outlook,
)
from scripts.artifact_io import load_artifact  # re-exported for tests / callers

__all__ = ["load_artifact", "main", "run"]


def run(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Report judge disagreement outlook")
    ap.add_argument("artifact", help="run_eval --out JSON artifact")
    ap.add_argument(
        "--stable-threshold",
        type=float,
        default=DEFAULT_STABLE_THRESHOLD,
        help=f"disagreement rate at or below this is stable (default {DEFAULT_STABLE_THRESHOLD})",
    )
    args = ap.parse_args(argv)
    try:
        artifact = load_artifact(args.artifact)
    except SystemExit as exc:
        return int(exc.code)
    summary = summarize_disagreement_outlook(
        artifact,
        stable_threshold=args.stable_threshold,
    )
    print(disagreement_outlook_headline(summary), file=sys.stderr)
    print(json.dumps(summary, indent=2))
    return 0


def main() -> None:
    raise SystemExit(run())


if __name__ == "__main__":
    main()
