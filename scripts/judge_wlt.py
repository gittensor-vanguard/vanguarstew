"""CLI: print judge W-L-T counts from a replay artifact.

  python -m scripts.judge_wlt result.json

Exits 2 when the artifact path is missing, JSON is invalid, or the root value is not an object.
"""

from __future__ import annotations

import argparse
import json
import sys

from benchmark.judge_wlt import judge_wlt_headline, summarize_judge_wlt


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
    ap = argparse.ArgumentParser(description="Report judge W-L-T counts from judge_report")
    ap.add_argument("artifact", help="run_eval --out JSON artifact")
    args = ap.parse_args(argv)
    try:
        artifact = load_artifact(args.artifact)
    except SystemExit as exc:
        return int(exc.code)
    summary = summarize_judge_wlt(artifact)
    print(judge_wlt_headline(summary), file=sys.stderr)
    print(json.dumps(summary, indent=2))
    return 0


def main() -> None:
    raise SystemExit(run())


if __name__ == "__main__":
    main()
