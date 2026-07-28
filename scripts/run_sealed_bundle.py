"""Execute one approved sealed bundle and emit only its canonical aggregate envelope."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from benchmark.sealed_execution import SealedExecutionPlan, SealedExecutor


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--bundle", required=True)
    parser.add_argument("--challenge", required=True)
    parser.add_argument("--timeout-seconds", type=int, default=900)
    parser.add_argument("--max-output-bytes", type=int, default=8 * 1024 * 1024)
    parser.add_argument("--max-memory-bytes", type=int, default=1024 * 1024 * 1024)
    parser.add_argument("--approved-request-sha256", required=True)
    return parser


def main(argv=None) -> int:
    args = _parser().parse_args(argv)
    try:
        plan = SealedExecutionPlan(
            bundle_path=Path(args.bundle),
            challenge=args.challenge,
            timeout_seconds=args.timeout_seconds,
            max_output_bytes=args.max_output_bytes,
            max_memory_bytes=args.max_memory_bytes,
        )
        envelope = SealedExecutor().execute_approved(
            plan,
            approved_request_sha256=args.approved_request_sha256,
        )
    except Exception:
        print("sealed bundle execution failed", file=sys.stderr)
        return 1
    sys.stdout.write(envelope)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
