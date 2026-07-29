"""Run one digest-approved public Polaris TEE pilot and save its complete receipt privately."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from benchmark.polaris import (
    POLARIS_ATTEST_BASE_URL,
    PolarisClient,
    PublicTeePilotPlan,
    verify_public_tee_pilot,
)


def _reserve_private_output(path: str) -> tuple[Path, int]:
    target = Path(path)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    flags |= getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(target, flags, 0o600)
    return target, descriptor


def _write_reserved_json(descriptor: int, value) -> None:
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        json.dump(value, handle, indent=2, sort_keys=True)
        handle.write("\n")


def _discard_reservation(target: Path, descriptor: int | None) -> None:
    if descriptor is None:
        return
    try:
        try:
            os.close(descriptor)
        except OSError:
            pass
    finally:
        try:
            target.unlink()
        except OSError:
            pass


def run(argv=None, *, client_factory=PolarisClient.from_env_file) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--env-file", required=True, help="mode-0600 dotenv containing the API key")
    parser.add_argument("--nonce", required=True, help="fresh 64-hex challenge from the plan")
    parser.add_argument("--e2e-pubkey", required=True, help="base64 requester key from the plan")
    parser.add_argument("--approved-request-sha256", required=True)
    parser.add_argument(
        "--receipt-output",
        required=True,
        help="new local file for the complete receipt; it is created mode 0600",
    )
    args = parser.parse_args(argv)

    target = Path(args.receipt_output)
    descriptor = None
    try:
        plan = PublicTeePilotPlan(nonce=args.nonce, e2e_pubkey_b64=args.e2e_pubkey)
        target, descriptor = _reserve_private_output(args.receipt_output)
        client = client_factory(args.env_file, base_url=POLARIS_ATTEST_BASE_URL)
        response = client.attest_public_pilot_approved(
            plan,
            approved_request_sha256=args.approved_request_sha256,
        )
        report = verify_public_tee_pilot(response, plan=plan)
        _write_reserved_json(descriptor, response)
        descriptor = None
    except Exception:
        _discard_reservation(target, descriptor)
        print("public TEE pilot failed", file=sys.stderr)
        return 2

    print(
        json.dumps(
            {
                "ok": report.get("ok") is True,
                "receipt_saved": True,
                "request_sha256": plan.request_sha256(),
                "verification_level": (report.get("outer") or {}).get(
                    "verification_level", "unverified"
                ),
            },
            sort_keys=True,
        )
    )
    return 0 if report.get("ok") is True else 1


if __name__ == "__main__":
    raise SystemExit(run())
