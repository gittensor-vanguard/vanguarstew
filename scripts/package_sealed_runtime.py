"""Build the deterministic public sealed-executor runtime zipapp."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from benchmark.sealed_runtime import build_sealed_runtime


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--output", required=True, help="new runtime path in a mode-0700 directory")
    return parser


def main(argv=None) -> int:
    args = _parser().parse_args(argv)
    try:
        result = build_sealed_runtime(Path(__file__).resolve().parents[1], args.output)
    except Exception:
        print("sealed runtime packaging failed", file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
