"""CLI: print judge/objective blend weights from a replay artifact.

  python -m scripts.blend_weights result.json
"""

from __future__ import annotations

import argparse
import json
import sys

from benchmark.blend_weights import blend_weights_headline, summarize_blend_weights
from scripts.artifact_io import load_artifact  # re-exported for tests / callers

__all__ = ["load_artifact", "run"]

def run(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Report judge/objective blend weights")
    ap.add_argument("artifact", help="run_eval --out JSON artifact")
    args = ap.parse_args(argv)
    try:
        artifact = load_artifact(args.artifact)
    except SystemExit as exc:
        return int(exc.code)
    summary = summarize_blend_weights(artifact)
    print(blend_weights_headline(summary), file=sys.stderr)
    print(json.dumps(summary, indent=2))
    return 0

def main() -> None:
    raise SystemExit(run())

if __name__ == "__main__":
    main()
