"""CLI: rank several replay artifacts against each other.

  python -m scripts.leaderboard agentA=a.json agentB=b.json agentC=c.json
  python -m scripts.leaderboard a.json b.json          # labels default to filenames

Each argument is an artifact path, optionally prefixed with ``label=`` to name the entry
(otherwise the filename is used). Prints a ranked table and the full JSON summary.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

from benchmark.leaderboard import leaderboard_headline, rank


def load_artifact(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError(f"artifact must be a JSON object: {path}")
    return data


def _split_label(arg: str):
    """``label=path`` -> ``(label, path)``; a bare ``path`` -> ``(basename, path)``."""
    if "=" in arg:
        label, path = arg.split("=", 1)
        return (label or os.path.basename(path)), path
    return os.path.basename(arg), arg


def main() -> None:
    ap = argparse.ArgumentParser(description="Rank replay artifacts by headline composite score")
    ap.add_argument("artifacts", nargs="+", help="artifact paths, each optionally 'label=path'")
    args = ap.parse_args()

    try:
        entries = [(label, load_artifact(path)) for label, path in map(_split_label, args.artifacts)]
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)

    summary = rank(entries)

    def _c(value):
        return f"{value:.3f}" if isinstance(value, (int, float)) and not isinstance(value, bool) else "n/a"

    print(leaderboard_headline(summary), file=sys.stderr)
    for row in summary["ranking"]:
        print(f"  #{row['rank']} {row['label']}: {row['composite_mean']:.3f} "
              f"({row['delta_from_best']:+.3f}) "
              f"[judge {_c(row['judge_mean'])}, objective {_c(row['objective_mean'])}]",
              file=sys.stderr)
    for label in summary["unscored"]:
        print(f"  (unscored) {label}", file=sys.stderr)

    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
