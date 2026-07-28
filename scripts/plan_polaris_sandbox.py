"""Render an exact network-free plan for a bare persistent Polaris TDX sandbox."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from benchmark.polaris_sandbox import PolarisSandboxPlan


def build_plan(argv=None) -> PolarisSandboxPlan:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--name", default="sealed-worker-1", help="neutral non-purpose identifier")
    parser.add_argument(
        "--ssh-public-key-file",
        required=True,
        help="local ssh-ed25519 public key; comments are removed from the request",
    )
    parser.add_argument("--max-spend-usd", type=float, default=1.0)
    parser.add_argument("--max-runtime-minutes", type=int, default=60)
    args = parser.parse_args(argv)
    try:
        public_key = Path(args.ssh_public_key_file).read_text(encoding="utf-8")
    except OSError as exc:
        raise RuntimeError("cannot read SSH public key file") from exc
    return PolarisSandboxPlan(
        name=args.name,
        ssh_public_key=public_key,
        max_spend_usd=args.max_spend_usd,
        max_runtime_minutes=args.max_runtime_minutes,
    )


def main(argv=None) -> int:
    try:
        plan = build_plan(argv)
    except Exception:
        print("Polaris sandbox planning failed", file=sys.stderr)
        return 2
    print(json.dumps(plan.approval_summary(), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
