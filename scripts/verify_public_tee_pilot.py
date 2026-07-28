"""Verify a saved public Polaris TEE pilot receipt against its fixed receipt contract."""

from __future__ import annotations

import argparse
import json
import sys

from benchmark.intel_dcap import DcapVerificationError, OfflineDcapQvlVerifier, TdxMeasurementPolicy
from benchmark.polaris import PublicTeePilotPlan, verify_public_tee_pilot


def _load(path: str):
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError) as exc:
        raise RuntimeError("cannot read verification input") from exc


def run(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--receipt", required=True, help="saved complete Polaris receipt JSON")
    parser.add_argument("--nonce", required=True, help="the plan's 64-hex freshness challenge")
    parser.add_argument("--e2e-pubkey", required=True, help="the plan's base64 requester key")
    parser.add_argument(
        "--dcap-policy",
        help="optional version-1 local TDX measurement policy for independent Intel verification",
    )
    parser.add_argument("--strict", action="store_true", help="exit 1 when verification fails")
    args = parser.parse_args(argv)

    try:
        receipt = _load(args.receipt)
        plan = PublicTeePilotPlan(nonce=args.nonce, e2e_pubkey_b64=args.e2e_pubkey)
        intel_verifier = None
        if args.dcap_policy:
            intel_verifier = OfflineDcapQvlVerifier(
                TdxMeasurementPolicy.from_dict(_load(args.dcap_policy))
            )
        report = verify_public_tee_pilot(
            receipt,
            plan=plan,
            intel_verifier=intel_verifier,
        )
    except (DcapVerificationError, RuntimeError, ValueError):
        print("public TEE pilot verification failed", file=sys.stderr)
        return 2

    print(json.dumps(report, indent=2, sort_keys=True))
    level = (report.get("outer") or {}).get("verification_level", "unverified")
    print(
        f"public TEE pilot: {'OK' if report.get('ok') else 'FAILED'} ({level})",
        file=sys.stderr,
    )
    if level == "polaris-verified":
        print(
            "  NOTE  receipt bindings passed; independent Intel verification was not requested",
            file=sys.stderr,
        )
    return 1 if args.strict and not report.get("ok") else 0


if __name__ == "__main__":
    raise SystemExit(run())
