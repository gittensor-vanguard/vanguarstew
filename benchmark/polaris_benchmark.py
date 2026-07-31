"""Receipt-bound Polaris TDX validation for a completed dual-target benchmark report.

The live model calls happen before this boundary.  This module mounts the complete report and all
four raw benchmark artifacts into a no-egress one-shot TDX job.  A deterministic, receipt-bound
validator reruns the integrity gates and recomputes both target reports and the conservative final
decision before emitting aggregate-only stdout.

This is an integrity seal for the benchmark artifact, not proof that hosted model inference ran in
the TEE.  Complete reports and receipts can contain sensitive operational evidence and are never
made public by this module.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import re

from benchmark.attestation import verify_evidence
from benchmark.polaris import (
    POLARIS_ATTEST_BASE_URL,
    POLARIS_MAX_MOUNTED_FILE_BYTES,
    POLARIS_MAX_MOUNTED_FILES,
    PolarisClient,
    PolarisError,
    PolarisReceipt,
    expected_report_data,
    mounted_files_sha256,
    verify_receipt,
)
from benchmark.tee_benchmark_validator import (
    TEE_BENCHMARK_CONTRACT,
    build_input_bundle,
    validate_input_bundle,
)
from benchmark.tee_validator_archive import VALIDATOR_ARCHIVE_PATH, build_validator_archive
from benchmark.transcript import canonical_json
from scripts.score_pr_delta import combine_dual_target

POLARIS_BENCHMARK_SEAL_CONTRACT = TEE_BENCHMARK_CONTRACT
PUBLIC_BENCHMARK_EVIDENCE_SCHEMA = "vanguarstew-public-tee-evidence-v1"
POLARIS_BENCHMARK_REPORT_PREFIX = "/submission/inputs.part"
POLARIS_BENCHMARK_MAX_REPORT_BYTES = (
    POLARIS_MAX_MOUNTED_FILES * POLARIS_MAX_MOUNTED_FILE_BYTES
)

_BANDS = {"blocked", "none", "xs", "s", "m", "l", "xl"}
_COMMIT_RE = re.compile(r"[0-9a-f]{40}")
_NONCE_RE = re.compile(r"[0-9a-f]{64}")
_SHA256_RE = re.compile(r"[0-9a-f]{64}")
_BASE_REF_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/-]{0,127}")
_TEE_KIND_RE = re.compile(r"tdx-[0-9]+(?:\.[0-9]+)?")
_UTC_TIMESTAMP_RE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z")
_DECISION_KEYS = ("band", "blocks_merge", "label", "multiplier", "reason")


class PolarisBenchmarkError(RuntimeError):
    """A report, approval plan, live request, or receipt failed validation."""


def _validate_requester_binding(value: str) -> str:
    if not isinstance(value, str) or not value or len(value) > 128:
        raise PolarisBenchmarkError("requester public binding is malformed")
    try:
        decoded = base64.b64decode(value.encode("ascii"), validate=True)
    except (UnicodeEncodeError, ValueError, binascii.Error) as exc:
        raise PolarisBenchmarkError("requester public binding is malformed") from exc
    if not 16 <= len(decoded) <= 96:
        raise PolarisBenchmarkError("requester public binding is malformed")
    return value


def _canonical_report(report) -> bytes:
    if not isinstance(report, dict):
        raise PolarisBenchmarkError("benchmark report must be an object")
    try:
        encoded = canonical_json(report).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise PolarisBenchmarkError("benchmark report is not canonicalizable") from exc
    if not 0 < len(encoded) <= POLARIS_BENCHMARK_MAX_REPORT_BYTES:
        raise PolarisBenchmarkError("benchmark report exceeds the Polaris mounted-file budget")
    return encoded


def _validate_decision(report: dict) -> None:
    band = report.get("band")
    if band not in _BANDS:
        raise PolarisBenchmarkError("benchmark report band is unsupported")
    if report.get("blocks_merge") is not (band == "blocked"):
        raise PolarisBenchmarkError("benchmark report block decision is inconsistent")
    expected_label = None if band in {"blocked", "none"} else f"perf:{band}"
    if report.get("label") != expected_label:
        raise PolarisBenchmarkError("benchmark report decision label is inconsistent")
    public = report.get("public")
    private = report.get("private")
    if not isinstance(public, dict) or not isinstance(private, dict):
        raise PolarisBenchmarkError("benchmark report requires two target reports")
    try:
        recomputed = combine_dual_target(public, private)
    except (KeyError, TypeError, ValueError) as exc:
        raise PolarisBenchmarkError("benchmark report targets cannot be recombined") from exc
    for key in _DECISION_KEYS:
        if report.get(key) != recomputed.get(key):
            raise PolarisBenchmarkError("benchmark report decision does not recompute")


def _validate_context(report: dict) -> None:
    pr_number = report.get("pr_number")
    base_ref = report.get("base_ref")
    base_sha = report.get("base_sha")
    head_sha = report.get("head_sha")
    if isinstance(pr_number, bool) or not isinstance(pr_number, int) or pr_number <= 0:
        raise PolarisBenchmarkError("benchmark report PR binding is malformed")
    if not isinstance(base_ref, str) or not _BASE_REF_RE.fullmatch(base_ref):
        raise PolarisBenchmarkError("benchmark report base ref is malformed")
    if not isinstance(base_sha, str) or not _COMMIT_RE.fullmatch(base_sha):
        raise PolarisBenchmarkError("benchmark report base commit is malformed")
    if not isinstance(head_sha, str) or not _COMMIT_RE.fullmatch(head_sha):
        raise PolarisBenchmarkError("benchmark report head commit is malformed")


def _validate_evidence(report: dict) -> str:
    evidence = report.get("evidence")
    if not isinstance(evidence, dict):
        raise PolarisBenchmarkError("benchmark report evidence is missing")
    artifact = dict(report)
    artifact.pop("evidence", None)
    verification = verify_evidence(artifact, evidence)
    if verification.get("ok") is not True:
        raise PolarisBenchmarkError("benchmark report evidence does not verify")
    inputs = evidence.get("inputs")
    if not isinstance(inputs, dict):
        raise PolarisBenchmarkError("benchmark report evidence inputs are malformed")
    if inputs.get("agent_commit") != report.get("head_sha"):
        raise PolarisBenchmarkError("benchmark evidence is not bound to the PR head")
    transcript_digest = inputs.get("transcript_digest")
    if not isinstance(transcript_digest, str) or not _SHA256_RE.fullmatch(transcript_digest):
        raise PolarisBenchmarkError("benchmark evidence requires a recorded transcript")
    report_data = evidence.get("report_data")
    if not isinstance(report_data, str) or not _SHA256_RE.fullmatch(report_data):
        raise PolarisBenchmarkError("benchmark evidence report-data digest is malformed")
    return report_data


def validate_benchmark_report(report) -> dict:
    """Validate and return the fixed decision and context needed by a seal plan."""
    _canonical_report(report)
    _validate_decision(report)
    _validate_context(report)
    evidence_report_data = _validate_evidence(report)
    return {
        "band": report["band"],
        "blocks_merge": report["blocks_merge"],
        "pr_number": report["pr_number"],
        "base_ref": report["base_ref"],
        "base_sha": report["base_sha"],
        "head_sha": report["head_sha"],
        "public_band": report["public"]["band"],
        "public_blocks_merge": report["public"]["blocks_merge"],
        "evidence_report_data": evidence_report_data,
    }


class PolarisBenchmarkSealPlan:
    """Exact no-egress TDX request for one report and its four raw artifacts."""

    def __init__(self, *, report, artifacts, nonce: str, e2e_pubkey_b64: str,
                 validator_archive: bytes | None = None):
        if not isinstance(nonce, str) or not _NONCE_RE.fullmatch(nonce):
            raise PolarisBenchmarkError("nonce must be 32 random bytes encoded as lowercase hex")
        self.nonce = nonce
        self.e2e_pubkey_b64 = _validate_requester_binding(e2e_pubkey_b64)
        self._decision = validate_benchmark_report(report)
        self._report = _canonical_report(report)
        self.report_sha256 = hashlib.sha256(self._report).hexdigest()
        try:
            self._inputs = build_input_bundle(report, artifacts)
            self.stdout = validate_input_bundle(self._inputs, challenge=self.nonce)
            validator = validator_archive or build_validator_archive()
        except (OSError, TypeError, ValueError, RuntimeError) as exc:
            raise PolarisBenchmarkError("benchmark TEE inputs do not validate") from exc
        if not isinstance(validator, bytes) or not validator:
            raise PolarisBenchmarkError("benchmark validator archive is malformed")
        self.validator_sha256 = hashlib.sha256(validator).hexdigest()
        self.inputs_sha256 = hashlib.sha256(self._inputs).hexdigest()
        self.files = {VALIDATOR_ARCHIVE_PATH: validator}
        self.files.update(self._split_report(self._inputs))
        self.files_sha256 = mounted_files_sha256(self.files)
        self.workload = self._workload()
        try:
            expected_report_data(
                self.nonce,
                self.e2e_pubkey_b64,
                "sha256:" + hashlib.sha256(self.workload.encode("utf-8")).hexdigest(),
                self.stdout,
                files_sha256=self.files_sha256,
            )
        except PolarisError as exc:
            raise PolarisBenchmarkError("benchmark seal request is invalid") from exc

    def __repr__(self) -> str:
        return (
            f"{type(self).__name__}(report=<redacted>, artifacts=<redacted>, nonce=<redacted>, "
            "e2e_pubkey_b64=<redacted>)"
        )

    @staticmethod
    def _split_report(report: bytes) -> dict[str, bytes]:
        files = {}
        for index, offset in enumerate(
            range(0, len(report), POLARIS_MAX_MOUNTED_FILE_BYTES)
        ):
            files[f"{POLARIS_BENCHMARK_REPORT_PREFIX}{index:02d}"] = report[
                offset : offset + POLARIS_MAX_MOUNTED_FILE_BYTES
            ]
        if not 1 <= len(files) <= POLARIS_MAX_MOUNTED_FILES - 1:
            raise PolarisBenchmarkError("benchmark report part count is outside the limit")
        return files

    def _workload(self) -> str:
        paths = " ".join(
            path for path in sorted(self.files) if path != VALIDATOR_ARCHIVE_PATH
        )
        return (
            "set -eu\n"
            f"python3 {VALIDATOR_ARCHIVE_PATH} --challenge {self.nonce} {paths}\n"
        )

    def request_body(self) -> dict:
        return {
            "nonce": self.nonce,
            "e2e_pubkey_b64": self.e2e_pubkey_b64,
            "workload": self.workload,
            "egress": "none",
            "files": {
                target: base64.b64encode(content).decode("ascii")
                for target, content in sorted(self.files.items())
            },
        }

    def request_sha256(self) -> str:
        return hashlib.sha256(canonical_json(self.request_body()).encode("utf-8")).hexdigest()

    def approval_summary(self) -> dict:
        return {
            "network_request_made": False,
            "method": "POST",
            "endpoint": POLARIS_ATTEST_BASE_URL + "/v1/attest",
            "request_sha256": self.request_sha256(),
            "report": {
                "bytes": len(self._report),
                "input_bundle_bytes": len(self._inputs),
                "parts": len(self.files) - 1,
                "sha256": self.report_sha256,
                "inputs_sha256": self.inputs_sha256,
                "validator_sha256": self.validator_sha256,
                "files_sha256": self.files_sha256,
            },
            "result": json.loads(self.stdout),
            "policy": {
                "egress": "none",
                "retries": 0,
                "full_report_private": True,
                "full_receipt_private": True,
                "missing_or_invalid_receipt_fails_closed": True,
            },
            "claim_boundary": {
                "raw_artifact_integrity_recomputed_in_tee": True,
                "benchmark_decision_recomputed_in_tee": True,
                "hosted_model_inference_inside_tee": False,
                "workload_confidentiality": False,
            },
        }


class PolarisBenchmarkClient(PolarisClient):
    """Make exactly one approval-bound benchmark seal request."""

    def attest_approved(
        self,
        plan: PolarisBenchmarkSealPlan,
        *,
        approved_request_sha256: str,
    ) -> dict:
        if not isinstance(plan, PolarisBenchmarkSealPlan):
            raise PolarisBenchmarkError("an exact PolarisBenchmarkSealPlan is required")
        if self.base_url != POLARIS_ATTEST_BASE_URL:
            raise PolarisBenchmarkError("benchmark seal must use the documented attestation host")
        if not _SHA256_RE.fullmatch(approved_request_sha256 or "") or not hmac.compare_digest(
            plan.request_sha256(), approved_request_sha256
        ):
            raise PolarisBenchmarkError("approved request digest does not match the seal plan")
        payload = self._post_attest(plan.request_body())
        PolarisReceipt.from_response(payload)
        return payload


def verify_benchmark_seal(receipt, *, plan: PolarisBenchmarkSealPlan) -> dict:
    """Verify the complete Polaris binding and exact aggregate-only stdout."""
    if not isinstance(plan, PolarisBenchmarkSealPlan):
        return {"ok": False, "detail": "an exact benchmark seal plan is required"}
    outer = verify_receipt(
        receipt,
        nonce=plan.nonce,
        e2e_pubkey_b64=plan.e2e_pubkey_b64,
        expected_workload=plan.workload,
        expected_files_sha256=plan.files_sha256,
        expected_egress_log_sha256="",
    )
    try:
        parsed = receipt if isinstance(receipt, PolarisReceipt) else PolarisReceipt.from_response(receipt)
        stdout_exact = hmac.compare_digest(parsed.stdout, plan.stdout)
    except PolarisError:
        stdout_exact = False
    return {
        "ok": outer.get("ok") is True and stdout_exact,
        "verification_level": outer.get("verification_level", "unverified"),
        "outer": outer,
        "stdout_exact": stdout_exact,
        "detail": (
            "benchmark raw artifacts were validated and the decision recomputed by the receipt-bound workload"
            if outer.get("ok") is True and stdout_exact
            else "benchmark seal verification failed"
        ),
    }


def build_public_benchmark_evidence(receipt, *, plan: PolarisBenchmarkSealPlan) -> dict:
    """Return the bounded, public-safe proof summary for a verified benchmark seal.

    The complete response remains private because it carries the raw quote, collateral, caller
    freshness values, and commitments to undisclosed inputs.  This summary exposes only the
    GitHub-public PR binding, public-target band, conservative policy verdict, provider verification
    status, and deterministic code/result commitments.  It never copies a target identity, score,
    report, raw artifact, transcript, quote, collateral, request digest, or requester value.
    """
    verification = verify_benchmark_seal(receipt, plan=plan)
    if verification.get("ok") is not True or not isinstance(receipt, dict):
        raise PolarisBenchmarkError("verified benchmark receipt response is required")
    try:
        stdout = json.loads(receipt["stdout"])
        attestation = receipt["tee_attestation"]
        provider_verification = receipt["verification"]
        kind = attestation["kind"]
        started_at = receipt["started_at"]
    except (KeyError, TypeError, ValueError) as exc:
        raise PolarisBenchmarkError("benchmark receipt lacks public verification metadata") from exc
    if not isinstance(stdout, dict) or stdout.get("contract") != TEE_BENCHMARK_CONTRACT:
        raise PolarisBenchmarkError("benchmark receipt contract is not public-evidence capable")
    expected = {
        "band": plan._decision["band"],
        "blocks_merge": plan._decision["blocks_merge"],
        "pr_number": plan._decision["pr_number"],
        "base_ref": plan._decision["base_ref"],
        "base_sha": plan._decision["base_sha"],
        "head_sha": plan._decision["head_sha"],
        "public_band": plan._decision["public_band"],
        "public_blocks_merge": plan._decision["public_blocks_merge"],
    }
    if any(stdout.get(key) != value for key, value in expected.items()):
        raise PolarisBenchmarkError("benchmark receipt public binding is inconsistent")
    if (
        not isinstance(kind, str)
        or not _TEE_KIND_RE.fullmatch(kind)
        or not isinstance(started_at, str)
        or not _UTC_TIMESTAMP_RE.fullmatch(started_at)
        or provider_verification.get("intel_verified") is not True
        or provider_verification.get("report_data_match") is not True
    ):
        raise PolarisBenchmarkError("benchmark receipt public verification metadata is invalid")
    workload_sha256 = "sha256:" + hashlib.sha256(plan.workload.encode("utf-8")).hexdigest()
    result_sha256 = hashlib.sha256(plan.stdout.encode("utf-8")).hexdigest()
    return {
        "schema": PUBLIC_BENCHMARK_EVIDENCE_SCHEMA,
        "contract": TEE_BENCHMARK_CONTRACT,
        "pr": {
            "number": expected["pr_number"],
            "base_ref": expected["base_ref"],
            "base_sha": expected["base_sha"],
            "head_sha": expected["head_sha"],
        },
        "benchmark": {
            "band": expected["band"],
            "blocks_merge": expected["blocks_merge"],
            "public_band": expected["public_band"],
            "public_blocks_merge": expected["public_blocks_merge"],
        },
        "tee": {
            "provider": "Polaris",
            "kind": kind,
            "verification_level": verification.get("verification_level", "unverified"),
            "intel_verified": True,
            "report_data_match": True,
            "started_at": started_at,
            "validator_sha256": plan.validator_sha256,
            "workload_sha256": workload_sha256,
            "result_sha256": result_sha256,
        },
    }
