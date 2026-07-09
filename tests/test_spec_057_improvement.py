"""Contract tests for specs/057-benchmark-improvement — assert improvement.py satisfies the spec's
EARS criteria: headline score extraction, adoption gate checks, row sanitization, headline branches,
and pure evaluation. Offline, deterministic.
"""

import copy
import logging
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from benchmark.improvement import (  # noqa: E402
    DEFAULT_MIN_GAIN,
    _check_rows_list,
    _dict,
    _is_number,
    check_improvement,
    failed_checks,
    improvement_headline,
)

_REQUIRED_KEYS = frozenset({
    "passed",
    "checks",
    "baseline_composite",
    "candidate_composite",
    "gain",
    "min_gain",
})

_MALFORMED_CHECKS = [
    "not a list",
    42,
    3.14,
    True,
    {"name": "both_scored"},
    ("a", "b"),
    range(2),
]


def _run(composite, scored_repos=None):
    out = {"composite_mean": composite, "rows": []}
    if scored_repos is not None:
        out["scored_repos"] = scored_repos
    return out


def _gen(tuned, held_out=0.5, scored_repos=3):
    return {
        "tuned": {"composite_mean": tuned, "scored_repos": scored_repos},
        "held_out": {"composite_mean": held_out, "scored_repos": 2},
        "generalization_gap": round(tuned - held_out, 3),
    }


# --- Input coercion -------------------------------------------------------------------------


def test_dict_helper_returns_dict_or_empty():
    assert _dict({"a": 1}) == {"a": 1}
    assert _dict(None) == {}
    assert _dict("nope") == {}


@pytest.mark.parametrize("value,expected", [
    (0.5, True),
    (1, True),
    (0, True),
    (True, False),
    (False, False),
    ("0.5", False),
    (None, False),
])
def test_is_number_semantics(value, expected):
    assert _is_number(value) is expected


@pytest.mark.parametrize("bad", (None, "not a dict", 42, [1, 2], ()))
def test_non_dict_artifacts_fail_gracefully_without_raising(bad):
    result = check_improvement(bad, _run(0.6))
    assert result["passed"] is False
    assert result["candidate_composite"] is None
    assert result["checks"]


# --- Headline score extraction --------------------------------------------------------------

def test_generalization_artifacts_compare_tuned_partition():
    result = check_improvement(_gen(0.66), _gen(0.60))
    assert result["baseline_composite"] == 0.60
    assert result["candidate_composite"] == 0.66
    assert result["passed"] is True


def test_unscored_aggregate_placeholder_is_not_a_real_score():
    baseline = _run(0.0, scored_repos=0)
    candidate = _run(0.66)
    result = check_improvement(candidate, baseline)
    assert result["baseline_composite"] is None
    assert result["passed"] is False
    assert "both_scored" in failed_checks(result)


def test_mixed_generalization_and_single_repo_still_compares_headlines():
    result = check_improvement(_gen(0.66), _run(0.60), min_gain=0.02)
    assert result["candidate_composite"] == 0.66
    assert result["baseline_composite"] == 0.60
    assert result["passed"] is True


# --- Improvement gate -----------------------------------------------------------------------


def test_clear_improvement_adopts():
    result = check_improvement(_run(0.66), _run(0.60), min_gain=0.02)
    assert result["passed"] is True
    assert [c["name"] for c in result["checks"]] == ["both_scored", "improves_by_margin"]
    assert result["gain"] == 0.06


def test_marginal_gain_below_bar_holds():
    result = check_improvement(_run(0.605), _run(0.60), min_gain=0.02)
    assert result["passed"] is False
    assert failed_checks(result) == ["improves_by_margin"]
    assert result["gain"] == 0.005


def test_matching_baseline_is_not_an_improvement():
    result = check_improvement(_run(0.60), _run(0.60), min_gain=0.02)
    assert result["passed"] is False
    assert result["gain"] == 0.0


def test_regression_is_not_an_improvement():
    result = check_improvement(_run(0.55), _run(0.60), min_gain=0.02)
    assert result["passed"] is False
    assert result["gain"] == -0.05


def test_gain_exactly_at_margin_is_adopted_inclusive_bound():
    assert check_improvement(_run(0.62), _run(0.60), min_gain=0.02)["passed"] is True
    assert check_improvement(_run(0.619), _run(0.60), min_gain=0.02)["passed"] is False
    assert check_improvement(_run(0.62), _run(0.60), min_gain=0.02)["gain"] == 0.02


def test_min_gain_is_configurable():
    runs = (_run(0.63), _run(0.60))
    assert check_improvement(*runs, min_gain=0.02)["passed"] is True
    assert check_improvement(*runs, min_gain=0.05)["passed"] is False


def test_zero_min_gain_adopts_non_negative_gain():
    assert check_improvement(_run(0.601), _run(0.600), min_gain=0.0)["passed"] is True
    assert check_improvement(_run(0.600), _run(0.600), min_gain=0.0)["passed"] is True
    assert check_improvement(_run(0.599), _run(0.600), min_gain=0.0)["passed"] is False


def test_missing_composite_fails_both_scored():
    result = check_improvement({"error": "no tasks"}, _run(0.6))
    assert result["passed"] is False
    assert "both_scored" in failed_checks(result)
    assert result["gain"] is None


def test_result_always_includes_required_keys():
    for candidate, baseline in (
        (_run(0.66), _run(0.60)),
        (_run(0.55), _run(0.60)),
        (_gen(0.66), _gen(0.60)),
        (None, _run(0.6)),
    ):
        result = check_improvement(candidate, baseline)
        assert _REQUIRED_KEYS <= frozenset(result)


def test_default_min_gain_constant():
    assert DEFAULT_MIN_GAIN == 0.02


# --- Failed checks --------------------------------------------------------------------------


def test_failed_checks_on_malformed_result_container():
    assert failed_checks({}) == []
    assert failed_checks("nope") == []
    assert failed_checks(check_improvement(_run(0.5), _run(0.6))) == ["improves_by_margin"]


def test_failed_checks_survives_non_list_checks_field():
    for bad in _MALFORMED_CHECKS:
        assert failed_checks({"checks": bad}) == [], bad


# --- Check-row sanitization -----------------------------------------------------------------


def test_check_rows_list_accepts_only_real_lists():
    rows = [{"name": "both_scored", "passed": True}]
    assert _check_rows_list(rows) == rows
    assert _check_rows_list(None) == []
    assert _check_rows_list([]) == []
    for bad in _MALFORMED_CHECKS:
        assert _check_rows_list(bad) == [], bad


def test_check_rows_list_skips_unusable_rows():
    checks = [
        {"name": "keep", "passed": False},
        "not a dict",
        {"passed": True},
        {"name": "no_passed"},
        {"name": 42, "passed": True},
        {"name": "bad_passed", "passed": "yes"},
    ]
    assert _check_rows_list(checks) == [{"name": "keep", "passed": False}]


def test_check_rows_list_warns_when_every_row_is_unusable(caplog):
    with caplog.at_level(logging.WARNING, logger="benchmark.improvement"):
        assert _check_rows_list([42, "bad", None]) == []
    assert any("no usable rows" in r.message for r in caplog.records)


def test_none_checks_is_silent_but_non_list_is_warned(caplog):
    with caplog.at_level(logging.WARNING, logger="benchmark.improvement"):
        assert _check_rows_list(None) == []
    assert not caplog.records
    caplog.clear()
    with caplog.at_level(logging.WARNING, logger="benchmark.improvement"):
        assert _check_rows_list("garbage") == []
    assert any("checks is str" in r.message for r in caplog.records)


# --- Improvement headline -------------------------------------------------------------------


def test_headline_adopt_exact_format():
    result = check_improvement(_run(0.67), _run(0.58), min_gain=0.03)
    assert improvement_headline(result) == (
        "improvement: ADOPT (composite 0.580 -> 0.670, gain 0.090)"
    )


def test_headline_hold_lists_failed_checks():
    result = check_improvement(_run(0.60), _run(0.60), min_gain=0.02)
    assert improvement_headline(result) == (
        "improvement: HOLD (1/2 checks failed: improves_by_margin)"
    )


def test_headline_no_checks_exact():
    assert improvement_headline({}) == "improvement: no checks evaluated"
    assert improvement_headline("nope") == "improvement: no checks evaluated"


def test_headline_survives_non_list_checks_field():
    for bad in _MALFORMED_CHECKS:
        assert improvement_headline({"checks": bad}) == "improvement: no checks evaluated", bad


def test_headline_never_contains_bare_none_for_missing_score():
    missing = improvement_headline(check_improvement({"error": "x"}, _run(0.6)))
    assert "None" not in missing
    assert missing.startswith("improvement: HOLD")


# --- Pure evaluation ------------------------------------------------------------------------


def test_check_improvement_does_not_mutate_inputs():
    baseline, candidate = _run(0.6), _run(0.66)
    snap_b, snap_c = copy.deepcopy(baseline), copy.deepcopy(candidate)
    check_improvement(candidate, baseline)
    assert baseline == snap_b and candidate == snap_c
