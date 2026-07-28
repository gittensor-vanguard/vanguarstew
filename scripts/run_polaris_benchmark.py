"""Run one approved Polaris TDX benchmark seal and save its receipt privately."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from benchmark.polaris import POLARIS_ATTEST_BASE_URL
from benchmark.polaris_benchmark import (
    PolarisBenchmarkClient,
    PolarisBenchmarkSealPlan,
    verify_benchmark_seal,
)
from scripts.plan_polaris_benchmark import load_private_report


def _reserve_private_output(path: str) -> tuple[Path, int]:
    target = Path(path)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    return target, os.open(target, flags, 0o600)


def _discard(target: Path, descriptor: int | None) -> None:
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


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--env-file", required=True, help="mode-0600 dotenv with Polaris key")
    parser.add_argument("--report", required=True, help="mode-0600 combined benchmark report")
    parser.add_argument("--nonce", required=True)
    parser.add_argument("--e2e-pubkey", required=True)
    parser.add_argument("--approved-request-sha256", required=True)
    parser.add_argument("--receipt-output", required=True, help="new mode-0600 receipt file")
    return parser


def run(argv=None, *, client_factory=PolarisBenchmarkClient.from_env_file) -> int:
    args = _parser().parse_args(argv)
    target = Path(args.receipt_output)
    descriptor = None
    try:
        plan = PolarisBenchmarkSealPlan(
            report=load_private_report(args.report),
            nonce=args.nonce,
            e2e_pubkey_b64=args.e2e_pubkey,
        )
        target, descriptor = _reserve_private_output(args.receipt_output)
        client = client_factory(args.env_file, base_url=POLARIS_ATTEST_BASE_URL)
        response = client.attest_approved(
            plan,
            approved_request_sha256=args.approved_request_sha256,
        )
        verification = verify_benchmark_seal(response, plan=plan)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            descriptor = None
            json.dump(response, handle, indent=2, sort_keys=True)
            handle.write("\n")
    except Exception:
        _discard(target, descriptor)
        print("benchmark seal failed", file=sys.stderr)
        return 2

    print(
        json.dumps(
            {
                "ok": verification.get("ok") is True,
                "receipt_saved": True,
                "request_sha256": plan.request_sha256(),
                "verification_level": verification.get("verification_level", "unverified"),
            },
            sort_keys=True,
        )
    )
    return 0 if verification.get("ok") is True else 1


def main() -> None:
    raise SystemExit(run())


if __name__ == "__main__":
    main()
