"""CLI: print the skip share (fraction of repos that did not score) of a replay artifact.

  python -m scripts.skip_share result.json
"""

from __future__ import annotations

import argparse
import json
import sys

from benchmark.skip_share import skip_share_headline, summarize_skip_share


def load_artifact(path: str) -> dict:
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        print(f"artifact not found: {path}", file=sys.stderr)
        raise SystemExit(2) from None
    except json.JSONDecodeError as exc:
        print(f"artifact is not valid JSON ({path}): {exc}", file=sys.stderr)
        raise SystemExit(2) from None
    if not isinstance(data, dict):
        print(f"artifact must be a JSON object: {path}", file=sys.stderr)
        raise SystemExit(2)
    return data


def run(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Report the skip share of a replay artifact")
    ap.add_argument("artifact", help="run_eval --out JSON artifact")
    args = ap.parse_args(argv)
    try:
        artifact = load_artifact(args.artifact)
    except SystemExit as exc:
        return int(exc.code)
    summary = summarize_skip_share(artifact)
    print(skip_share_headline(summary), file=sys.stderr)
    print(json.dumps(summary, indent=2))
    return 0


def main() -> None:
    raise SystemExit(run())


if __name__ == "__main__":
    main()
