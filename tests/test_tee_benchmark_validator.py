"""Rejection-path contract for the in-enclave benchmark validator (#2279).

``benchmark/tee_benchmark_validator.py`` runs inside the Polaris one-shot TDX workload and
decides whether a sealed benchmark decision may be attested. It had no test file, and the
coverage it picked up from importers exercised the accepting path — so every branch that
*refuses* a bad bundle was unverified. A validator covered only on accept can fail in one
direction, and it is the direction that matters at an attestation boundary.

These tests pin each refusal by its own cause: bundle framing, contract version, artifact
set, recomputation of both targets and the combined decision, PR binding, and evidence
binding. The accepting path is covered by a round trip so the rejections are known to be
rejecting something that would otherwise pass.
"""

import gzip
import hashlib
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

os.environ["VANGUARSTEW_OFFLINE"] = "1"

import pytest  # noqa: E402

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

CHALLENGE = "a" * 64
BASE_SHA = "1" * 40
HEAD_SHA = "2" * 40


def _objective(module_recall: float) -> dict:
    return {
        "module_recall": module_recall,
        "weighted_module_recall": module_recall,
        "module_weights": {"core": 1},
        "weighted_matched_modules": {"core": 1} if module_recall else {},
        "actual_modules": ["core"],
        "matched_modules": ["core"] if module_recall else [],
        "kind_recall": 0.0,
        "actual_kinds": [],
        "matched_kinds": [],
        "backlog_recall": 0.0,
        "matched_issue_numbers": [],
        "addressed_issue_numbers": [],
        "addressed_backlog_diagnostics": [],
        "release_predicted": False,
        "release_signaled": False,
        "release_match": True,
        "bump_predicted": None,
        "bump_actual": None,
        "bump_match": True,
    }


def _artifact(module_recall: float, tasks: int = 3) -> dict:
    """A scored single-repo replay artifact that satisfies the live integrity gate.

    Shaped like ``benchmark/runner.py::run_replay`` output — rows, tally, weights and judge
    telemetry must all recompute against each other or ``check_live_artifacts`` rejects it,
    so the composite is derived here rather than asserted.
    """
    composite = round(0.6 * 1.0 + 0.4 * module_recall, 3)
    rows = [
        {
            "task": index,
            "freeze": f"{index:010x}",
            "winner": "challenger",
            "judge_order": "offline",
            "overlap": 0.0,
            "objective": _objective(module_recall),
            "composite": composite,
        }
        for index in range(tasks)
    ]
    return {
        "tasks": tasks,
        "baseline": "empty",
        "tally": {"challenger": tasks, "baseline": 0, "tie": 0},
        "decisive_margin": tasks,
        "composite_mean": composite,
        "composite_parts": {"judge_mean": 1.0, "objective_mean": module_recall},
        "weights": {"judge": 0.6, "objective": 0.4},
        "rows": rows,
        "judge_order_stats": {
            "agree": 0, "disagree": 0, "tie": 0, "single": 0,
            "offline": tasks, "dual_order_tasks": 0, "disagreement_rate": None,
        },
        "judge_report": {
            "wins": tasks, "losses": 0, "ties": 0, "dual_order_tasks": 0,
            "disagreements": 0, "disagreement_rate": None,
            "summary": f"judge W-L-T {tasks}-0-0; disagreement_rate=n/a (0/0 dual-order tasks)",
        },
    }


def _artifacts(candidate_recall: float = 0.5) -> dict:
    """Four raw artifacts: a flat baseline and a candidate that improves both targets."""
    return {
        "baseline_public": _artifact(0.0),
        "candidate_public": _artifact(candidate_recall),
        "baseline_private": _artifact(0.0),
        "candidate_private": _artifact(candidate_recall),
    }


def _report(artifacts: dict) -> dict:
    """A report whose targets and decision recompute from ``artifacts``, with bound evidence."""
    public = score_pr_delta(artifacts["baseline_public"], artifacts["candidate_public"])
    private = score_pr_delta(artifacts["baseline_private"], artifacts["candidate_private"])
    combined = combine_dual_target(public, private)
    report = {
        "pr_number": 42,
        "base_ref": "test",
        "base_sha": BASE_SHA,
        "head_sha": HEAD_SHA,
        "public": public,
        "private": private,
        **{key: combined[key] for key in ("band", "blocks_merge", "label", "multiplier", "reason")},
    }
    report["evidence"] = build_evidence(
        report,
        inputs={"agent_commit": HEAD_SHA, "transcript_digest": hashlib.sha256(b"t").hexdigest()},
    )
    return report


def _bundle(report=None, artifacts=None) -> bytes:
    artifacts = _artifacts() if artifacts is None else artifacts
    report = _report(artifacts) if report is None else report
    return build_input_bundle(report, artifacts)


# ── accepting path ────────────────────────────────────────────────────────────────────────


def test_valid_bundle_round_trips_and_emits_public_safe_stdout():
    stdout = validate_input_bundle(_bundle(), challenge=CHALLENGE)
    emitted = json.loads(stdout)
    assert emitted["contract"] == TEE_BENCHMARK_CONTRACT
    assert emitted["challenge"] == CHALLENGE
    assert emitted["pr_number"] == 42
    assert emitted["base_sha"] == BASE_SHA and emitted["head_sha"] == HEAD_SHA
    # The stdout is quote-bound public evidence: raw reports, per-target measurements and
    # model evidence must stay in the no-egress bundle.
    assert "public" not in emitted and "private" not in emitted
    assert "evidence" not in emitted and "artifacts" not in emitted


def test_stdout_is_canonical_json():
    stdout = validate_input_bundle(_bundle(), challenge=CHALLENGE)
    assert stdout == canonical_json(json.loads(stdout))


# ── challenge binding ─────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("challenge", [
    None, 42, "", "z" * 64, "A" * 64, "a" * 63, "a" * 65,
])
def test_challenge_must_be_64_lowercase_hex(challenge):
    with pytest.raises(TeeBenchmarkValidationError, match="challenge"):
        validate_input_bundle(_bundle(), challenge=challenge)


# ── bundle framing ────────────────────────────────────────────────────────────────────────


def test_non_gzip_payload_is_rejected_as_malformed():
    with pytest.raises(TeeBenchmarkValidationError, match="malformed"):
        validate_input_bundle(b"not gzip at all", challenge=CHALLENGE)


def test_bundle_expanding_past_the_size_limit_is_rejected():
    oversized = gzip.compress(b"x" * (MAX_UNCOMPRESSED_BUNDLE_BYTES + 1), mtime=0)
    with pytest.raises(TeeBenchmarkValidationError, match="size limit"):
        validate_input_bundle(oversized, challenge=CHALLENGE)


def test_wrong_bundle_contract_is_rejected():
    payload = {"contract": "some-other-contract-v1", "report": {}, "artifacts": {}}
    raw = canonical_json(payload).encode("utf-8")
    with pytest.raises(TeeBenchmarkValidationError, match="contract is unsupported"):
        validate_input_bundle(gzip.compress(raw, mtime=0), challenge=CHALLENGE)


def test_non_canonical_bundle_json_is_rejected():
    # Same content, non-canonical serialization: the validator re-serializes and compares
    # bytes, so a reordered/spaced payload must not pass even though it parses.
    artifacts = _artifacts()
    payload = {
        "contract": TEE_BENCHMARK_BUNDLE_CONTRACT,
        "report": _report(artifacts),
        "artifacts": artifacts,
    }
    raw = json.dumps(payload, indent=1).encode("utf-8")
    with pytest.raises(TeeBenchmarkValidationError, match="canonical"):
        validate_input_bundle(gzip.compress(raw, mtime=0), challenge=CHALLENGE)


def test_non_finite_json_constant_is_rejected():
    raw = b'{"contract":"' + TEE_BENCHMARK_BUNDLE_CONTRACT.encode() + b'","report":NaN}'
    with pytest.raises(TeeBenchmarkValidationError, match="malformed"):
        validate_input_bundle(gzip.compress(raw, mtime=0), challenge=CHALLENGE)


# ── artifact set ──────────────────────────────────────────────────────────────────────────


def test_report_must_be_an_object():
    artifacts = _artifacts()
    raw = canonical_json({
        "contract": TEE_BENCHMARK_BUNDLE_CONTRACT, "report": "not-an-object",
        "artifacts": artifacts,
    }).encode("utf-8")
    with pytest.raises(TeeBenchmarkValidationError, match="report must be an object"):
        validate_input_bundle(gzip.compress(raw, mtime=0), challenge=CHALLENGE)


@pytest.mark.parametrize("mutate", [
    lambda a: {k: v for k, v in a.items() if k != "candidate_private"},   # one missing
    lambda a: {**a, "extra_target": _artifact(0.5)},                       # one too many
])
def test_exactly_the_four_live_artifacts_are_required(mutate):
    artifacts = _artifacts()
    report = _report(artifacts)
    with pytest.raises(TeeBenchmarkValidationError, match="four raw artifacts"):
        validate_input_bundle(_bundle(report, mutate(artifacts)), challenge=CHALLENGE)


def test_live_artifact_keys_are_the_four_the_validator_expects():
    assert set(LIVE_ARTIFACT_KEYS) == {
        "baseline_public", "candidate_public", "baseline_private", "candidate_private",
    }


# ── recomputation of the targets and the combined decision ────────────────────────────────


@pytest.mark.parametrize("target", ["public", "private"])
def test_each_target_report_must_recompute_from_the_raw_artifacts(target):
    artifacts = _artifacts()
    report = _report(artifacts)
    # A band the scorer can never emit, so the mutation is a real difference regardless of
    # what the fixture's delta happens to band as.
    report[target] = {**report[target], "band": "not-a-band"}
    with pytest.raises(TeeBenchmarkValidationError, match=f"{target} target report"):
        validate_input_bundle(_bundle(report, artifacts), challenge=CHALLENGE)


@pytest.mark.parametrize("key,value", [
    ("band", "not-a-band"),
    ("blocks_merge", "not-a-bool"),
    ("label", "perf:not-a-band"),
    ("multiplier", -1.0),
    ("reason", "a reason the recomputation never produces"),
])
def test_every_decision_key_must_recompute(key, value):
    artifacts = _artifacts()
    report = _report(artifacts)
    assert report[key] != value, "the mutation must differ from the recomputed value"
    report[key] = value
    with pytest.raises(TeeBenchmarkValidationError, match="decision does not recompute"):
        validate_input_bundle(_bundle(report, artifacts), challenge=CHALLENGE)


# ── PR binding ────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("pr_number", [None, True, 0, -1, "42", 4.2])
def test_pr_number_binding_must_be_a_positive_int(pr_number):
    artifacts = _artifacts()
    report = _report(artifacts)
    report["pr_number"] = pr_number
    with pytest.raises(TeeBenchmarkValidationError, match="PR binding"):
        validate_input_bundle(_bundle(report, artifacts), challenge=CHALLENGE)


@pytest.mark.parametrize("base_ref", [None, 42, "", "-leading-dash", "has space", "x" * 129])
def test_base_ref_must_match_the_ref_shape(base_ref):
    artifacts = _artifacts()
    report = _report(artifacts)
    report["base_ref"] = base_ref
    with pytest.raises(TeeBenchmarkValidationError, match="base ref"):
        validate_input_bundle(_bundle(report, artifacts), challenge=CHALLENGE)


@pytest.mark.parametrize("name", ["base_sha", "head_sha"])
@pytest.mark.parametrize("sha", [None, 42, "", "abc", "A" * 40, "g" * 40, "1" * 39, "1" * 41])
def test_commit_shas_must_be_40_lowercase_hex(name, sha):
    artifacts = _artifacts()
    report = _report(artifacts)
    report[name] = sha
    # head_sha also binds the evidence, so rebuild it against the mutated report.
    report["evidence"] = build_evidence(
        {k: v for k, v in report.items() if k != "evidence"},
        inputs={"agent_commit": report["head_sha"],
                "transcript_digest": hashlib.sha256(b"t").hexdigest()},
    )
    with pytest.raises(TeeBenchmarkValidationError, match=name):
        validate_input_bundle(_bundle(report, artifacts), challenge=CHALLENGE)


# ── evidence binding ──────────────────────────────────────────────────────────────────────


def test_evidence_must_verify_against_the_report():
    artifacts = _artifacts()
    report = _report(artifacts)
    report["evidence"] = {**report["evidence"], "artifact_digest": "0" * 64}
    with pytest.raises(TeeBenchmarkValidationError, match="evidence does not verify"):
        validate_input_bundle(_bundle(report, artifacts), challenge=CHALLENGE)


def test_evidence_must_be_bound_to_the_pr_head():
    artifacts = _artifacts()
    report = _report(artifacts)
    report["evidence"] = build_evidence(
        {k: v for k, v in report.items() if k != "evidence"},
        inputs={"agent_commit": "3" * 40,  # a different commit than head_sha
                "transcript_digest": hashlib.sha256(b"t").hexdigest()},
    )
    with pytest.raises(TeeBenchmarkValidationError, match="not bound to the PR head"):
        validate_input_bundle(_bundle(report, artifacts), challenge=CHALLENGE)


@pytest.mark.parametrize("transcript", [None, 42, "", "not-a-digest", "a" * 63])
def test_evidence_requires_a_recorded_transcript_digest(transcript):
    artifacts = _artifacts()
    report = _report(artifacts)
    report["evidence"] = build_evidence(
        {k: v for k, v in report.items() if k != "evidence"},
        inputs={"agent_commit": HEAD_SHA, "transcript_digest": transcript},
    )
    with pytest.raises(TeeBenchmarkValidationError, match="recorded transcript"):
        validate_input_bundle(_bundle(report, artifacts), challenge=CHALLENGE)


# ── CLI ───────────────────────────────────────────────────────────────────────────────────


def test_main_writes_the_verdict_and_exits_zero_for_a_valid_bundle(tmp_path, capsys):
    part = tmp_path / "bundle.part00"
    part.write_bytes(_bundle())
    assert main(["--challenge", CHALLENGE, str(part)]) == 0
    assert json.loads(capsys.readouterr().out)["contract"] == TEE_BENCHMARK_CONTRACT


def test_main_joins_multiple_parts_in_order(tmp_path, capsys):
    blob = _bundle()
    half = len(blob) // 2
    (tmp_path / "p0").write_bytes(blob[:half])
    (tmp_path / "p1").write_bytes(blob[half:])
    assert main(["--challenge", CHALLENGE, str(tmp_path / "p0"), str(tmp_path / "p1")]) == 0
    assert json.loads(capsys.readouterr().out)["challenge"] == CHALLENGE


def test_main_exits_two_and_writes_nothing_when_validation_fails(tmp_path, capsys):
    part = tmp_path / "bundle.part00"
    part.write_bytes(b"not a bundle")
    assert main(["--challenge", CHALLENGE, str(part)]) == 2
    assert capsys.readouterr().out == ""


def test_main_exits_two_when_a_part_is_missing(tmp_path, capsys):
    assert main(["--challenge", CHALLENGE, str(tmp_path / "absent")]) == 2
    assert capsys.readouterr().out == ""
