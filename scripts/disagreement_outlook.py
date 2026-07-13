"""CLI: print judge disagreement outlook from a replay artifact.

  python -m scripts.disagreement_outlook result.json
  python -m scripts.disagreement_outlook result.json --stable-threshold 0.2

Exits 2 when the artifact path is missing, JSON is invalid, or the root value is not an object.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

from benchmark.disagreement_outlook import (
    DEFAULT_STABLE_THRESHOLD,
    disagreement_outlook_headline,
    summarize_disagreement_outlook,
)


def load_artifact(path: str) -> dict:
    """Load a JSON-object artifact, exiting with a clear message on a bad path or bad JSON.

    Path problems get a specific, actionable message instead of a raw traceback: a broken
    symlink (dangling target), ``FileNotFoundError`` (missing), ``PermissionError`` (unreadable),
    ``IsADirectoryError`` (a directory, not a file), and any other ``OSError``.
    """
    if os.path.islink(path) and not os.path.exists(path):
        print(f"artifact is a broken symlink (target does not exist): {path}", file=sys.stderr)
        raise SystemExit(2) from None
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
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
