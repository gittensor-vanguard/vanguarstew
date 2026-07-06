"""CLI: render a saved replay artifact as a Markdown report.

  python -m scripts.report result.json                 # print to stdout
  python -m scripts.report result.json --out report.md  # write to a file

Accepts any artifact ``run_eval`` writes (single-repo, multi-repo, or --generalization).
"""

from __future__ import annotations

import argparse
import json
import sys

from benchmark.report import render_report


def load_artifact(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError(f"artifact must be a JSON object: {path}")
    return data


def main() -> None:
    ap = argparse.ArgumentParser(description="Render a replay result artifact as Markdown")
    ap.add_argument("artifact", help="path to a run_eval --out JSON artifact")
    ap.add_argument("--out", default=None, help="write the report here instead of stdout")
    args = ap.parse_args()

    report = render_report(load_artifact(args.artifact))
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(report)
        print(f"wrote report to {args.out}", file=sys.stderr)
    else:
        print(report)


if __name__ == "__main__":
    main()
