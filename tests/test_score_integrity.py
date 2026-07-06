"""Tests for the composite-score integrity gate (deterministic, offline)."""

import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from benchmark.score_integrity import (  # noqa: E402
    DEFAULT_W_JUDGE,
    DEFAULT_W_OBJECTIVE,
    _expected_composite,
    check_score_integrity,
    failed_checks,
    integrity_headline,
)


def _artifact(composite=0.62, judge=0.7, objective=0.5, w_judge=0.6, w_objective=0.4, scored_repos=1):
    return {
        "scored_repos": scored_repos,
        "composite_mean": composite,
        "composite_parts": {"judge_mean": judge, "objective_mean": objective},
        "weights": {"judge": w_judge, "objective": w_objective},
        "rows": [],
    }


def _names(result):
    return [c["name"] for c in result["checks"]]


def test_a_consistent_artifact_passes():
    art = _artifact()
    result = check_score_integrity(art)
    assert result["passed"] is True
    assert _names(result) == [
        "composite_numeric", "composite_in_range", "components_present",
        "components_in_range", "blend_consistent",
    ]


def test_blend_uses_custom_weights():
    art = _artifact(composite=0.5, judge=0.5, objective=0.5, w_judge=0.8, w_objective=0.2)
    assert check_score_integrity(art)["passed"] is True


def test_absent_weights_default_to_sixty_forty():
    art = _artifact()
    del art["weights"]
    expected = _expected_composite(0.7, 0.5, DEFAULT_W_JUDGE, DEFAULT_W_OBJECTIVE)
    art["composite_mean"] = expected
    assert check_score_integrity(art)["passed"] is True


def test_zero_weights_do_not_divide_by_zero():
    art = _artifact(composite=0.0, judge=0.5, objective=0.5, w_judge=0.0, w_objective=0.0)
    assert check_score_integrity(art)["passed"] is True


def test_mismatched_composite_fails_blend_consistent():
    art = _artifact(composite=0.99)
    result = check_score_integrity(art)
    assert result["passed"] is False
    assert failed_checks(result) == ["blend_consistent"]


def test_out_of_range_composite_fails():
    result = check_score_integrity(_artifact(composite=1.5))
    assert result["passed"] is False
    assert "composite_in_range" in failed_checks(result)


def test_out_of_range_component_fails():
    art = _artifact(objective=1.2, composite=0.7)
    result = check_score_integrity(art)
    assert result["passed"] is False
    assert "components_in_range" in failed_checks(result)


def test_missing_composite_parts_fails_components_present():
    art = _artifact()
    del art["composite_parts"]
    result = check_score_integrity(art)
    assert result["passed"] is False
    assert "components_present" in failed_checks(result)


def test_non_dict_composite_parts_fails_components_present():
    art = _artifact()
    art["composite_parts"] = "oops"
    result = check_score_integrity(art)
    assert result["passed"] is False
    assert "components_present" in failed_checks(result)


def test_non_numeric_composite_fails_gracefully():
    art = _artifact()
    art["composite_mean"] = "high"
    result = check_score_integrity(art)
    assert result["passed"] is False
    assert "composite_numeric" in failed_checks(result)


def test_non_dict_artifact_fails_gracefully():
    for bad in (None, "not a dict", 42, [1, 2]):
        result = check_score_integrity(bad)
        assert result["passed"] is False
        assert failed_checks(result) == ["artifact_shape"]


def test_empty_dict_fails_gracefully():
    result = check_score_integrity({})
    assert result["passed"] is False
    assert "composite_numeric" in failed_checks(result)


def test_tolerance_is_configurable():
    art = _artifact()
    art["composite_mean"] = art["composite_mean"] + 0.001
    assert check_score_integrity(art, tolerance=0.002)["passed"] is True
    assert check_score_integrity(art, tolerance=0.0005)["passed"] is False


def test_generalization_checks_each_scored_partition():
    report = {
        "generalization_gap": 0.05,
        "tuned": _artifact(composite=0.62, judge=0.7, objective=0.5),
        "held_out": _artifact(composite=0.56, judge=0.6, objective=0.5),
    }
    result = check_score_integrity(report)
    assert result["passed"] is True
    assert "tuned:blend_consistent" in _names(result)
    assert "held_out:blend_consistent" in _names(result)


def test_generalization_skips_unscored_partitions():
    report = {
        "generalization_gap": None,
        "tuned": {"scored_repos": 0, "composite_mean": 0.0},
        "held_out": {"scored_repos": 0, "composite_mean": 0.0},
    }
    result = check_score_integrity(report)
    assert result["passed"] is False
    assert failed_checks(result) == ["artifact_shape"]


def test_multi_repo_weights_from_per_repo():
    art = {
        "composite_mean": 0.62,
        "composite_parts": {"judge_mean": 0.7, "objective_mean": 0.5},
        "per_repo": [
            {"name": "a", "composite_mean": 0.62,
             "weights": {"judge": 0.6, "objective": 0.4},
             "composite_parts": {"judge_mean": 0.7, "objective_mean": 0.5}},
        ],
    }
    assert check_score_integrity(art)["passed"] is True


def test_integrity_headline_reports_consistent_and_inconsistent():
    assert "CONSISTENT" in integrity_headline(check_score_integrity(_artifact()))
    assert "INCONSISTENT" in integrity_headline(check_score_integrity(_artifact(composite=0.1)))


def test_check_score_integrity_does_not_mutate_the_artifact():
    art = _artifact()
    before = json.dumps(art, sort_keys=True)
    check_score_integrity(art)
    assert json.dumps(art, sort_keys=True) == before


def test_cli_strict_exits_nonzero_on_inconsistent(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps(_artifact(composite=0.1)), encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, "-m", "scripts.score_integrity", str(bad), "--strict"],
        cwd=ROOT, capture_output=True, text=True,
    )
    assert proc.returncode == 1
    assert "INCONSISTENT" in proc.stderr


def test_cli_passes_for_consistent_artifact(tmp_path):
    good = tmp_path / "good.json"
    good.write_text(json.dumps(_artifact()), encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, "-m", "scripts.score_integrity", str(good), "--strict"],
        cwd=ROOT, capture_output=True, text=True,
    )
    assert proc.returncode == 0
    assert "CONSISTENT" in proc.stderr
