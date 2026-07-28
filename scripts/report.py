"""CLI: render a saved ``run_eval --out`` JSON artifact as Markdown.

  python -m scripts.report result.json
  python -m scripts.report result.json --out report.md

Path / JSON failures exit 2 (via ``scripts.artifact_io``).
"""

from __future__ import annotations

import argparse

from benchmark.report import DEFAULT_GAP_INSPECT_THRESHOLD, render_report
from scripts.artifact_io import load_artifact  # re-exported for tests / callers

__all__ = ["load_artifact", "main"]


def main() -> None:
    ap = argparse.ArgumentParser(description="Render a run_eval --out JSON artifact as Markdown")
    ap.add_argument("artifact", help="saved replay result JSON")
    ap.add_argument("--out", default=None, help="write Markdown to this path (default: stdout)")
    ap.add_argument("--gap-threshold", type=float, default=DEFAULT_GAP_INSPECT_THRESHOLD,
                    help="generalization gap above this value yields an inspect verdict "
                         f"(default {DEFAULT_GAP_INSPECT_THRESHOLD})")
    args = ap.parse_args()

    artifact = load_artifact(args.artifact)

    md = render_report(artifact, gap_inspect_threshold=args.gap_threshold)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(md)
    else:
        print(md, end="")


if __name__ == "__main__":
    main()
