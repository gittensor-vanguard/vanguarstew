"""Render an exact network-free Polaris managed GPU sandbox plan."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from benchmark.polaris_gpu import ManagedGpuSandboxPlan


def build_plan(argv=None) -> ManagedGpuSandboxPlan:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--name", default="gpu-worker-1", help="neutral gpu-worker-N identifier")
    parser.add_argument("--ssh-public-key-file", required=True)
    parser.add_argument("--gpu-type", required=True, help="exact live Polaris catalog name")
    parser.add_argument("--max-gpu-hourly-usd", required=True, type=float)
    parser.add_argument("--max-pairing-premium-hourly-usd", required=True, type=float)
    parser.add_argument("--max-spend-usd", type=float, default=1.0)
    parser.add_argument("--max-runtime-minutes", type=int, default=30)
    args = parser.parse_args(argv)
    try:
        public_key = Path(args.ssh_public_key_file).read_text(encoding="utf-8")
    except OSError as exc:
        raise RuntimeError("cannot read SSH public key file") from exc
    return ManagedGpuSandboxPlan(
        name=args.name,
        ssh_public_key=public_key,
        gpu_type=args.gpu_type,
        max_gpu_hourly_usd=args.max_gpu_hourly_usd,
        max_pairing_premium_hourly_usd=args.max_pairing_premium_hourly_usd,
        max_spend_usd=args.max_spend_usd,
        max_runtime_minutes=args.max_runtime_minutes,
    )


def main(argv=None) -> int:
    try:
        plan = build_plan(argv)
    except Exception:
        print("managed GPU sandbox planning failed", file=sys.stderr)
        return 2
    print(json.dumps(plan.approval_summary(), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
