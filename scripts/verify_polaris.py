"""Verify a saved Polaris TDX receipt and its vanguarstew benchmark evidence.

  python -m scripts.verify_polaris --receipt receipt.json --nonce <64hex> \
      --e2e-pubkey <base64> --image ghcr.io/org/eval@sha256:<64hex> [--strict]

  python -m scripts.verify_polaris ... --dcap-policy intel-dcap.json \
      --dcap-collateral intel-dcap.json --strict

The default requires a live (non-stub) receipt.  This CLI locally checks the quote layout,
nonce/requester-key binding, resolved image digest, stdout binding, and the inner benchmark
artifact/evidence chain.  It reports ``polaris-verified`` when the receipt carries Polaris's
server-side Intel verification result.  Pass ``--dcap-policy`` to require complete local collateral,
strict TCB status, and allowlisted TDX measurements through the optional ``dcap-qvl`` backend.  The
independent path is offline-only and never fetches collateral implicitly.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import replace

from benchmark.intel_dcap import (
    DcapVerificationError,
    OfflineDcapQvlVerifier,
    TdxMeasurementPolicy,
)
from benchmark.polaris import PolarisError, PolarisReceipt, verify_attested_envelope


def _load(path: str):
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError) as exc:
        print(f"verify_polaris: cannot read receipt ({path}): {exc}", file=sys.stderr)
        raise SystemExit(2) from exc


def run(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--receipt", required=True, help="saved Polaris response/receipt JSON")
    parser.add_argument("--nonce", required=True, help="the 64-hex challenge sent to Polaris")
    parser.add_argument(
        "--e2e-pubkey", required=True, help="the base64 requester public key sent to Polaris"
    )
    parser.add_argument(
        "--image", required=True, help="expected OCI image pinned as name@sha256:<64hex>"
    )
    parser.add_argument(
        "--allow-stub",
        action="store_true",
        help="verify stub bindings for development (never hardware attestation)",
    )
    parser.add_argument(
        "--dcap-policy",
        help=(
            "version-1 TDX measurement policy; enables offline independent verification and "
            "requires complete local DCAP collateral"
        ),
    )
    parser.add_argument(
        "--dcap-collateral",
        help=(
            "complete local QuoteCollateralV3 JSON, or a local verification bundle containing a "
            "top-level collateral object; never fetched implicitly"
        ),
    )
    parser.add_argument("--strict", action="store_true", help="exit 1 when any check fails")
    args = parser.parse_args(argv)

    loaded_receipt = _load(args.receipt)
    receipt_value = (
        loaded_receipt.get("receipt")
        if isinstance(loaded_receipt, dict) and isinstance(loaded_receipt.get("receipt"), dict)
        else loaded_receipt
    )
    try:
        parsed_receipt = PolarisReceipt.from_dict(receipt_value)
    except PolarisError as exc:
        print(f"verify_polaris: malformed receipt: {exc}", file=sys.stderr)
        return 2

    intel_verifier = None
    if args.dcap_policy:
        try:
            loaded_policy = _load(args.dcap_policy)
            policy_value = loaded_policy
            if (
                isinstance(loaded_policy, dict)
                and isinstance(loaded_policy.get("verification"), dict)
                and isinstance(loaded_policy["verification"].get("policy"), dict)
            ):
                policy_value = loaded_policy["verification"]["policy"]
            intel_verifier = OfflineDcapQvlVerifier(
                TdxMeasurementPolicy.from_dict(policy_value)
            )
        except DcapVerificationError as exc:
            print(f"verify_polaris: invalid DCAP policy: {exc}", file=sys.stderr)
            return 2
    if args.dcap_collateral:
        if intel_verifier is None:
            print("verify_polaris: --dcap-collateral requires --dcap-policy", file=sys.stderr)
            return 2
        loaded_collateral = _load(args.dcap_collateral)
        collateral = (
            loaded_collateral.get("collateral")
            if isinstance(loaded_collateral, dict)
            and isinstance(loaded_collateral.get("collateral"), dict)
            else loaded_collateral
        )
        parsed_receipt = replace(parsed_receipt, collateral=collateral)

    report = verify_attested_envelope(
        parsed_receipt,
        nonce=args.nonce,
        e2e_pubkey_b64=args.e2e_pubkey,
        expected_image=args.image,
        require_live=not args.allow_stub,
        intel_verifier=intel_verifier,
    )
    print(json.dumps(report, indent=2, sort_keys=True))
    level = (report.get("outer") or {}).get("verification_level", "unverified")
    print(f"verify_polaris: {'OK' if report.get('ok') else 'FAILED'} ({level})", file=sys.stderr)
    if level == "polaris-verified":
        print(
            "  NOTE  Intel verification is Polaris server-side, not independently re-run here",
            file=sys.stderr,
        )
    if args.dcap_policy and level != "independently-verified":
        print(
            "  NOTE  independent verification failed closed; no network collateral fetch was made",
            file=sys.stderr,
        )
    if level == "stub":
        print("  NOTE  stub binding only -- hardware attestation did NOT occur", file=sys.stderr)
    return 1 if args.strict and not report.get("ok") else 0


if __name__ == "__main__":
    raise SystemExit(run())
