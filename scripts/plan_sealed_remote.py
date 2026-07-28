"""Render a network-free plan for one target-bound sealed remote execution."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from benchmark.sealed_remote import (
    SealedRemoteExecutionPlan,
    load_owner_detail,
    owner_target_binding,
)


def build_plan(argv=None) -> SealedRemoteExecutionPlan:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--owner-detail-file", required=True)
    parser.add_argument("--known-hosts-file", required=True)
    parser.add_argument("--runtime", required=True)
    parser.add_argument("--bundle", required=True)
    parser.add_argument("--challenge", required=True)
    parser.add_argument("--timeout-seconds", type=int, default=900)
    parser.add_argument("--max-output-bytes", type=int, default=8 * 1024 * 1024)
    parser.add_argument("--max-memory-bytes", type=int, default=1024 * 1024 * 1024)
    args = parser.parse_args(argv)
    detail = load_owner_detail(args.owner_detail_file)
    return SealedRemoteExecutionPlan(
        runtime_path=Path(args.runtime),
        bundle_path=Path(args.bundle),
        challenge=args.challenge,
        target_binding_sha256=owner_target_binding(detail, args.known_hosts_file),
        timeout_seconds=args.timeout_seconds,
        max_output_bytes=args.max_output_bytes,
        max_memory_bytes=args.max_memory_bytes,
    )


def main(argv=None) -> int:
    try:
        plan = build_plan(argv)
    except Exception:
        print("sealed remote planning failed", file=sys.stderr)
        return 2
    print(json.dumps(plan.approval_summary(), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
