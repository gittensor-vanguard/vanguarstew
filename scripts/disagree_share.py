"""CLI: print the position-disagreement share from a replay artifact's judge order stats.

  python -m scripts.disagree_share result.json

Exits 2 when the artifact path cannot be read (missing, permission, not a file), the JSON is
invalid, a non-UTF-8 file, or the root value is not an object.
"""

from __future__ import annotations

import argparse
import json
import sys

from benchmark.disagree_share import disagree_share_headline, summarize_disagree_share


def load_artifact(path: str) -> dict:
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except OSError as exc:
        print(f"cannot read artifact ({path}): {exc}", file=sys.stderr)
        raise SystemExit(2) from None
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        # A non-UTF-8 file raises UnicodeDecodeError (a ValueError, not an OSError) mid-read.
        print(f"artifact is not valid UTF-8 JSON ({path}): {exc}", file=sys.stderr)
        raise SystemExit(2) from None
    if not isinstance(data, dict):
        print(f"artifact must be a JSON object: {path}", file=sys.stderr)
        raise SystemExit(2)
    return data


def run(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Report the position-disagreement share of a replay artifact")
    ap.add_argument("artifact", help="run_eval --out JSON artifact")
    args = ap.parse_args(argv)
    try:
        artifact = load_artifact(args.artifact)
    except SystemExit as exc:
        return int(exc.code)
    summary = summarize_disagree_share(artifact)
    print(disagree_share_headline(summary), file=sys.stderr)
    print(json.dumps(summary, indent=2))
    return 0


def main() -> None:
    raise SystemExit(run())


if __name__ == "__main__":
    main()
