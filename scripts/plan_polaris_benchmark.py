"""Render an exact network-free Polaris TDX benchmark-seal request."""

from __future__ import annotations

import argparse
import json
import os
import stat
import sys

from benchmark.polaris_benchmark import (
    POLARIS_BENCHMARK_MAX_REPORT_BYTES,
    PolarisBenchmarkSealPlan,
)


def load_private_report(path: str) -> dict:
    descriptor = None
    try:
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or not 0 < info.st_size <= POLARIS_BENCHMARK_MAX_REPORT_BYTES:
            raise ValueError("report is not a bounded regular file")
        if os.name != "nt" and info.st_mode & 0o077:
            raise ValueError("report permissions are too broad")
        chunks = []
        remaining = info.st_size
        while remaining:
            chunk = os.read(descriptor, min(1024 * 1024, remaining))
            if not chunk:
                raise ValueError("report changed while reading")
            chunks.append(chunk)
            remaining -= len(chunk)
        if os.read(descriptor, 1):
            raise ValueError("report changed while reading")
        raw = b"".join(chunks)
        value = json.loads(raw.decode("utf-8"))
    finally:
        if descriptor is not None:
            os.close(descriptor)
    if not isinstance(value, dict):
        raise ValueError("report must be an object")
    return value


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--report", required=True, help="mode-0600 combined benchmark report")
    parser.add_argument("--nonce", required=True, help="fresh 64-hex challenge")
    parser.add_argument("--e2e-pubkey", required=True, help="base64 requester public binding")
    return parser


def main(argv=None) -> int:
    args = _parser().parse_args(argv)
    try:
        plan = PolarisBenchmarkSealPlan(
            report=load_private_report(args.report),
            nonce=args.nonce,
            e2e_pubkey_b64=args.e2e_pubkey,
        )
    except Exception:
        print("benchmark seal planning failed", file=sys.stderr)
        return 2
    print(json.dumps(plan.approval_summary(), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
