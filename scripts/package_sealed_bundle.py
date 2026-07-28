"""Build one deterministic mode-0600 sealed workload bundle."""

from __future__ import annotations

import argparse
import json
import sys

from benchmark.sealed_bundle import build_sealed_bundle


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--source", required=True, help="mode-0700 tree containing executable run")
    parser.add_argument(
        "--output", required=True, help="new output tar path in a mode-0700 directory"
    )
    return parser


def main(argv=None) -> int:
    args = _parser().parse_args(argv)
    try:
        result = build_sealed_bundle(args.source, args.output)
    except Exception:
        print("sealed bundle packaging failed", file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
