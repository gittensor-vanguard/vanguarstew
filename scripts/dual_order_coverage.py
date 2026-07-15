"""CLI: print dual-order judging coverage from a replay artifact.

  python -m scripts.dual_order_coverage result.json

Exits 2 when the artifact path cannot be read (missing, permission, not a file), the JSON is
invalid, or the root value is not an object.
"""

from __future__ import annotations

import argparse
import json
import sys

from benchmark.dual_order_coverage import (
    dual_order_coverage_headline,
    summarize_dual_order_coverage,
)


def load_artifact(path: str) -> dict:
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except OSError as exc:
        # Covers missing file, permission denied, and "is a directory".
        print(f"cannot read artifact ({path}): {exc}", file=sys.stderr)
        raise SystemExit(2) from None
    except ValueError as exc:
        # json.load raises a plain ValueError (not JSONDecodeError) on an integer literal beyond
        # the int-string-conversion limit (py3.11+); JSONDecodeError and the mid-read
        # UnicodeDecodeError of a non-UTF-8 file both subclass ValueError, so this one clause
        # covers all three (mirrors offline_share / the CLIs hardened in #1563).
        print(f"artifact is not valid JSON ({path}): {exc}", file=sys.stderr)
        raise SystemExit(2) from None
    if not isinstance(data, dict):
        print(f"artifact must be a JSON object: {path}", file=sys.stderr)
        raise SystemExit(2)
    return data


def run(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Report dual-order judging coverage")
    ap.add_argument("artifact", help="run_eval --out JSON artifact")
    args = ap.parse_args(argv)
    try:
        artifact = load_artifact(args.artifact)
    except SystemExit as exc:
        return int(exc.code)
    summary = summarize_dual_order_coverage(artifact)
    print(dual_order_coverage_headline(summary), file=sys.stderr)
    print(json.dumps(summary, indent=2))
    return 0


def main() -> None:
    raise SystemExit(run())


if __name__ == "__main__":
    main()
