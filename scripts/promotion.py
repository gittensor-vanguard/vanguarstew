"""CLI: gate whether a replay run is strong enough to promote the challenger.

  python -m scripts.promotion result.json                        # report PROMOTE / HOLD
  python -m scripts.promotion result.json --min-composite 0.6 --strict   # exit 1 on HOLD (CI gate)

``result.json`` is a ``run_eval --out`` artifact (single-repo or multi-repo). With --strict the
process exits non-zero when the promotion gate fails.
"""

from __future__ import annotations

import argparse
import json
import sys

from benchmark.promotion import (
    DEFAULT_MAX_DISAGREEMENT,
    DEFAULT_MIN_COMPOSITE,
    DEFAULT_MIN_DECISIVE_MARGIN,
    check_promotion,
    promotion_headline,
)


def load_artifact(path: str) -> dict:
    """Load a JSON-object artifact, exiting with a clear message on a bad path or bad JSON.

    Each failure mode gets its own actionable message instead of a raw errno string: the path is
    missing, unreadable, or a directory; the file is not valid JSON; or the root value is not an
    object. Every case exits 1 via ``SystemExit`` so the caller needs no error handling.
    """
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        print(f"artifact not found: {path}", file=sys.stderr)
        raise SystemExit(1) from None
    except PermissionError:
        print(f"artifact is not readable (check file permissions): {path}", file=sys.stderr)
        raise SystemExit(1) from None
    except IsADirectoryError:
        print(f"artifact path is a directory, not a file: {path}", file=sys.stderr)
        raise SystemExit(1) from None
    except OSError:
        print(f"cannot read artifact: {path}", file=sys.stderr)
        raise SystemExit(1) from None
    except ValueError as exc:
        # json.load raises JSONDecodeError (a ValueError) for malformed JSON, and a plain
        # ValueError for an integer literal beyond the int-string-conversion limit (py3.11+).
        print(f"artifact is not valid JSON ({path}): {exc}", file=sys.stderr)
        raise SystemExit(1) from None
    if not isinstance(data, dict):
        print(f"artifact must be a JSON object: {path}", file=sys.stderr)
        raise SystemExit(1)
    return data


def main() -> None:
    ap = argparse.ArgumentParser(description="Gate a replay run on the challenger-promotion criteria")
    ap.add_argument("artifact", help="path to a run_eval --out JSON artifact")
    ap.add_argument("--min-composite", type=float, default=DEFAULT_MIN_COMPOSITE,
                    help=f"minimum composite_mean (default {DEFAULT_MIN_COMPOSITE})")
    ap.add_argument("--min-decisive-margin", type=int, default=DEFAULT_MIN_DECISIVE_MARGIN,
                    help=f"minimum wins-minus-losses margin (default {DEFAULT_MIN_DECISIVE_MARGIN})")
    ap.add_argument("--max-disagreement", type=float, default=DEFAULT_MAX_DISAGREEMENT,
                    help=f"max judge order-disagreement rate (default {DEFAULT_MAX_DISAGREEMENT})")
    ap.add_argument("--strict", action="store_true",
                    help="exit 1 when the promotion gate fails (for CI gating)")
    args = ap.parse_args()

    artifact = load_artifact(args.artifact)

    result = check_promotion(artifact,
                             min_composite=args.min_composite,
                             min_decisive_margin=args.min_decisive_margin,
                             max_disagreement=args.max_disagreement)
    print(promotion_headline(result), file=sys.stderr)
    for check in result["checks"]:
        mark = "PASS" if check["passed"] else "FAIL"
        print(f"  [{mark}] {check['name']}: {check['detail']}", file=sys.stderr)

    print(json.dumps(result, indent=2))

    if args.strict and not result["passed"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
