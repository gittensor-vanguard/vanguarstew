"""CLI: rank several replay artifacts against each other.

  python -m scripts.leaderboard agentA=a.json agentB=b.json agentC=c.json
  python -m scripts.leaderboard a.json b.json          # labels default to filenames

Each argument is an artifact path, optionally prefixed with ``label=`` to name the entry
(otherwise the filename is used). Prints a ranked table and the full JSON summary.

Path / JSON failures exit 2 (via ``scripts.artifact_io``).
"""

from __future__ import annotations

import argparse
import json
import os
import sys

from benchmark.leaderboard import leaderboard_headline, rank
from scripts.artifact_io import load_artifact  # re-exported for tests / callers

__all__ = ["load_artifact", "main"]


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

    entries = [(label, load_artifact(path)) for label, path in map(_split_label, args.artifacts)]

    summary = rank(entries)

    def _c(value):
        return f"{value:.3f}" if isinstance(value, (int, float)) and not isinstance(value, bool) else "n/a"

    print(leaderboard_headline(summary), file=sys.stderr)
    for row in summary["ranking"]:
        print(f"  #{row['rank']} {row['label']}: {row['composite_mean']:.3f} "
              f"({row['delta_from_best']:+.3f}) "
              f"[judge {_c(row['judge_mean'])}, objective {_c(row['objective_mean'])}] "
              f"[foresight — modules {_c(row['module_recall_mean'])}, "
              f"kinds {_c(row['kind_recall_mean'])}, "
              f"release {_c(row['release_accuracy'])}]",
              file=sys.stderr)
    for label in summary["unscored"]:
        print(f"  (unscored) {label}", file=sys.stderr)

    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
