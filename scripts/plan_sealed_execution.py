"""Render a network-free approval plan for one sealed bundle execution."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from benchmark.sealed_execution import SealedExecutionPlan


def build_plan(argv=None) -> SealedExecutionPlan:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--bundle", required=True, help="validated mode-0600 sealed bundle")
    parser.add_argument("--challenge", required=True, help="fresh 32-byte lowercase-hex challenge")
    parser.add_argument("--timeout-seconds", type=int, default=900)
    parser.add_argument("--max-output-bytes", type=int, default=8 * 1024 * 1024)
    parser.add_argument("--max-memory-bytes", type=int, default=1024 * 1024 * 1024)
    args = parser.parse_args(argv)
    return SealedExecutionPlan(
        bundle_path=Path(args.bundle),
        challenge=args.challenge,
        timeout_seconds=args.timeout_seconds,
        max_output_bytes=args.max_output_bytes,
        max_memory_bytes=args.max_memory_bytes,
    )


def main(argv=None) -> int:
    try:
        plan = build_plan(argv)
    except Exception:
        print("sealed execution planning failed", file=sys.stderr)
        return 2
    print(json.dumps(plan.approval_summary(), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
