"""Rejection-path coverage for the in-enclave TEE benchmark validator (#2279)."""

from __future__ import annotations

import gzip
import hashlib
import json
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from benchmark.attestation import build_evidence  # noqa: E402
from benchmark.live_gate import LIVE_ARTIFACT_KEYS  # noqa: E402
from benchmark.tee_benchmark_validator import (  # noqa: E402
    MAX_UNCOMPRESSED_BUNDLE_BYTES,
    TEE_BENCHMARK_BUNDLE_CONTRACT,
    TEE_BENCHMARK_CONTRACT,
    TeeBenchmarkValidationError,
    build_input_bundle,
    main,
    validate_input_bundle,
)
from benchmark.transcript import canonical_json  # noqa: E402
from scripts.score_pr_delta import combine_dual_target, score_pr_delta  # noqa: E402

CHALLENGE = "ab" * 32
BASE_SHA = "12" * 20
HEAD_SHA = "34" * 20
TRANSCRIPT = "56" * 32

_PUBLIC = {
    "band": "xs",
    "blocks_merge": False,
    "label": "perf:xs",
    "multiplier": 0.5,
    "reason": "public-ok",
}
_PRIVATE = {
    "band": "xs",
    "blocks_merge": False,
    "label": "perf:xs",
    "multiplier": 0.5,
    "reason": "private-ok",
}
_COMBINED = {
    "band": "xs",
    "blocks_merge": False,
    "label": "perf:xs",
    "multiplier": 0.5,
    "reason": "combined-ok",
    "public": _PUBLIC,
    "private": _PRIVATE,
}


def _artifacts():
    return {key: {"side": key} for key in LIVE_ARTIFACT_KEYS}


def _evidence_inputs(*, agent_commit=HEAD_SHA, transcript_digest=TRANSCRIPT):
    return {
        "repo_set": "public+second-target",
        "repo_set_partition": "tuned",
        "seed": 0,
        "rotation_seed": None,
        "model": "model-snapshot",
        "agent_commit": agent_commit,
        "eval_image": None,
        "transcript_digest": transcript_digest,
    }


def _report(*, evidence=None, **overrides):
    report = {
        **_COMBINED,
        "pr_number": 2042,
        "base_ref": "test",
        "base_sha": BASE_SHA,
        "head_sha": HEAD_SHA,
        "public": dict(_PUBLIC),
        "private": dict(_PRIVATE),
    }
    report.update(overrides)
    if evidence is None:
        report["evidence"] = build_evidence(report, _evidence_inputs())
    else:
        report["evidence"] = evidence
    return report


def _install_scoring(monkeypatch, *, public=None, private=None, combined=None, gate=None):
    public = _PUBLIC if public is None else public
    private = _PRIVATE if private is None else private
    combined = _COMBINED if combined is None else combined
    scores = iter((public, private))

    monkeypatch.setattr(
        "benchmark.tee_benchmark_validator.check_live_artifacts",
        lambda _artifacts: {"passed": True} if gate is None else gate,
    )
    monkeypatch.setattr(
        "benchmark.tee_benchmark_validator.score_pr_delta",
        lambda _baseline, _candidate: next(scores),
    )
    monkeypatch.setattr(
        "benchmark.tee_benchmark_validator.combine_dual_target",
        lambda _public, _private: dict(combined),
    )


def _gzip_payload(payload: dict) -> bytes:
    return gzip.compress(canonical_json(payload).encode("utf-8"), compresslevel=9, mtime=0)


def _gzip_raw(raw: bytes) -> bytes:
    return gzip.compress(raw, compresslevel=9, mtime=0)


def test_round_trip_build_and_validate_accepts_a_consistent_bundle(monkeypatch):
    _install_scoring(monkeypatch)
    artifacts = _artifacts()
    report = _report()
    compressed = build_input_bundle(report, artifacts)

    stdout = validate_input_bundle(compressed, challenge=CHALLENGE)
    parsed = json.loads(stdout)

    assert parsed["contract"] == TEE_BENCHMARK_CONTRACT
    assert parsed["challenge"] == CHALLENGE
    assert parsed["pr_number"] == 2042
    assert parsed["base_ref"] == "test"
    assert parsed["base_sha"] == BASE_SHA
    assert parsed["head_sha"] == HEAD_SHA
    assert parsed["band"] == "xs"
    assert parsed["blocks_merge"] is False
    assert parsed["public_band"] == "xs"
    assert parsed["public_blocks_merge"] is False
    assert parsed["artifacts_sha256"] == hashlib.sha256(compressed).hexdigest()
    assert parsed["evidence_report_data"] == report["evidence"]["report_data"]
    assert stdout == canonical_json(parsed)


def _score_artifact(composite_mean, judge_mean, objective_mean):
    """Minimal artifact shape accepted by score_pr_delta (see tests/test_score_pr_delta.py)."""
    return {
        "composite_mean": composite_mean,
        "composite_parts": {"judge_mean": judge_mean, "objective_mean": objective_mean},
    }


def test_round_trip_with_real_score_and_combine_helpers(monkeypatch):
    """Prefer a real dual-target decision when the fixture stays cheap."""
    artifacts = {
        "baseline_public": _score_artifact(0.60, 0.55, 0.65),
        "candidate_public": _score_artifact(0.80, 0.75, 0.85),
        "baseline_private": _score_artifact(0.60, 0.55, 0.65),
        "candidate_private": _score_artifact(0.615, 0.56, 0.67),
    }
    public = score_pr_delta(artifacts["baseline_public"], artifacts["candidate_public"])
    private = score_pr_delta(artifacts["baseline_private"], artifacts["candidate_private"])
    report = combine_dual_target(public, private)
    report.update(
        {
            "pr_number": 2042,
            "base_ref": "test",
            "base_sha": BASE_SHA,
            "head_sha": HEAD_SHA,
        }
    )
    report["evidence"] = build_evidence(report, _evidence_inputs())
    monkeypatch.setattr(
        "benchmark.tee_benchmark_validator.check_live_artifacts",
        lambda _artifacts: {"passed": True},
    )
    compressed = build_input_bundle(report, artifacts)
    stdout = validate_input_bundle(compressed, challenge=CHALLENGE)
    parsed = json.loads(stdout)
    assert parsed["band"] == report["band"]
    assert parsed["blocks_merge"] == report["blocks_merge"]
    assert parsed["public_band"] == public["band"]
    assert parsed["contract"] == TEE_BENCHMARK_CONTRACT


def test_build_input_bundle_rejects_oversize_uncompressed_payload(monkeypatch):
    monkeypatch.setattr(
        "benchmark.tee_benchmark_validator.MAX_UNCOMPRESSED_BUNDLE_BYTES",
        64,
    )
    with pytest.raises(TeeBenchmarkValidationError, match="exceeds the size limit"):
        build_input_bundle({"padding": "x" * 200}, _artifacts())


def test_validate_input_bundle_rejects_expansion_past_size_limit(monkeypatch):
    monkeypatch.setattr(
        "benchmark.tee_benchmark_validator.MAX_UNCOMPRESSED_BUNDLE_BYTES",
        32,
    )
    compressed = _gzip_raw(b"x" * 64)
    with pytest.raises(TeeBenchmarkValidationError, match="expands past the size limit"):
        validate_input_bundle(compressed, challenge=CHALLENGE)


def test_validate_input_bundle_rejects_unsupported_bundle_contract():
    compressed = _gzip_payload(
        {
            "contract": "not-the-bundle-contract",
            "report": {},
            "artifacts": _artifacts(),
        }
    )
    with pytest.raises(TeeBenchmarkValidationError, match="contract is unsupported"):
        validate_input_bundle(compressed, challenge=CHALLENGE)


def test_validate_input_bundle_rejects_malformed_and_noncanonical_bundles():
    with pytest.raises(TeeBenchmarkValidationError, match="malformed"):
        validate_input_bundle(b"not-gzip", challenge=CHALLENGE)

    with pytest.raises(TeeBenchmarkValidationError, match="malformed"):
        validate_input_bundle(_gzip_raw(b'{"contract": Infinity}'), challenge=CHALLENGE)

    raw = json.dumps(
        {
            "contract": TEE_BENCHMARK_BUNDLE_CONTRACT,
            "report": {"x": 1},
            "artifacts": _artifacts(),
        },
        indent=2,
    ).encode("utf-8")
    with pytest.raises(TeeBenchmarkValidationError, match="not canonical JSON"):
        validate_input_bundle(_gzip_raw(raw), challenge=CHALLENGE)


@pytest.mark.parametrize(
    "challenge",
    ["", "AB" * 32, "00" * 31, "not-hex", "gg" * 32, None],
)
def test_validate_input_bundle_rejects_malformed_challenge(challenge, monkeypatch):
    _install_scoring(monkeypatch)
    compressed = build_input_bundle(_report(), _artifacts())
    with pytest.raises(TeeBenchmarkValidationError, match="challenge must be 64 lowercase hex"):
        validate_input_bundle(compressed, challenge=challenge)


def test_validate_input_bundle_rejects_wrong_artifact_set(monkeypatch):
    _install_scoring(monkeypatch)
    report = _report()
    payload = {
        "contract": TEE_BENCHMARK_BUNDLE_CONTRACT,
        "report": report,
        "artifacts": {"baseline_public": {}, "candidate_public": {}},
    }
    with pytest.raises(TeeBenchmarkValidationError, match="exactly four raw artifacts"):
        validate_input_bundle(_gzip_payload(payload), challenge=CHALLENGE)


def test_validate_input_bundle_rejects_failed_integrity_gate(monkeypatch):
    _install_scoring(monkeypatch, gate={"passed": False, "failed_artifacts": ["baseline_public"]})
    compressed = build_input_bundle(_report(), _artifacts())
    with pytest.raises(TeeBenchmarkValidationError, match="integrity gate failed"):
        validate_input_bundle(compressed, challenge=CHALLENGE)


def test_validate_input_bundle_rejects_public_or_private_that_do_not_recompute(monkeypatch):
    _install_scoring(monkeypatch)
    report = _report()
    report["public"] = {**_PUBLIC, "band": "xl"}
    compressed = build_input_bundle(report, _artifacts())
    with pytest.raises(TeeBenchmarkValidationError, match="public target report does not recompute"):
        validate_input_bundle(compressed, challenge=CHALLENGE)

    _install_scoring(monkeypatch)
    report = _report()
    report["private"] = {**_PRIVATE, "band": "xl"}
    # evidence must match the mutated report body
    report["evidence"] = build_evidence(
        {k: v for k, v in report.items() if k != "evidence"},
        _evidence_inputs(),
    )
    compressed = build_input_bundle(report, _artifacts())
    with pytest.raises(TeeBenchmarkValidationError, match="private target report does not recompute"):
        validate_input_bundle(compressed, challenge=CHALLENGE)


def test_validate_input_bundle_rejects_decision_that_does_not_recompute(monkeypatch):
    _install_scoring(monkeypatch)
    report = _report(band="xl", label="perf:xl", multiplier=4.0)
    compressed = build_input_bundle(report, _artifacts())
    with pytest.raises(
        TeeBenchmarkValidationError,
        match="combined benchmark decision does not recompute",
    ):
        validate_input_bundle(compressed, challenge=CHALLENGE)


@pytest.mark.parametrize(
    ("overrides", "match"),
    [
        ({"pr_number": 0}, "PR binding is malformed"),
        ({"pr_number": True}, "PR binding is malformed"),
        ({"pr_number": "1"}, "PR binding is malformed"),
        ({"base_ref": ""}, "base ref is malformed"),
        ({"base_ref": "../escape"}, "base ref is malformed"),
        ({"base_sha": "deadbeef"}, "base_sha is malformed"),
        ({"head_sha": "GG" * 20}, "head_sha is malformed"),
    ],
)
def test_validate_input_bundle_rejects_malformed_report_context(monkeypatch, overrides, match):
    _install_scoring(monkeypatch)
    report = _report(**overrides)
    compressed = build_input_bundle(report, _artifacts())
    with pytest.raises(TeeBenchmarkValidationError, match=match):
        validate_input_bundle(compressed, challenge=CHALLENGE)


def test_validate_input_bundle_rejects_evidence_that_fails_verify(monkeypatch):
    _install_scoring(monkeypatch)
    report = _report()
    report["evidence"] = {
        **report["evidence"],
        "artifact_digest": "00" * 32,
        "report_data": "11" * 32,
    }
    compressed = build_input_bundle(report, _artifacts())
    with pytest.raises(TeeBenchmarkValidationError, match="evidence does not verify"):
        validate_input_bundle(compressed, challenge=CHALLENGE)


def test_validate_input_bundle_rejects_evidence_not_bound_to_head(monkeypatch):
    _install_scoring(monkeypatch)
    body = _report()
    body.pop("evidence")
    evidence = build_evidence(body, _evidence_inputs(agent_commit="aa" * 20))
    report = {**body, "evidence": evidence}
    compressed = build_input_bundle(report, _artifacts())
    with pytest.raises(TeeBenchmarkValidationError, match="not bound to the PR head"):
        validate_input_bundle(compressed, challenge=CHALLENGE)


@pytest.mark.parametrize(
    ("mutate", "match"),
    [
        (
            lambda evidence: {
                **evidence,
                "inputs": {**evidence["inputs"], "transcript_digest": "not-a-digest"},
                # keep digests consistent so verify_evidence still passes
            },
            "requires a recorded transcript",
        ),
        (
            lambda evidence: {
                **evidence,
                "report_data": "NOTHEX" + "0" * 58,
            },
            "evidence does not verify",
        ),
    ],
)
def test_validate_input_bundle_rejects_malformed_evidence_digests(monkeypatch, mutate, match):
    _install_scoring(monkeypatch)
    report = _report()
    report["evidence"] = mutate(report["evidence"])
    if match == "requires a recorded transcript":
        # Re-bind digests after transcript mutation so verify_evidence succeeds and
        # the transcript shape check is the failing branch.
        rebound = build_evidence(
            {k: v for k, v in report.items() if k != "evidence"},
            report["evidence"]["inputs"],
        )
        report["evidence"] = rebound
    compressed = build_input_bundle(report, _artifacts())
    with pytest.raises(TeeBenchmarkValidationError, match=match):
        validate_input_bundle(compressed, challenge=CHALLENGE)


def test_validate_input_bundle_rejects_malformed_report_data_digest(monkeypatch):
    """Force verify_evidence ok, then fail the report_data hex shape check."""
    _install_scoring(monkeypatch)
    monkeypatch.setattr(
        "benchmark.tee_benchmark_validator.verify_evidence",
        lambda _artifact, _evidence: {"ok": True},
    )
    report = _report()
    report["evidence"] = {
        **report["evidence"],
        "report_data": "zz" * 32,
    }
    compressed = build_input_bundle(report, _artifacts())
    with pytest.raises(
        TeeBenchmarkValidationError,
        match="report-data digest is malformed",
    ):
        validate_input_bundle(compressed, challenge=CHALLENGE)


def test_validate_input_bundle_rejects_non_object_report(monkeypatch):
    _install_scoring(monkeypatch)
    payload = {
        "contract": TEE_BENCHMARK_BUNDLE_CONTRACT,
        "report": ["not", "an", "object"],
        "artifacts": _artifacts(),
    }
    with pytest.raises(TeeBenchmarkValidationError, match="report must be an object"):
        validate_input_bundle(_gzip_payload(payload), challenge=CHALLENGE)


def test_main_exits_zero_and_writes_stdout(tmp_path, monkeypatch, capsys):
    _install_scoring(monkeypatch)
    compressed = build_input_bundle(_report(), _artifacts())
    part_a = tmp_path / "a.bin"
    part_b = tmp_path / "b.bin"
    part_a.write_bytes(compressed[:20])
    part_b.write_bytes(compressed[20:])

    assert main(["--challenge", CHALLENGE, str(part_a), str(part_b)]) == 0
    captured = capsys.readouterr()
    parsed = json.loads(captured.out)
    assert parsed["contract"] == TEE_BENCHMARK_CONTRACT
    assert parsed["challenge"] == CHALLENGE
    assert captured.err == ""


def test_main_exits_two_on_validation_failure(tmp_path, capsys):
    bad = tmp_path / "bad.bin"
    bad.write_bytes(b"not-a-bundle")
    assert main(["--challenge", CHALLENGE, str(bad)]) == 2
    captured = capsys.readouterr()
    assert captured.out == ""


def test_max_uncompressed_bundle_bytes_constant_is_sixteen_mib():
    assert MAX_UNCOMPRESSED_BUNDLE_BYTES == 16 * 1024 * 1024
