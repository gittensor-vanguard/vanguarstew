"""Verify a private Polaris benchmark-seal receipt against its exact report and plan values."""

from __future__ import annotations

import argparse
import json
import os
import stat
import sys

from benchmark.polaris_benchmark import PolarisBenchmarkSealPlan, verify_benchmark_seal
from scripts.plan_polaris_benchmark import load_private_report

_MAX_RECEIPT_BYTES = 4 * 1024 * 1024


def _load_private_receipt(path: str) -> dict:
    descriptor = None
    try:
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or not 0 < info.st_size <= _MAX_RECEIPT_BYTES:
            raise ValueError("receipt is not a bounded regular file")
        if os.name != "nt" and info.st_mode & 0o077:
            raise ValueError("receipt permissions are too broad")
        chunks = []
        remaining = info.st_size
        while remaining:
            chunk = os.read(descriptor, min(1024 * 1024, remaining))
            if not chunk:
                raise ValueError("receipt changed while reading")
            chunks.append(chunk)
            remaining -= len(chunk)
        if os.read(descriptor, 1):
            raise ValueError("receipt changed while reading")
        value = json.loads(b"".join(chunks).decode("utf-8"))
    finally:
        if descriptor is not None:
            os.close(descriptor)
    if not isinstance(value, dict):
        raise ValueError("receipt must be an object")
    return value


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--receipt", required=True, help="mode-0600 complete receipt")
    parser.add_argument("--report", required=True, help="mode-0600 combined benchmark report")
    parser.add_argument("--nonce", required=True)
    parser.add_argument("--e2e-pubkey", required=True)
    return parser


def run(argv=None) -> int:
    args = _parser().parse_args(argv)
    try:
        plan = PolarisBenchmarkSealPlan(
            report=load_private_report(args.report),
            nonce=args.nonce,
            e2e_pubkey_b64=args.e2e_pubkey,
        )
        verification = verify_benchmark_seal(
            _load_private_receipt(args.receipt),
            plan=plan,
        )
    except Exception:
        print("benchmark seal verification failed", file=sys.stderr)
        return 2
    print(
        json.dumps(
            {
                "ok": verification.get("ok") is True,
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
