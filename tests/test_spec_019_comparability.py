"""Contract tests for specs/019-benchmark-comparability — assert comparability.py satisfies
the spec's EARS criteria: artifact kind classification, repo-set matching, gate aggregation,
and malformed-result robustness. Offline, deterministic.
"""

import copy
import logging
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from benchmark.comparability import (  # noqa: E402
    _check_rows_list,
    _repo_key,
    artifact_kind,
    check_comparability,
    comparability_headline,
    failed_checks,
)

_MALFORMED_CHECKS = [42, 3.14, True, {"name": "same_repo_set"}, "not a list"]


def _repo(name, tasks=5, score=0.6):
    return {"repo": name, "tasks": tasks, "composite_mean": score}


def _multi(*repos):
    return {
        "repos": len(repos),
        "scored_repos": len(repos),
        "composite_mean": 0.6,
        "per_repo": [_repo(r) for r in repos],
    }


def _gen(tuned_repos, held_repos):
    return {
        "tuned": _multi(*tuned_repos),
        "held_out": _multi(*held_repos),
        "generalization_gap": 0.05,
    }


def _single(score=0.6):
    return {"composite_mean": score, "tasks": 8}


# --- Artifact kind classification ---------------------------------------------------------


def test_artifact_kind_single_multi_generalization_invalid():
    assert artifact_kind(_single()) == "single"
    assert artifact_kind(_multi("a", "b")) == "multi"
    assert artifact_kind(_gen(["a"], ["b"])) == "generalization"
    assert artifact_kind([]) == "invalid"
    assert artifact_kind("oops") == "invalid"
    assert artifact_kind({}) == "invalid"


# --- Repo identity extraction -------------------------------------------------------------


def test_repo_key_prefers_repo_field():
    assert _repo_key({"repo": "myrepo", "name": "other"}) == "myrepo"


def test_repo_key_falls_back_to_freeze_commit_prefix():
    assert _repo_key({"freeze_commit": "deadbeef1234567890"}) == "deadbeef12"


def test_malformed_per_repo_container_yields_empty_repo_set():
    art = _multi("a")
    art["per_repo"] = 42
    other = _multi("a")
    result = check_comparability([art, other])
    assert result["passed"] is False
    assert "same_repo_set" in failed_checks(result)


def test_non_dict_per_repo_rows_are_skipped():
    art = {"per_repo": ["oops", _repo("a")], "composite_mean": 0.5}
    result = check_comparability([art, art])
    assert result["passed"] is True
    assert result["repo_sets"]["multi"] == ["a"]


# --- Comparability checks -----------------------------------------------------------------


def test_matching_multi_repo_artifacts_pass():
    result = check_comparability([_multi("r1", "r2"), _multi("r1", "r2")])
    assert result["passed"] is True
    assert result["artifact_kind"] == "multi"
    assert result["repo_sets"]["multi"] == ["r1", "r2"]
    assert failed_checks(result) == []


def test_different_multi_repo_sets_fail():
    result = check_comparability([_multi("r1", "r2"), _multi("r1", "r3")])
    assert result["passed"] is False
    assert failed_checks(result) == ["same_repo_set"]


def test_generalization_partition_mismatch_fails():
    result = check_comparability([_gen(["a"], ["h1"]), _gen(["b"], ["h1"])])
    assert result["passed"] is False
    assert "tuned_same_repo_set" in failed_checks(result)


def test_mixed_kinds_fail_same_artifact_kind():
    result = check_comparability([_single(), _multi("a")])
    assert result["passed"] is False
    assert "same_artifact_kind" in failed_checks(result)


def test_one_artifact_fails_enough_artifacts():
    result = check_comparability([_multi("a")])
    assert result["passed"] is False
    assert failed_checks(result) == ["enough_artifacts"]


def test_single_repo_artifacts_pass_without_repo_signature():
    result = check_comparability([_single(0.5), _single(0.7)])
    assert result["passed"] is True
    assert result["artifact_kind"] == "single"


def test_check_comparability_does_not_mutate_inputs():
    artifacts = [_multi("a", "b"), _multi("a", "b")]
    snapshot = copy.deepcopy(artifacts)
    check_comparability(artifacts)
    assert artifacts == snapshot


# --- Malformed gate-result robustness -----------------------------------------------------


@pytest.mark.parametrize("bad", _MALFORMED_CHECKS)
def test_check_rows_list_treats_non_list_as_empty(bad):
    assert _check_rows_list(bad) == []


def test_check_rows_list_logs_warning_for_non_list(caplog):
    with caplog.at_level(logging.WARNING, logger="benchmark.comparability"):
        assert _check_rows_list(42) == []
    assert any("checks is int" in r.message for r in caplog.records)


def test_check_rows_list_skips_rows_missing_required_keys():
    rows = [{"name": "same_repo_set"}, {"passed": True}]
    assert _check_rows_list(rows) == []


def test_check_rows_list_skips_non_bool_passed():
    rows = [{"name": "same_repo_set", "passed": 1}]
    assert _check_rows_list(rows) == []


def test_failed_checks_tolerates_malformed_result():
    assert failed_checks({}) == []
    assert failed_checks({"checks": "oops"}) == []


def test_failed_checks_skips_non_dict_and_malformed_rows():
    checks = [
        {"name": "same_repo_set", "passed": False},
        42,
        {"name": "enough_artifacts", "passed": True},
        {"name": "bad_row", "passed": 1},
    ]
    assert failed_checks({"checks": checks}) == ["same_repo_set"]


# --- Comparability headline ----------------------------------------------------------------


def test_comparability_headline_pass_and_fail():
    ok = check_comparability([_multi("a"), _multi("a")])
    bad = check_comparability([_multi("a"), _multi("b")])
    assert "COMPARABLE" in comparability_headline(ok)
    assert "NOT COMPARABLE" in comparability_headline(bad)


def test_comparability_headline_no_checks_when_malformed():
    assert comparability_headline({"checks": 42}) == "comparability: no checks evaluated"


def test_comparability_headline_survives_non_list_checks():
    assert comparability_headline({"checks": 42, "passed": False}) == (
        "comparability: no checks evaluated"
    )
