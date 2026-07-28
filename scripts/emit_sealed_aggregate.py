"""Read one evaluation artifact from stdin and emit only its sealed aggregate envelope."""

from __future__ import annotations

import argparse
import json
import sys

from benchmark.sealed_aggregate import build_sealed_aggregate

_MAX_INPUT_BYTES = 16 * 1024 * 1024


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--challenge", required=True, help="fresh expected 32-byte lowercase hex")
    return parser


def main(argv=None) -> int:
    args = _parser().parse_args(argv)
    try:
        raw = sys.stdin.buffer.read(_MAX_INPUT_BYTES + 1)
        if len(raw) > _MAX_INPUT_BYTES:
            raise ValueError("input is too large")
        artifact = json.loads(raw.decode("utf-8"))
        envelope = build_sealed_aggregate(artifact, challenge=args.challenge)
    except Exception:
        print("sealed aggregate generation failed", file=sys.stderr)
        return 1
    sys.stdout.write(envelope)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
