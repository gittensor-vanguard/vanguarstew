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
from benchmark.tee_benchmark_validator import MAX_UNCOMPRESSED_BUNDLE_BYTES


def load_private_json(path: str, *, max_bytes: int, label: str) -> dict:
    descriptor = None
    try:
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or not 0 < info.st_size <= max_bytes:
            raise ValueError(f"{label} is not a bounded regular file")
        if os.name != "nt" and info.st_mode & 0o077:
            raise ValueError(f"{label} permissions are too broad")
        chunks = []
        remaining = info.st_size
        while remaining:
            chunk = os.read(descriptor, min(1024 * 1024, remaining))
            if not chunk:
                raise ValueError(f"{label} changed while reading")
            chunks.append(chunk)
            remaining -= len(chunk)
        if os.read(descriptor, 1):
            raise ValueError(f"{label} changed while reading")
        raw = b"".join(chunks)
        value = json.loads(raw.decode("utf-8"))
    finally:
        if descriptor is not None:
            os.close(descriptor)
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    return value


def load_private_report(path: str) -> dict:
    return load_private_json(
        path, max_bytes=POLARIS_BENCHMARK_MAX_REPORT_BYTES, label="report"
    )


def load_private_artifacts(args) -> dict:
    return {
        "baseline_public": load_private_json(
            args.baseline_public, max_bytes=MAX_UNCOMPRESSED_BUNDLE_BYTES, label="artifact"
        ),
        "candidate_public": load_private_json(
            args.candidate_public, max_bytes=MAX_UNCOMPRESSED_BUNDLE_BYTES, label="artifact"
        ),
        "baseline_private": load_private_json(
            args.baseline_private, max_bytes=MAX_UNCOMPRESSED_BUNDLE_BYTES, label="artifact"
        ),
        "candidate_private": load_private_json(
            args.candidate_private, max_bytes=MAX_UNCOMPRESSED_BUNDLE_BYTES, label="artifact"
        ),
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--report", required=True, help="mode-0600 combined benchmark report")
    parser.add_argument("--baseline-public", required=True, help="mode-0600 raw artifact")
    parser.add_argument("--candidate-public", required=True, help="mode-0600 raw artifact")
    parser.add_argument("--baseline-private", required=True, help="mode-0600 raw artifact")
    parser.add_argument("--candidate-private", required=True, help="mode-0600 raw artifact")
    parser.add_argument("--nonce", required=True, help="fresh 64-hex challenge")
    parser.add_argument("--e2e-pubkey", required=True, help="base64 requester public binding")
    return parser


def main(argv=None) -> int:
    args = _parser().parse_args(argv)
    try:
        plan = PolarisBenchmarkSealPlan(
            report=load_private_report(args.report),
            artifacts=load_private_artifacts(args),
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
