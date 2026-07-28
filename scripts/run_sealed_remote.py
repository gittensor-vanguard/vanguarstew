"""Execute one approved sealed plan over pinned SSH and emit only its aggregate envelope."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from benchmark.sealed_remote import (
    SealedRemoteExecutionPlan,
    SealedRemoteExecutor,
    load_owner_detail,
    owner_target_binding,
)
from benchmark.sealed_ssh import SealedSSHConnection


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--owner-detail-file", required=True)
    parser.add_argument("--identity-file", required=True)
    parser.add_argument("--known-hosts-file", required=True)
    parser.add_argument("--runtime", required=True)
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
        detail = load_owner_detail(args.owner_detail_file)
        connection = SealedSSHConnection.from_owner_detail(
            detail,
            identity_file=Path(args.identity_file),
            known_hosts_file=Path(args.known_hosts_file),
        )
        plan = SealedRemoteExecutionPlan(
            runtime_path=Path(args.runtime),
            bundle_path=Path(args.bundle),
            challenge=args.challenge,
            target_binding_sha256=owner_target_binding(detail, args.known_hosts_file),
            timeout_seconds=args.timeout_seconds,
            max_output_bytes=args.max_output_bytes,
            max_memory_bytes=args.max_memory_bytes,
        )
        envelope = SealedRemoteExecutor().execute_approved(
            connection,
            plan,
            owner_detail=detail,
            approved_request_sha256=args.approved_request_sha256,
        )
    except Exception:
        print("sealed remote execution failed", file=sys.stderr)
        return 1
    sys.stdout.write(envelope)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
