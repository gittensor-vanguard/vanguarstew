"""CLI: diff two saved replay result artifacts.

  python -m scripts.compare_eval baseline.json candidate.json

Loads JSON written by ``scripts.run_eval --out`` and prints a structured diff on stdout
plus a short headline on stderr.
"""

from __future__ import annotations

import argparse
import json
import sys

from benchmark.compare import compare_headline, compare_results, load_result


def main() -> None:
    ap = argparse.ArgumentParser(description="compare two vanguarstew replay result artifacts")
    ap.add_argument("baseline", help="earlier or reference result JSON (--out artifact)")
    ap.add_argument("candidate", help="newer or challenger result JSON (--out artifact)")
    args = ap.parse_args()

    baseline = load_result(args.baseline)
    candidate = load_result(args.candidate)
    diff = compare_results(baseline, candidate)
    print(compare_headline(diff), file=sys.stderr)
    print(json.dumps(diff, indent=2))


if __name__ == "__main__":
    main()
