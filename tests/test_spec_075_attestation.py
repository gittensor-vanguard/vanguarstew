"""Spec 075 contract tests for benchmark/attestation.py (attestation evidence binding).

Exercises the binding through the REAL benchmark.transcript.digest (never mocked), so the
cryptographic binding, its determinism, and tamper-detection are genuinely tested. Digest equality
is stable across platforms because digest is deterministic. See specs/075-benchmark-attestation.
"""

import logging
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from benchmark.attestation import (  # noqa: E402
    _INPUT_FIELDS,
    EVIDENCE_VERSION,
    build_evidence,
    verify_evidence,
)
from benchmark.transcript import digest  # noqa: E402

_ARTIFACT = {"composite_mean": 0.6, "per_repo": [{"repo": "a", "tasks": 3}]}
_INPUTS = {"repo_set": "curated.json", "seed": 1, "model": "m-1", "eval_image": "img@sha",
           "transcript_digest": "abc"}


# --- Constants -----------------------------------------------------------------------------------

def test_constants_are_pinned():
    assert EVIDENCE_VERSION == 1
    assert _INPUT_FIELDS == ("repo_set", "repo_set_partition", "seed", "rotation_seed", "model",
                             "agent_commit", "eval_image", "transcript_digest")


# --- build_evidence ------------------------------------------------------------------------------

def test_evidence_shape_and_version():
    ev = build_evidence(_ARTIFACT, _INPUTS)
    assert set(ev) == {"version", "inputs", "artifact_digest", "report_data"}
    assert ev["version"] == EVIDENCE_VERSION


def test_inputs_restricted_to_known_fields():
    ev = build_evidence(_ARTIFACT, {**_INPUTS, "junk": "dropped", "another": 7})
    assert set(ev["inputs"]) == set(_INPUT_FIELDS)
    assert "junk" not in ev["inputs"] and "another" not in ev["inputs"]


def test_absent_input_field_is_none():
    ev = build_evidence(_ARTIFACT, {"seed": 1})
    assert ev["inputs"]["seed"] == 1
    assert ev["inputs"]["model"] is None            # absent field bound as None
    assert ev["inputs"]["agent_commit"] is None


def test_non_dict_inputs_warns_and_binds_empty(caplog):
    with caplog.at_level(logging.WARNING, logger="benchmark.attestation"):
        ev = build_evidence(_ARTIFACT, "not-a-dict")
    assert any(
        r.message == "attestation: inputs is str, not a dict; treating as empty"
        for r in caplog.records
    )
    assert all(ev["inputs"][f] is None for f in _INPUT_FIELDS)


def test_artifact_and_report_digests_match_primitive():
    ev = build_evidence(_ARTIFACT, _INPUTS)
    assert ev["artifact_digest"] == digest(_ARTIFACT)
    assert ev["report_data"] == digest(
        {"inputs": ev["inputs"], "artifact_digest": ev["artifact_digest"]})


def test_build_evidence_is_deterministic():
    assert build_evidence(_ARTIFACT, _INPUTS) == build_evidence(_ARTIFACT, dict(_INPUTS))


def test_report_data_changes_with_inputs_and_artifact():
    base = build_evidence(_ARTIFACT, _INPUTS)
    diff_input = build_evidence(_ARTIFACT, {**_INPUTS, "seed": 2})
    diff_artifact = build_evidence({**_ARTIFACT, "composite_mean": 0.7}, _INPUTS)
    assert diff_input["report_data"] != base["report_data"]
    assert diff_artifact["report_data"] != base["report_data"]


# --- verify_evidence -----------------------------------------------------------------------------

def test_non_dict_evidence_shape():
    result = verify_evidence(_ARTIFACT, "not-a-dict")
    assert result == {"ok": False, "checks": {"evidence_shape": False},
                      "detail": "evidence is str, not a dict"}
    assert "quote_checked" not in result and "expected_report_data" not in result


def test_roundtrip_ok():
    ev = build_evidence(_ARTIFACT, _INPUTS)
    result = verify_evidence(_ARTIFACT, ev)
    assert result["ok"] is True
    assert result["checks"] == {"artifact_digest": True, "report_data": True}
    assert result["quote_checked"] is False
    assert result["expected_report_data"] == ev["report_data"]
    assert result["detail"] == "all checks passed"


def test_quote_match_passes_binding():
    ev = build_evidence(_ARTIFACT, _INPUTS)
    result = verify_evidence(_ARTIFACT, ev, quote_report_data=ev["report_data"])
    assert result["ok"] is True
    assert result["checks"] == {"artifact_digest": True, "report_data": True, "quote_binding": True}
    assert result["quote_checked"] is True


def test_quote_absent_is_skipped_not_failed():
    ev = build_evidence(_ARTIFACT, _INPUTS)
    result = verify_evidence(_ARTIFACT, ev)                 # no quote_report_data
    assert "quote_binding" not in result["checks"]
    assert result["quote_checked"] is False


def test_detail_all_passed_and_failed():
    ev = build_evidence(_ARTIFACT, _INPUTS)
    assert verify_evidence(_ARTIFACT, ev)["detail"] == "all checks passed"
    tampered = {**ev, "report_data": "deadbeef"}
    assert verify_evidence(_ARTIFACT, tampered)["detail"] == "report_data FAILED"


# --- Failure localization ------------------------------------------------------------------------

def test_edited_artifact_fails_both_digests():
    ev = build_evidence(_ARTIFACT, _INPUTS)
    # verify the evidence for _ARTIFACT against a DIFFERENT artifact -> both digest chains break
    result = verify_evidence({**_ARTIFACT, "composite_mean": 0.99}, ev)
    assert result["ok"] is False
    assert result["checks"]["artifact_digest"] is False
    assert result["checks"]["report_data"] is False


def test_tampered_report_data_fails_only_report_data():
    ev = build_evidence(_ARTIFACT, _INPUTS)
    tampered = {**ev, "report_data": "0" * 64}
    result = verify_evidence(_ARTIFACT, tampered)
    assert result["ok"] is False
    assert result["checks"]["artifact_digest"] is True      # artifact unchanged
    assert result["checks"]["report_data"] is False


def test_quote_mismatch_fails_only_quote_binding():
    ev = build_evidence(_ARTIFACT, _INPUTS)
    result = verify_evidence(_ARTIFACT, ev, quote_report_data="not-the-right-report-data")
    assert result["ok"] is False
    assert result["checks"]["artifact_digest"] is True
    assert result["checks"]["report_data"] is True
    assert result["checks"]["quote_binding"] is False
    assert result["detail"] == "quote_binding FAILED"
