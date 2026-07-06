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
    with open(path, "r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError(f"artifact must be a JSON object: {path}")
    return data


def main() -> None:
    ap = argparse.ArgumentParser(description="Gate a replay artifact on judge-report integrity")
    ap.add_argument("artifact", help="path to a run_eval --out JSON artifact")
    ap.add_argument("--strict", action="store_true",
                    help="exit 1 when the judge report integrity gate fails (for CI gating)")
    args = ap.parse_args()

    try:
        artifact = load_artifact(args.artifact)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)

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
