"""CLI: gate whether a replay artifact's judge summary matches its telemetry.

  python -m scripts.judge_report_integrity result.json
  python -m scripts.judge_report_integrity result.json --strict

With --strict the process exits non-zero when the judge summary is inconsistent.
"""

from __future__ import annotations

import argparse
import json
import sys

from benchmark.judge_report_integrity import check_judge_report_integrity, integrity_headline


def load_artifact(path: str) -> dict:
    """Load a JSON-object artifact, exiting with a clear message on a bad path or bad JSON.

    Each failure mode gets its own actionable message instead of a raw errno string: the path is
    missing, unreadable, or a directory; the file is not valid JSON; or the root value is not an
    object. Every case exits 1 via ``SystemExit`` so the caller needs no error handling.
    """
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
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
    ap = argparse.ArgumentParser(description="Gate a replay artifact on judge-report integrity")
    ap.add_argument("artifact", help="path to a run_eval --out JSON artifact")
    ap.add_argument("--strict", action="store_true",
                    help="exit 1 when the judge report integrity gate fails (for CI gating)")
    args = ap.parse_args()

    artifact = load_artifact(args.artifact)

    result = check_judge_report_integrity(artifact)
    print(integrity_headline(result), file=sys.stderr)
    for check in result["checks"]:
        mark = "PASS" if check["passed"] else "FAIL"
        print(f"  [{mark}] {check['name']}: {check['detail']}", file=sys.stderr)

    print(json.dumps(result, indent=2))

    if args.strict and not result["passed"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
