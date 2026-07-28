"""Bind a benchmark artifact to an attestation quote, and verify that binding.

A TEE quote on its own proves "some attested enclave ran the expected image." That is not the
claim anyone actually needs. The claim that matters is:

    this attested enclave, running this exact published image, produced THIS score

which only holds if the score is cryptographically bound into the quote. Every TEE quote format
carries a caller-supplied field for exactly this — ``report_data`` (64 bytes) on Intel TDX and
AMD SEV-SNP, a custom nonce claim on managed offerings like GCP Confidential Space. This module
computes what goes in that field, and checks it afterwards.

The binding covers inputs as well as the output, because a score is only meaningful relative to
what produced it: the same enclave running the same image against an easier repo set would produce
an unrelated, still-"attested" number. Binding ``(inputs, artifact)`` together makes the quote a
statement about a specific, fully-described run.

The model call is deliberately represented by the *transcript digest* rather than trusted directly:
a TEE cannot make a hosted model's answer trustworthy, but it can prove which answers the run was
given, and that the score follows deterministically from them (see :mod:`benchmark.transcript`).
"""

from __future__ import annotations

import logging

from benchmark.transcript import digest

logger = logging.getLogger(__name__)

EVIDENCE_VERSION = 1

# The run-identifying inputs bound alongside the artifact. Anything that changes which score is
# correct belongs here; anything cosmetic must not, or the binding breaks on irrelevant churn.
_INPUT_FIELDS = ("repo_set", "repo_set_partition", "seed", "rotation_seed", "model",
                 "agent_commit", "eval_image", "transcript_digest")


def build_evidence(artifact, inputs) -> dict:
    """The evidence bundle for one scored run, including the ``report_data`` to bind into a quote.

    ``artifact`` is a ``run_eval --out`` result; ``inputs`` describes the run (see
    :data:`_INPUT_FIELDS`). Unknown input keys are dropped rather than rejected, so a caller can
    pass a richer run-description dict without silently changing the binding.
    """
    if not isinstance(inputs, dict):
        logger.warning("attestation: inputs is %s, not a dict; treating as empty",
                       type(inputs).__name__)
        inputs = {}
    bound_inputs = {field: inputs.get(field) for field in _INPUT_FIELDS}
    artifact_digest = digest(artifact)
    return {
        "version": EVIDENCE_VERSION,
        "inputs": bound_inputs,
        "artifact_digest": artifact_digest,
        # What the enclave writes into the quote. Recomputable by anyone holding the published
        # artifact + inputs, which is the whole point.
        "report_data": digest({"inputs": bound_inputs, "artifact_digest": artifact_digest}),
    }


def verify_evidence(artifact, evidence, quote_report_data: str = None) -> dict:
    """Check that ``evidence`` really describes ``artifact`` — and, when supplied, that a quote's
    ``report_data`` matches.

    Returns a report rather than raising, because a verifier's job is to say precisely *which*
    link failed: a mismatched artifact digest (the published score was edited after the fact) is a
    very different finding from a mismatched ``report_data`` (the quote attests a different run).

    ``ok`` is true only when every check that could be run passed. Note the quote check is skipped —
    not failed — when ``quote_report_data`` is absent, so the caller can verify the binding chain
    offline and still see honestly that hardware attestation was not part of the result.
    """
    checks = {}
    if not isinstance(evidence, dict):
        return {"ok": False, "checks": {"evidence_shape": False},
                "detail": f"evidence is {type(evidence).__name__}, not a dict"}

    recomputed = build_evidence(artifact, evidence.get("inputs"))

    checks["artifact_digest"] = evidence.get("artifact_digest") == recomputed["artifact_digest"]
    checks["report_data"] = evidence.get("report_data") == recomputed["report_data"]
    if quote_report_data is not None:
        checks["quote_binding"] = quote_report_data == recomputed["report_data"]

    detail = "all checks passed" if all(checks.values()) else "; ".join(
        f"{name} FAILED" for name, passed in checks.items() if not passed)
    return {
        "ok": all(checks.values()),
        "checks": checks,
        "quote_checked": quote_report_data is not None,
        "expected_report_data": recomputed["report_data"],
        "detail": detail,
    }
