"""Tests for the candidate-vs-baseline improvement (adoption) gate (deterministic, offline)."""

import copy
import os
import sys
from unittest.mock import patch

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from benchmark.improvement import (  # noqa: E402
    DEFAULT_MIN_GAIN,
    _check_rows_list,
    check_improvement,
    failed_checks,
    improvement_headline,
)
from scripts.improvement import load_artifact  # noqa: E402


def _run(composite):
    return {"composite_mean": composite, "rows": []}


def _gen(tuned):
    return {"tuned": {"composite_mean": tuned, "scored_repos": 3},
            "held_out": {"composite_mean": 0.5, "scored_repos": 2}, "generalization_gap": 0.1}


def _names(result):
    return [c["name"] for c in result["checks"]]


def test_a_clear_improvement_is_adopted():
    result = check_improvement(_run(0.66), _run(0.60), min_gain=0.02)
    assert result["passed"] is True
    assert _names(result) == ["both_scored", "improves_by_margin"]
    assert result["gain"] == 0.06


def test_a_marginal_gain_below_the_bar_holds():
    result = check_improvement(_run(0.605), _run(0.60), min_gain=0.02)   # gain 0.005
    assert result["passed"] is False
    assert failed_checks(result) == ["improves_by_margin"]


def test_matching_the_baseline_is_not_an_improvement():
    result = check_improvement(_run(0.60), _run(0.60), min_gain=0.02)
    assert result["passed"] is False
    assert result["gain"] == 0.0


def test_a_regression_is_not_an_improvement():
    result = check_improvement(_run(0.55), _run(0.60), min_gain=0.02)
    assert result["passed"] is False
    assert result["gain"] == -0.05


def test_gain_exactly_at_the_margin_is_adopted():
    # The bound is inclusive: a gain equal to min_gain adopts.
    assert check_improvement(_run(0.62), _run(0.60), min_gain=0.02)["passed"] is True
    assert check_improvement(_run(0.619), _run(0.60), min_gain=0.02)["passed"] is False


def test_min_gain_is_configurable():
    runs = (_run(0.63), _run(0.60))                          # gain 0.03
    assert check_improvement(*runs, min_gain=0.02)["passed"] is True
    assert check_improvement(*runs, min_gain=0.05)["passed"] is False


def test_improvement_compares_generalization_tuned_scores():
    result = check_improvement(_gen(0.66), _gen(0.60))
    assert result["baseline_composite"] == 0.60 and result["candidate_composite"] == 0.66
    assert result["passed"] is True


def test_missing_composite_fails_both_scored():
    result = check_improvement({"error": "no tasks"}, _run(0.6))
    assert result["passed"] is False
    assert "both_scored" in failed_checks(result)
    assert result["gain"] is None


def _partial_candidate():
    return {
        "composite_mean": 0.66,
        "scored_repos": 2,
        "per_repo": [
            {"repo": "good-a", "composite_mean": 0.70, "tasks": 4},
            {"repo": "good-b", "composite_mean": 0.62, "tasks": 3},
            {"repo": "bad-clone", "error": "failed to clone", "tasks": 0},
        ],
    }


def test_candidate_per_repo_error_fails_both_scored():
    result = check_improvement(_partial_candidate(), _run(0.60))
    assert result["passed"] is False
    assert failed_checks(result) == ["both_scored", "improves_by_margin"]
    assert result["gain"] is None
    detail = next(c["detail"] for c in result["checks"] if c["name"] == "both_scored")
    assert "candidate error" in detail


def test_baseline_per_repo_error_fails_both_scored():
    baseline = {
        "composite_mean": 0.60,
        "scored_repos": 2,
        "per_repo": [
            {"repo": "good", "tasks": 4},
            {"repo": "bad", "tasks": 0, "error": "freeze failed"},
        ],
    }
    result = check_improvement(_run(0.66), baseline)
    assert result["passed"] is False
    assert "both_scored" in failed_checks(result)
    detail = next(c["detail"] for c in result["checks"] if c["name"] == "both_scored")
    assert "baseline error" in detail


def test_tuned_per_repo_error_fails_both_scored():
    candidate = {
        "tuned": {
            "composite_mean": 0.66,
            "scored_repos": 2,
            "per_repo": [{"repo": "a", "tasks": 4}, {"repo": "b", "tasks": 0, "error": "clone failed"}],
        },
        "held_out": {"composite_mean": 0.55, "scored_repos": 2},
        "generalization_gap": 0.11,
    }
    result = check_improvement(candidate, _gen(0.60))
    assert result["passed"] is False
    assert "both_scored" in failed_checks(result)


def test_held_out_per_repo_error_is_ignored_when_tuned_is_clean():
    candidate = _gen(0.66)
    candidate["held_out"] = {
        "composite_mean": 0.55,
        "scored_repos": 1,
        "per_repo": [{"repo": "x", "tasks": 0, "error": "clone failed"}],
    }
    result = check_improvement(candidate, _gen(0.60))
    assert result["passed"] is True


def test_both_scored_tolerates_missing_per_repo_and_non_list_per_repo():
    clean = {"composite_mean": 0.66, "scored_repos": 2}
    assert check_improvement(clean, _run(0.60))["passed"] is True
    weird = {"composite_mean": 0.66, "scored_repos": 2, "per_repo": "oops"}
    assert check_improvement(weird, _run(0.60))["passed"] is True


def test_lone_tuned_without_held_out_is_not_treated_as_generalization():
    # Only tuned present alongside a top-level score — do not scan orphan tuned's per_repo.
    candidate = {
        "composite_mean": 0.66,
        "scored_repos": 2,
        "tuned": {"per_repo": [{"repo": "b", "tasks": 0, "error": "clone failed"}]},
    }
    result = check_improvement(candidate, _run(0.60))
    assert result["passed"] is True


def test_malformed_or_non_dict_artifacts_fail_gracefully():
    for bad in (None, "not a dict", 42, [1, 2]):
        result = check_improvement(bad, _run(0.6))
        assert result["passed"] is False
        assert result["checks"]
        assert result["candidate_composite"] is None


def test_headline_reports_adopt_and_hold_without_bare_none():
    assert "ADOPT" in improvement_headline(check_improvement(_run(0.66), _run(0.60)))
    hold = improvement_headline(check_improvement(_run(0.60), _run(0.60)))
    assert "HOLD" in hold
    # Even when a score is missing, the headline reads "n/a", never a bare "None".
    missing = improvement_headline(check_improvement({"error": "x"}, _run(0.6)))
    assert "None" not in missing
    assert improvement_headline({}) == "improvement: no checks evaluated"
    assert DEFAULT_MIN_GAIN == 0.02


def test_failed_checks_helper_is_robust():
    assert failed_checks({}) == []
    assert failed_checks("not a dict") == []
    assert failed_checks(check_improvement(_run(0.5), _run(0.6))) != []


# --- a non-list / malformed `checks` field must not crash the reporting helpers ----------------
# check_improvement always emits a list of well-formed rows, but a hand-built or deserialized
# result whose `checks` isn't a list used to crash failed_checks / the headline on `c["name"]`.

_MALFORMED_CHECKS = ["not a list", 42, 3.14, True, {"name": "both_scored"}, ("a", "b"), range(2)]


def test_check_rows_list_accepts_only_real_lists():
    rows = [{"name": "both_scored", "passed": True}]
    assert _check_rows_list(rows) == rows
    assert _check_rows_list(None) == []          # absent key -> silent empty
    assert _check_rows_list([]) == []
    for bad in _MALFORMED_CHECKS:
        assert _check_rows_list(bad) == [], bad


def test_check_rows_list_skips_unusable_rows():
    # Non-dict rows, rows missing name/passed, and rows with wrong-typed name/passed are skipped.
    checks = [
        {"name": "keep", "passed": False},
        "not a dict",
        {"passed": True},                       # missing name
        {"name": "no_passed"},                   # missing passed
        {"name": 42, "passed": True},            # non-str name
        {"name": "bad_passed", "passed": "yes"},  # non-bool passed
    ]
    assert _check_rows_list(checks) == [{"name": "keep", "passed": False}]


def test_check_rows_list_warns_when_every_row_is_unusable(caplog):
    import logging

    with caplog.at_level(logging.WARNING, logger="benchmark.improvement"):
        assert _check_rows_list([42, "bad", None]) == []
    assert any("no usable rows" in r.message for r in caplog.records)


def test_failed_checks_survives_a_non_list_checks_field():
    for bad in _MALFORMED_CHECKS:
        assert failed_checks({"checks": bad}) == [], bad


def test_headline_survives_a_non_list_checks_field():
    for bad in _MALFORMED_CHECKS:
        assert improvement_headline({"checks": bad}) == "improvement: no checks evaluated", bad


def test_helpers_log_a_warning_for_a_non_list_checks_field(caplog):
    import logging

    with caplog.at_level(logging.WARNING, logger="benchmark.improvement"):
        assert failed_checks({"checks": "garbage"}) == []
    assert any("checks is str" in r.message for r in caplog.records)


def test_none_checks_is_silent_but_a_non_list_is_warned(caplog):
    # None (a missing checks key) is legitimate -> silent empty, no warning. A non-list value is
    # malformed -> warned and treated as empty. The two are handled distinctly, not conflated.
    import logging

    with caplog.at_level(logging.WARNING, logger="benchmark.improvement"):
        assert _check_rows_list(None) == []
    assert not caplog.records                      # None is silent
    caplog.clear()
    with caplog.at_level(logging.WARNING, logger="benchmark.improvement"):
        assert _check_rows_list("garbage") == []
    assert any("checks is str" in r.message for r in caplog.records)   # non-list is warned


def test_zero_min_gain_adopts_any_strict_improvement():
    # With min_gain=0, any gain >= 0 adopts (including an exact tie, which is gain 0.0).
    assert check_improvement(_run(0.601), _run(0.600), min_gain=0.0)["passed"] is True
    assert check_improvement(_run(0.600), _run(0.600), min_gain=0.0)["passed"] is True
    assert check_improvement(_run(0.599), _run(0.600), min_gain=0.0)["passed"] is False


def test_a_new_king_scenario_end_to_end():
    # A candidate that clearly beats the reigning best is adopted, with the gain reported.
    reigning = _run(0.58)
    challenger = _run(0.67)
    result = check_improvement(challenger, reigning, min_gain=0.03)
    assert result["passed"] is True
    assert result["gain"] == 0.09
    assert "ADOPT" in improvement_headline(result)
    assert "0.580 -> 0.670" in improvement_headline(result)


def test_generalization_vs_single_repo_mixed_baseline_and_candidate():
    # A generalization candidate compared to a single-repo baseline still compares the tuned
    # composite against the top-level composite consistently.
    result = check_improvement(_gen(0.66), _run(0.60), min_gain=0.02)
    assert result["candidate_composite"] == 0.66 and result["baseline_composite"] == 0.60
    assert result["passed"] is True


def test_a_float_precision_gain_at_the_margin_is_not_tipped_over():
    # 0.62 - 0.60 rounds to exactly 0.02, not 0.020000000000000018, so the inclusive bound holds.
    assert check_improvement(_run(0.62), _run(0.60), min_gain=0.02)["gain"] == 0.02


def test_check_improvement_does_not_mutate_inputs():
    baseline, candidate = _run(0.6), _run(0.66)
    snap_b, snap_c = copy.deepcopy(baseline), copy.deepcopy(candidate)
    check_improvement(candidate, baseline)
    assert baseline == snap_b and candidate == snap_c


# --- CLI loader: directory/unreadable artifact paths exit 2 cleanly (not a raw traceback) -----
# The CLI (scripts/improvement.py) reads two artifacts via load_artifact; a directory path or an
# unreadable file must exit 2 with a clear message, mirroring generalization_gate #1446 /
# objective_integrity #1377. (improvement.main() reads sys.argv directly, so load_artifact — the
# function that changed — is exercised directly.)


def test_load_artifact_directory_path_exits_two(tmp_path, capsys):
    with pytest.raises(SystemExit) as exc:
        load_artifact(str(tmp_path))
    assert exc.value.code == 2
    assert "directory" in capsys.readouterr().err


def test_load_artifact_unreadable_file_exits_two(capsys):
    with patch("builtins.open", side_effect=PermissionError("denied")):
        with pytest.raises(SystemExit) as exc:
            load_artifact("locked.json")
    assert exc.value.code == 2
    assert "not readable" in capsys.readouterr().err


def test_load_artifact_generic_os_error_exits_two(capsys):
    with patch("builtins.open", side_effect=OSError("I/O error")):
        with pytest.raises(SystemExit) as exc:
            load_artifact("flaky.json")
    assert exc.value.code == 2
    err = capsys.readouterr().err
    assert "cannot read artifact" in err and "I/O error" in err
