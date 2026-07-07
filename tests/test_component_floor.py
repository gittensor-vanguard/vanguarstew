"""Tests for the per-component score-floor gate (deterministic, offline)."""

import copy
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from benchmark.component_floor import (  # noqa: E402
    DEFAULT_MIN_COMPOSITE,
    _check_rows_list,
    check_component_floors,
    component_floor_headline,
    failed_checks,
)


def _result(composite, judge, objective):
    return {"composite_mean": composite,
            "composite_parts": {"judge_mean": judge, "objective_mean": objective}}


def _names(result):
    return [c["name"] for c in result["checks"]]


def test_all_components_above_floors_passes():
    result = check_component_floors(_result(0.62, 0.7, 0.55))
    assert result["passed"] is True
    assert _names(result) == ["composite_floor", "judge_floor", "objective_floor"]
    assert result["composite_mean"] == 0.62 and result["judge_mean"] == 0.7


def test_a_weak_objective_anchor_is_caught_even_with_a_good_composite():
    # The differentiator: composite and judge clear their floors, but the objective anchor is
    # weak (fluff won the judge). --fail-under on the composite alone would miss this.
    result = check_component_floors(_result(0.55, 0.9, 0.2),
                                    min_composite=0.5, min_judge=0.4, min_objective=0.4)
    assert result["passed"] is False
    assert failed_checks(result) == ["objective_floor"]


def test_a_weak_judge_is_caught():
    result = check_component_floors(_result(0.55, 0.2, 0.9), min_judge=0.4)
    assert result["passed"] is False
    assert "judge_floor" in failed_checks(result)


def test_composite_below_floor_is_caught():
    result = check_component_floors(_result(0.30, 0.7, 0.6), min_composite=0.5)
    assert result["passed"] is False
    assert "composite_floor" in failed_checks(result)


def test_floors_are_inclusive():
    assert check_component_floors(_result(0.5, 0.4, 0.4),
                                  min_composite=0.5, min_judge=0.4, min_objective=0.4)["passed"] is True
    assert check_component_floors(_result(0.49, 0.4, 0.4), min_composite=0.5)["passed"] is False


def test_all_floors_are_configurable():
    run = _result(0.6, 0.5, 0.5)
    assert check_component_floors(run, min_composite=0.5, min_judge=0.4, min_objective=0.4)["passed"] is True
    assert check_component_floors(run, min_composite=0.7)["passed"] is False
    assert check_component_floors(run, min_judge=0.6)["passed"] is False
    assert check_component_floors(run, min_objective=0.6)["passed"] is False


def test_missing_components_fail_their_floors():
    result = check_component_floors({"composite_mean": 0.6, "composite_parts": {}})
    assert result["passed"] is False
    assert set(failed_checks(result)) == {"judge_floor", "objective_floor"}
    assert result["judge_mean"] is None and result["objective_mean"] is None


def test_malformed_or_non_dict_result_fails_gracefully():
    for bad in (None, "not a dict", 42, [1, 2]):
        result = check_component_floors(bad)
        assert result["passed"] is False
        assert result["checks"]
        assert result["composite_mean"] is None


def test_non_numeric_fields_do_not_crash():
    weird = {"composite_mean": "high", "composite_parts": {"judge_mean": "a", "objective_mean": None}}
    result = check_component_floors(weird)
    assert result["passed"] is False
    assert set(failed_checks(result)) == {"composite_floor", "judge_floor", "objective_floor"}


def test_headline_reports_pass_and_fail():
    assert "PASS" in component_floor_headline(check_component_floors(_result(0.62, 0.7, 0.6)))
    fail = component_floor_headline(check_component_floors(_result(0.55, 0.9, 0.1)))
    assert "FAIL" in fail and "objective_floor" in fail
    assert component_floor_headline({}) == "component floors: no checks evaluated"
    assert DEFAULT_MIN_COMPOSITE == 0.5


def test_every_floor_reported_even_when_all_fail():
    result = check_component_floors(_result(0.1, 0.1, 0.1))
    assert len(result["checks"]) == 3
    assert set(failed_checks(result)) == {"composite_floor", "judge_floor", "objective_floor"}


def test_stricter_than_a_single_composite_floor():
    # Two runs with the SAME composite (0.55, above a 0.5 --fail-under floor): the balanced one
    # passes, the fluff-driven one (weak objective anchor) is blocked. This is the whole point:
    # a per-component gate catches what a single composite floor cannot.
    balanced = check_component_floors(_result(0.55, 0.55, 0.55), min_composite=0.5,
                                      min_judge=0.4, min_objective=0.4)
    fluff = check_component_floors(_result(0.55, 0.95, 0.15), min_composite=0.5,
                                   min_judge=0.4, min_objective=0.4)
    assert balanced["passed"] is True
    assert fluff["passed"] is False and failed_checks(fluff) == ["objective_floor"]


def test_gates_a_multi_repo_result_with_top_level_parts():
    # A multi-repo aggregate carries composite_parts at the top level, so it gates the same way.
    multi = {"repos": 3, "scored_repos": 3, "composite_mean": 0.6,
             "composite_parts": {"judge_mean": 0.62, "objective_mean": 0.58}, "per_repo": []}
    result = check_component_floors(multi, min_composite=0.5, min_judge=0.4, min_objective=0.4)
    assert result["passed"] is True
    assert result["judge_mean"] == 0.62 and result["objective_mean"] == 0.58


def test_a_perfect_judge_cannot_rescue_a_zero_anchor():
    # The extreme: judge 1.0 but the objective anchor is 0.0 -> blocked on the anchor floor.
    result = check_component_floors(_result(0.6, 1.0, 0.0), min_objective=0.4)
    assert result["passed"] is False
    assert "objective_floor" in failed_checks(result)
    assert "FAIL" in component_floor_headline(result)


def test_check_component_floors_does_not_mutate_the_result():
    run = _result(0.62, 0.7, 0.6)
    snapshot = copy.deepcopy(run)
    check_component_floors(run)
    assert run == snapshot


# --- unscored multi-repo placeholder must not be read as a real 0.0 score ---------------
# `run_multi_replay` reports `scored_repos: 0` with placeholder means of `0.0` (averages over
# empty lists). The gate drops those placeholders to None (same `scored_repos` guard promotion and
# `run_eval --fail-under` already apply), so an unscored run never clears the floors — while a
# genuinely scored run whose components are really 0.0 is preserved.


def test_unscored_multi_repo_placeholder_fails_all_floors():
    empty_run = {
        "repos": 2, "scored_repos": 0, "skipped": 2, "composite_mean": 0.0,
        "composite_parts": {"judge_mean": 0.0, "objective_mean": 0.0},
    }
    result = check_component_floors(empty_run)
    assert result["passed"] is False
    assert set(failed_checks(result)) == {"composite_floor", "judge_floor", "objective_floor"}
    assert result["composite_mean"] is None
    assert result["judge_mean"] is None
    assert result["objective_mean"] is None


def test_unscored_placeholder_is_not_passed_even_at_permissive_floors():
    # Without the guard the placeholder 0.0 would clear zero floors and a no-op run that scored
    # nothing could pass. It must stay held even at min_* = 0.0.
    empty_run = {
        "repos": 2, "scored_repos": 0, "skipped": 2, "composite_mean": 0.0,
        "composite_parts": {"judge_mean": 0.0, "objective_mean": 0.0},
    }
    result = check_component_floors(empty_run, min_composite=0.0, min_judge=0.0, min_objective=0.0)
    assert result["passed"] is False
    assert set(failed_checks(result)) == {"composite_floor", "judge_floor", "objective_floor"}


def test_genuine_zero_scored_run_is_a_real_score():
    # Control: same 0.0 means, but scored_repos > 0 means the run really scored 0.0. It must keep
    # its real values and be gated on them — proving scored_repos, not the numeric 0.0, marks the
    # placeholder unscored.
    scored_run = {
        "repos": 2, "scored_repos": 2, "skipped": 0, "composite_mean": 0.0,
        "composite_parts": {"judge_mean": 0.0, "objective_mean": 0.0},
    }
    result = check_component_floors(scored_run)
    assert result["composite_mean"] == 0.0
    assert result["judge_mean"] == 0.0
    assert result["objective_mean"] == 0.0
    assert set(failed_checks(result)) == {"composite_floor", "judge_floor", "objective_floor"}


def test_single_repo_zero_components_are_unaffected():
    # A single-repo run carries no scored_repos key, so its real 0.0 stays a real score.
    result = check_component_floors(_result(0.0, 0.0, 0.0))
    assert result["composite_mean"] == 0.0
    assert result["judge_mean"] == 0.0
    assert result["objective_mean"] == 0.0


def test_bool_scored_repos_is_not_treated_as_an_unscored_placeholder():
    # scored_repos must be a real int/float count; a bool is malformed, not the zero placeholder.
    run = {
        "repos": 1, "scored_repos": False, "composite_mean": 0.7,
        "composite_parts": {"judge_mean": 0.6, "objective_mean": 0.5},
    }
    result = check_component_floors(run)
    assert result["composite_mean"] == 0.7
    assert result["judge_mean"] == 0.6
    assert result["passed"] is True


# --- a non-list / malformed `checks` field must not crash the reporting helpers ----------------
# check_component_floors always emits a list of well-formed rows, but a hand-built or deserialized
# result whose `checks` isn't a list used to crash failed_checks / the headline on `c["name"]`.

_MALFORMED_CHECKS = ["not a list", 42, 3.14, True, {"name": "composite_floor"}, ("a", "b"), range(2)]


def test_check_rows_list_accepts_only_real_lists():
    rows = [{"name": "composite_floor", "passed": True}]
    assert _check_rows_list(rows) == rows
    assert _check_rows_list(None) == []
    assert _check_rows_list([]) == []
    for bad in _MALFORMED_CHECKS:
        assert _check_rows_list(bad) == [], bad


def test_check_rows_list_skips_unusable_rows():
    checks = [
        {"name": "keep", "passed": False},
        "not a dict",
        {"passed": True},                       # missing name
        {"name": "no_passed"},                   # missing passed
        {"name": 42, "passed": True},            # non-str name
        {"name": True, "passed": True},          # bool name (bool is an int subclass, not a str)
        {"name": "", "passed": True},            # empty name
        {"name": "   ", "passed": True},         # whitespace-only name
        {"name": "bad_passed", "passed": "yes"},  # non-bool passed
        {"name": "int_passed", "passed": 1},     # int is not bool
    ]
    assert _check_rows_list(checks) == [{"name": "keep", "passed": False}]


def test_a_dict_checks_value_is_warned_not_silently_dropped(caplog):
    # A dict `checks` is a non-list -> it is warned (not silent) and distinguished from a missing
    # key (None, which is silent). Refutes any notion that a dict is dropped silently.
    import logging

    with caplog.at_level(logging.WARNING, logger="benchmark.component_floor"):
        assert _check_rows_list({"name": "composite_floor", "passed": True}) == []
    assert any("checks is dict" in r.message for r in caplog.records)


def test_check_rows_list_warns_when_every_row_is_unusable(caplog):
    import logging

    with caplog.at_level(logging.WARNING, logger="benchmark.component_floor"):
        assert _check_rows_list([42, "bad", None]) == []
    assert any("no usable rows" in r.message for r in caplog.records)


def test_failed_checks_survives_a_non_list_checks_field():
    for bad in _MALFORMED_CHECKS:
        assert failed_checks({"checks": bad}) == [], bad


def test_headline_survives_a_non_list_checks_field():
    for bad in _MALFORMED_CHECKS:
        assert component_floor_headline({"checks": bad}) == "component floors: no checks evaluated", bad


def test_none_checks_is_silent_but_a_non_list_is_warned(caplog):
    # None (a missing checks key) is legitimate -> silent empty; a non-list value is malformed ->
    # warned. The two are handled distinctly, not conflated.
    import logging

    with caplog.at_level(logging.WARNING, logger="benchmark.component_floor"):
        assert _check_rows_list(None) == []
    assert not caplog.records
    caplog.clear()
    with caplog.at_level(logging.WARNING, logger="benchmark.component_floor"):
        assert _check_rows_list("garbage") == []
    assert any("checks is str" in r.message for r in caplog.records)
