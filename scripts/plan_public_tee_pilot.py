"""Render the exact network-free request for the public Polaris TEE pilot."""

from __future__ import annotations

import argparse
import json
import sys

from benchmark.polaris import PublicTeePilotPlan


def build_plan(argv=None) -> PublicTeePilotPlan:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--nonce", required=True, help="fresh 64-hex challenge")
    parser.add_argument(
        "--e2e-pubkey",
        required=True,
        help="fresh base64 requester public key, at most 128 characters",
    )
    args = parser.parse_args(argv)
    return PublicTeePilotPlan(nonce=args.nonce, e2e_pubkey_b64=args.e2e_pubkey)


def main(argv=None) -> int:
    try:
        plan = build_plan(argv)
    except Exception:
        print("public TEE pilot planning failed", file=sys.stderr)
        return 2
    print(json.dumps(plan.approval_summary(), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
