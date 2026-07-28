"""Deterministic validator executed by the Polaris one-shot TDX workload."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import json
import re
import sys

from benchmark.attestation import verify_evidence
from benchmark.live_gate import LIVE_ARTIFACT_KEYS, check_live_artifacts
from benchmark.transcript import canonical_json
from scripts.score_pr_delta import combine_dual_target, score_pr_delta

TEE_BENCHMARK_CONTRACT = "vanguarstew-benchmark-tee-v2"
TEE_BENCHMARK_BUNDLE_CONTRACT = "vanguarstew-benchmark-inputs-v1"
MAX_UNCOMPRESSED_BUNDLE_BYTES = 16 * 1024 * 1024

_SHA256_RE = re.compile(r"[0-9a-f]{64}")
_COMMIT_RE = re.compile(r"[0-9a-f]{40}")
_BASE_REF_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/-]{0,127}")
_DECISION_KEYS = ("band", "blocks_merge", "label", "multiplier", "reason")


class TeeBenchmarkValidationError(RuntimeError):
    """The mounted benchmark inputs cannot support a verified decision."""


def _reject_constant(value):
    raise ValueError(f"non-finite JSON constant: {value}")


def build_input_bundle(report: dict, artifacts: dict) -> bytes:
    payload = {
        "contract": TEE_BENCHMARK_BUNDLE_CONTRACT,
        "report": report,
        "artifacts": artifacts,
    }
    raw = canonical_json(payload).encode("utf-8")
    if not 0 < len(raw) <= MAX_UNCOMPRESSED_BUNDLE_BYTES:
        raise TeeBenchmarkValidationError("benchmark input bundle exceeds the size limit")
    return gzip.compress(raw, compresslevel=9, mtime=0)


def _load_input_bundle(compressed: bytes) -> dict:
    try:
        with gzip.GzipFile(fileobj=io.BytesIO(compressed), mode="rb") as handle:
            raw = handle.read(MAX_UNCOMPRESSED_BUNDLE_BYTES + 1)
        if len(raw) > MAX_UNCOMPRESSED_BUNDLE_BYTES:
            raise TeeBenchmarkValidationError("benchmark input bundle expands past the size limit")
        payload = json.loads(raw.decode("utf-8"), parse_constant=_reject_constant)
    except TeeBenchmarkValidationError:
        raise
    except (OSError, UnicodeError, ValueError, TypeError) as exc:
        raise TeeBenchmarkValidationError("benchmark input bundle is malformed") from exc
    if not isinstance(payload, dict) or payload.get("contract") != TEE_BENCHMARK_BUNDLE_CONTRACT:
        raise TeeBenchmarkValidationError("benchmark input bundle contract is unsupported")
    if canonical_json(payload).encode("utf-8") != raw:
        raise TeeBenchmarkValidationError("benchmark input bundle is not canonical JSON")
    return payload


def _validate_report_context(report: dict) -> None:
    if (
        isinstance(report.get("pr_number"), bool)
        or not isinstance(report.get("pr_number"), int)
        or report["pr_number"] <= 0
    ):
        raise TeeBenchmarkValidationError("benchmark report PR binding is malformed")
    if not isinstance(report.get("base_ref"), str) or not _BASE_REF_RE.fullmatch(report["base_ref"]):
        raise TeeBenchmarkValidationError("benchmark report base ref is malformed")
    for name in ("base_sha", "head_sha"):
        if not isinstance(report.get(name), str) or not _COMMIT_RE.fullmatch(report[name]):
            raise TeeBenchmarkValidationError(f"benchmark report {name} is malformed")


def _validate_report_evidence(report: dict) -> str:
    evidence = report.get("evidence")
    artifact = dict(report)
    artifact.pop("evidence", None)
    verification = verify_evidence(artifact, evidence)
    if verification.get("ok") is not True:
        raise TeeBenchmarkValidationError("benchmark report evidence does not verify")
    inputs = evidence.get("inputs") if isinstance(evidence, dict) else None
    if not isinstance(inputs, dict) or inputs.get("agent_commit") != report.get("head_sha"):
        raise TeeBenchmarkValidationError("benchmark evidence is not bound to the PR head")
    transcript = inputs.get("transcript_digest")
    report_data = evidence.get("report_data")
    if not isinstance(transcript, str) or not _SHA256_RE.fullmatch(transcript):
        raise TeeBenchmarkValidationError("benchmark evidence requires a recorded transcript")
    if not isinstance(report_data, str) or not _SHA256_RE.fullmatch(report_data):
        raise TeeBenchmarkValidationError("benchmark evidence report-data digest is malformed")
    return report_data


def validate_input_bundle(compressed: bytes, *, challenge: str) -> str:
    """Recompute the integrity gates and dual-target verdict; return canonical private stdout."""
    if not isinstance(challenge, str) or not _SHA256_RE.fullmatch(challenge):
        raise TeeBenchmarkValidationError("challenge must be 64 lowercase hex characters")
    payload = _load_input_bundle(compressed)
    report = payload.get("report")
    artifacts = payload.get("artifacts")
    if not isinstance(report, dict):
        raise TeeBenchmarkValidationError("benchmark report must be an object")
    if not isinstance(artifacts, dict) or set(artifacts) != set(LIVE_ARTIFACT_KEYS):
        raise TeeBenchmarkValidationError("benchmark requires exactly four raw artifacts")

    gate = check_live_artifacts(artifacts)
    if gate.get("passed") is not True:
        raise TeeBenchmarkValidationError("benchmark raw artifact integrity gate failed")

    public = score_pr_delta(artifacts["baseline_public"], artifacts["candidate_public"])
    private = score_pr_delta(artifacts["baseline_private"], artifacts["candidate_private"])
    if canonical_json(report.get("public")) != canonical_json(public):
        raise TeeBenchmarkValidationError("public target report does not recompute")
    if canonical_json(report.get("private")) != canonical_json(private):
        raise TeeBenchmarkValidationError("private target report does not recompute")
    combined = combine_dual_target(public, private)
    if any(report.get(key) != combined.get(key) for key in _DECISION_KEYS):
        raise TeeBenchmarkValidationError("combined benchmark decision does not recompute")

    _validate_report_context(report)
    report_data = _validate_report_evidence(report)
    gate_digest = hashlib.sha256(canonical_json(gate).encode("utf-8")).hexdigest()
    report_digest = hashlib.sha256(canonical_json(report).encode("utf-8")).hexdigest()
    return canonical_json(
        {
            "artifacts_sha256": hashlib.sha256(compressed).hexdigest(),
            "band": combined["band"],
            "blocks_merge": combined["blocks_merge"],
            "challenge": challenge,
            "contract": TEE_BENCHMARK_CONTRACT,
            "evidence_report_data": report_data,
            "integrity_gate_sha256": gate_digest,
            "report_sha256": report_digest,
        }
    )


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--challenge", required=True)
    parser.add_argument("parts", nargs="+")
    args = parser.parse_args(argv)
    try:
        compressed = b"".join(open(path, "rb").read() for path in args.parts)
        stdout = validate_input_bundle(compressed, challenge=args.challenge)
    except Exception:
        return 2
    sys.stdout.write(stdout)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
