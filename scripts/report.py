"""CLI: render a saved ``run_eval --out`` JSON artifact as Markdown.

  python -m scripts.report result.json
  python -m scripts.report result.json --out report.md
"""

from __future__ import annotations

import argparse
import json

from benchmark.report import DEFAULT_GAP_INSPECT_THRESHOLD, render_report


def load_artifact(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError(f"artifact must be a JSON object: {path}")
    return data


def main() -> None:
    ap = argparse.ArgumentParser(description="Render a run_eval --out JSON artifact as Markdown")
    ap.add_argument("artifact", help="saved replay result JSON")
    ap.add_argument("--out", default=None, help="write Markdown to this path (default: stdout)")
    ap.add_argument("--gap-threshold", type=float, default=DEFAULT_GAP_INSPECT_THRESHOLD,
                    help="generalization gap above this value yields an inspect verdict "
                         f"(default {DEFAULT_GAP_INSPECT_THRESHOLD})")
    args = ap.parse_args()
    md = render_report(load_artifact(args.artifact), gap_inspect_threshold=args.gap_threshold)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(md)
    else:
        print(md, end="")


if __name__ == "__main__":
    main()
