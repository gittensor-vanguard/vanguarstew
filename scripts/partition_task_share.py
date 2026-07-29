"""CLI: print scored-task distribution across generalization partitions.

  python -m scripts.partition_task_share result.json

Path / JSON failures exit 2 (via ``scripts.artifact_io``).
"""

from __future__ import annotations

import argparse
import json
import sys

from benchmark.partition_task_share import (
    partition_task_share_headline,
    summarize_partition_task_share,
)
from scripts.artifact_io import load_artifact  # re-exported for tests / callers

__all__ = ["load_artifact", "main", "run"]


def run(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="Report scored-task distribution across generalization partitions",
    )
    ap.add_argument("artifact", help="run_eval --out JSON artifact")
    args = ap.parse_args(argv)
    try:
        artifact = load_artifact(args.artifact)
    except SystemExit as exc:
        return int(exc.code)
    summary = summarize_partition_task_share(artifact)
    print(partition_task_share_headline(summary), file=sys.stderr)
    print(json.dumps(summary, indent=2))
    return 0


def main() -> None:
    raise SystemExit(run())


if __name__ == "__main__":
    main()
