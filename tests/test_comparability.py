"""Tests for the cross-artifact comparability gate and its CLI (deterministic, offline)."""

import copy
import json
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from benchmark.comparability import (  # noqa: E402
    artifact_kind,
    check_comparability,
    comparability_headline,
    failed_checks,
)
from scripts import comparability as cli  # noqa: E402


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


def test_artifact_kind_classification():
    assert artifact_kind(_single()) == "single"
    assert artifact_kind(_multi("a", "b")) == "multi"
    assert artifact_kind(_gen(["a"], ["b"])) == "generalization"
    assert artifact_kind([]) == "invalid"
    assert artifact_kind("oops") == "invalid"


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


def test_matching_generalization_partitions_pass():
    a = _gen(["t1", "t2"], ["h1"])
    b = copy.deepcopy(a)
    result = check_comparability([a, b])
    assert result["passed"] is True
    assert result["artifact_kind"] == "generalization"
    assert set(result["repo_sets"]["tuned"]) == {"t1", "t2"}
    assert result["repo_sets"]["held_out"] == ["h1"]


def test_generalization_tuned_mismatch_fails():
    result = check_comparability([_gen(["a"], ["h"]), _gen(["b"], ["h"])])
    assert result["passed"] is False
    assert "tuned_same_repo_set" in failed_checks(result)


def test_generalization_held_out_mismatch_fails():
    result = check_comparability([_gen(["a"], ["h1"]), _gen(["a"], ["h2"])])
    assert result["passed"] is False
    assert "held_out_same_repo_set" in failed_checks(result)


def test_mixed_kinds_fail_same_artifact_kind():
    result = check_comparability([_single(), _multi("a")])
    assert result["passed"] is False
    assert "same_artifact_kind" in failed_checks(result)


def test_single_repo_artifacts_pass_without_repo_signature():
    result = check_comparability([_single(0.5), _single(0.7)])
    assert result["passed"] is True
    assert result["artifact_kind"] == "single"


def test_one_artifact_fails_enough_artifacts():
    result = check_comparability([_multi("a")])
    assert result["passed"] is False
    assert failed_checks(result) == ["enough_artifacts"]


def test_non_dict_artifact_fails_enough_artifacts():
    result = check_comparability([_multi("a"), "not-a-dict"])
    assert result["passed"] is False
    assert "enough_artifacts" in failed_checks(result)


def test_empty_per_repo_fails_same_repo_set():
    art = _multi("a")
    art["per_repo"] = []
    result = check_comparability([art, _multi("a")])
    assert result["passed"] is False
    assert "same_repo_set" in failed_checks(result)


def test_malformed_per_repo_container_fails_same_repo_set():
    art = _multi("a")
    art["per_repo"] = 42
    result = check_comparability([art, _multi("a")])
    assert result["passed"] is False
    assert "same_repo_set" in failed_checks(result)


def test_non_dict_per_repo_rows_are_skipped():
    art = {"per_repo": ["oops", _repo("a")], "composite_mean": 0.5}
    result = check_comparability([art, art])
    assert result["passed"] is True
    assert result["repo_sets"]["multi"] == ["a"]


def test_comparability_headline_pass_and_fail():
    ok = check_comparability([_multi("a"), _multi("a")])
    bad = check_comparability([_multi("a"), _multi("b")])
    assert "COMPARABLE" in comparability_headline(ok)
    assert "NOT COMPARABLE" in comparability_headline(bad)


def test_failed_checks_tolerates_malformed_result():
    assert failed_checks({}) == []
    assert failed_checks({"checks": "oops"}) == []


@pytest.fixture
def tmp_artifacts(tmp_path):
    def write(name, payload):
        path = tmp_path / name
        path.write_text(json.dumps(payload), encoding="utf-8")
        return str(path)

    return write


def test_cli_strict_exits_one_when_not_comparable(tmp_artifacts, capsys):
    a = tmp_artifacts("a.json", _multi("r1"))
    b = tmp_artifacts("b.json", _multi("r2"))
    assert cli.run([a, b, "--strict"]) == 1
    err = capsys.readouterr().err
    assert "NOT COMPARABLE" in err


def test_cli_without_strict_exits_zero_when_not_comparable(tmp_artifacts, capsys):
    a = tmp_artifacts("a.json", _multi("r1"))
    b = tmp_artifacts("b.json", _multi("r2"))
    assert cli.run([a, b]) == 0


def test_cli_strict_passes_for_comparable_artifacts(tmp_artifacts, capsys):
    a = tmp_artifacts("a.json", _multi("r1", "r2"))
    b = tmp_artifacts("b.json", _multi("r1", "r2"))
    assert cli.run([a, b, "--strict"]) == 0
    assert "COMPARABLE" in capsys.readouterr().err


def test_cli_missing_file_exits_two(tmp_artifacts, capsys):
    good = tmp_artifacts("good.json", _multi("a"))
    assert cli.run([good, "missing.json"]) == 2
    assert "not found" in capsys.readouterr().err


def test_cli_rejects_non_object_json(tmp_artifacts, capsys):
    bad = tmp_artifacts("bad.json", [1, 2, 3])
    good = tmp_artifacts("good.json", _multi("a"))
    assert cli.run([good, str(bad)]) == 2
    assert "JSON object" in capsys.readouterr().err
