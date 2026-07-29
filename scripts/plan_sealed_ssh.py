"""Render a network-free approval plan for staging one sealed SSH payload."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from benchmark.sealed_ssh import SealedSSHDeploymentPlan


def build_plan(argv=None) -> SealedSSHDeploymentPlan:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--bundle", required=True, help="mode-0600 payload archive")
    parser.add_argument(
        "--challenge",
        required=True,
        help="fresh 32-byte lowercase-hex result challenge",
    )
    args = parser.parse_args(argv)
    return SealedSSHDeploymentPlan(bundle_path=Path(args.bundle), challenge=args.challenge)


def main(argv=None) -> int:
    try:
        plan = build_plan(argv)
    except Exception:
        print("sealed SSH planning failed", file=sys.stderr)
        return 2
    print(json.dumps(plan.approval_summary(), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
