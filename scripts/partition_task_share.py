"""CLI: print scored-task distribution across generalization partitions.

  python -m scripts.partition_task_share result.json

Exits 2 when the artifact path is missing, unreadable, invalid JSON, or not an object.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

from benchmark.partition_task_share import (
    partition_task_share_headline,
    summarize_partition_task_share,
)


def load_artifact(path: str) -> dict:
    # A dangling symlink surfaces from open() as FileNotFoundError, which reads as "you typed
    # the wrong path" and hides the real problem: the path is right but its target is gone.
    # Name it before opening so the message points at the link, not a missing file.
    if os.path.islink(path) and not os.path.exists(path):
        print(f"artifact is a broken symlink (its target is missing): {path}", file=sys.stderr)
        raise SystemExit(2)
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except FileNotFoundError:
        print(f"artifact not found: {path}", file=sys.stderr)
        raise SystemExit(2) from None
    except PermissionError:
        print(f"artifact is not readable (check file permissions): {path}", file=sys.stderr)
        raise SystemExit(2) from None
    except IsADirectoryError:
        print(f"artifact path is a directory, not a file: {path}", file=sys.stderr)
        raise SystemExit(2) from None
    except OSError as exc:
        # Catch-all for the rest (a symlink loop's ELOOP, a device/IO error): still clean.
        print(f"cannot read artifact ({path}): {exc}", file=sys.stderr)
        raise SystemExit(2) from None
    except ValueError as exc:
        # json.load raises a plain ValueError (not JSONDecodeError) on an integer literal
        # beyond the int-string-conversion limit (py3.11+); JSONDecodeError subclasses it.
        print(f"artifact is not valid JSON ({path}): {exc}", file=sys.stderr)
        raise SystemExit(2) from None
    if not isinstance(data, dict):
        print(f"artifact must be a JSON object: {path}", file=sys.stderr)
        raise SystemExit(2)
    return data


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
