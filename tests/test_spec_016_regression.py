"""Contract tests for specs/016-benchmark-regression — assert regression.py satisfies the spec's
EARS criteria: input coercion, numeric semantics, rounding, the headline_score composite source,
order-disagreement resolution (flat, per-partition, and generalization summation), fail-closed gate
evaluation with inclusive bounds, checks-row sanitization, headline branches, and pure evaluation.
Offline, deterministic.
"""

import copy
import logging
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from benchmark.regression import (  # noqa: E402
    DEFAULT_MAX_COMPOSITE_DROP,
    DEFAULT_MAX_DISAGREEMENT_INCREASE,
    _check_rows_list,
    _dict,
    _disagreement,
    _flat_disagreement,
    _is_number,
    _partition_disagreement_counts,
    _round,
    check_regression,
    failed_checks,
    regression_headline,
)
from benchmark.trend import headline_score  # noqa: E402

_LOGGER = "benchmark.regression"
_CHECK_ORDER = ["both_scored", "no_composite_regression", "no_judge_instability_increase"]
_REQUIRED_KEYS = frozenset({
    "passed", "checks", "baseline_composite", "candidate_composite", "composite_delta",
    "disagreement_delta", "max_composite_drop", "max_disagreement_increase",
})


def _run(composite, disagreement=None):
    art = {"composite_mean": composite, "rows": []}
    if disagreement is not None:
        art["judge_report"] = {"disagreement_rate": disagreement}
    return art


def _row(result, name):
    return next(c for c in result["checks"] if c["name"] == name)


# --- Input coercion ---------------------------------------------------------------------------

def test_non_dict_artifacts_coerced_and_fail_gracefully():
    for bad in (None, "not a dict", 42, [1, 2], 3.5):
        result = check_regression(bad, _run(0.6))
        assert result["passed"] is False
        assert [c["name"] for c in result["checks"]] == _CHECK_ORDER
        assert result["candidate_composite"] is None
        assert "both_scored" in failed_checks(result)


def test_dict_helper_returns_dict_or_empty():
    d = {"a": 1}
    assert _dict(d) is d
    for bad in (None, "x", 3, [1], (1,), True):
        assert _dict(bad) == {}


# --- Numeric semantics ------------------------------------------------------------------------

def test_is_number_accepts_int_and_float():
    assert _is_number(3) is True
    assert _is_number(3.5) is True
    assert _is_number(-1) is True


def test_is_number_rejects_bool():
    assert _is_number(True) is False
    assert _is_number(False) is False


def test_is_number_rejects_non_numbers():
    for bad in (None, "1", [1], {"a": 1}, (1,)):
        assert _is_number(bad) is False


# --- Rounding ---------------------------------------------------------------------------------

def test_round_rounds_numbers_to_three_places():
    assert _round(0.12345) == 0.123
    assert _round(2) == 2.0
    assert isinstance(_round(2), float)


def test_round_returns_none_for_non_number():
    for bad in (None, True, False, "0.5", [0.5]):
        assert _round(bad) is None


# --- Compared composite -----------------------------------------------------------------------

def test_composites_come_from_headline_score():
    baseline, candidate = _run(0.60), _run(0.66)
    result = check_regression(candidate, baseline)
    assert result["baseline_composite"] == headline_score(baseline)
    assert result["candidate_composite"] == headline_score(candidate)


def test_unscored_or_errored_artifact_has_none_composite():
    result = check_regression({"error": "no tasks"}, _run(0.6))
    assert result["candidate_composite"] is None
    assert _row(result, "both_scored")["passed"] is False


# --- Order-disagreement resolution ------------------------------------------------------------

def test_flat_disagreement_prefers_stats_over_report():
    art = {
        "judge_report": {"disagreement_rate": 0.2},
        "judge_order_stats": {"dual_order_tasks": 10, "disagree": 3, "agree": 5, "tie": 2},
    }
    assert _flat_disagreement(art) == 0.3


def test_flat_disagreement_none_without_telemetry():
    assert _flat_disagreement({}) is None
    assert _flat_disagreement({"judge_report": {}, "judge_order_stats": {}}) is None


def test_partition_counts_prefer_stats_and_derive_dual():
    # dual_order_tasks absent -> derived as agree + disagree + tie.
    part = {"judge_order_stats": {"agree": 5, "disagree": 3, "tie": 2}}
    assert _partition_disagreement_counts(part) == (3, 10)


def test_partition_counts_accept_disagreements_alias():
    part = {"judge_report": {"dual_order_tasks": 4, "disagreements": 1}}
    assert _partition_disagreement_counts(part) == (1, 4)


def test_partition_counts_none_when_dual_missing_or_zero():
    assert _partition_disagreement_counts({}) is None
    assert _partition_disagreement_counts({"judge_report": {"disagree": 1}}) is None
    assert _partition_disagreement_counts(
        {"judge_order_stats": {"dual_order_tasks": 0, "disagree": 0}}) is None


def test_generalization_sums_both_partitions():
    art = {
        "tuned": {"judge_order_stats": {"dual_order_tasks": 10, "disagree": 2, "agree": 8, "tie": 0}},
        "held_out": {"judge_order_stats": {"dual_order_tasks": 10, "disagree": 4, "agree": 6, "tie": 0}},
    }
    # (2 + 4) / (10 + 10) = 0.3
    assert _disagreement(art) == 0.3


def test_generalization_none_when_no_partition_counts():
    assert _disagreement({"tuned": {}, "held_out": {}}) is None


def test_flat_used_without_both_partitions():
    # Only `tuned` present (no `held_out`) -> flat path reads top-level telemetry, not partitions.
    art = {"tuned": {"judge_order_stats": {"dual_order_tasks": 10, "disagree": 9}},
           "judge_report": {"disagreement_rate": 0.4}}
    assert _disagreement(art) == 0.4


# --- Gate evaluation --------------------------------------------------------------------------

def test_checks_order_and_shape():
    result = check_regression(_run(0.66), _run(0.60))
    assert [c["name"] for c in result["checks"]] == _CHECK_ORDER
    for row in result["checks"]:
        assert set(row) == {"name", "passed", "detail"}
        assert isinstance(row["passed"], bool)


def test_both_scored_gate():
    assert _row(check_regression(_run(0.6), _run(0.6)), "both_scored")["passed"] is True
    assert _row(check_regression({"error": "x"}, _run(0.6)), "both_scored")["passed"] is False


def test_no_composite_regression_inclusive_bound():
    # Drop exactly at the tolerance passes; one thousandth beyond fails.
    assert check_regression(_run(0.58), _run(0.60), max_composite_drop=0.02)["passed"] is True
    assert check_regression(_run(0.579), _run(0.60), max_composite_drop=0.02)["passed"] is False
    blocked = check_regression(_run(0.55), _run(0.60), max_composite_drop=0.02)
    assert _row(blocked, "no_composite_regression")["passed"] is False
    assert blocked["composite_delta"] == -0.05


def test_no_judge_instability_increase_gate():
    at_bound = check_regression(_run(0.6, 0.2), _run(0.6, 0.1), max_disagreement_increase=0.1)
    assert _row(at_bound, "no_judge_instability_increase")["passed"] is True
    assert at_bound["disagreement_delta"] == 0.1
    beyond = check_regression(_run(0.6, 0.21), _run(0.6, 0.1), max_disagreement_increase=0.1)
    assert _row(beyond, "no_judge_instability_increase")["passed"] is False


def test_judge_check_passes_vacuously_without_both_rates():
    result = check_regression(_run(0.6, 0.9), _run(0.6))  # baseline has no rate
    assert _row(result, "no_judge_instability_increase")["passed"] is True
    assert result["disagreement_delta"] is None


def test_passed_is_conjunction_of_checks():
    ok = check_regression(_run(0.66), _run(0.60))
    assert ok["passed"] is True and all(c["passed"] for c in ok["checks"])
    bad = check_regression(_run(0.40), _run(0.60))
    assert bad["passed"] is False and not all(c["passed"] for c in bad["checks"])


def test_result_always_includes_required_keys():
    result = check_regression(_run(0.6), _run(0.6))
    assert _REQUIRED_KEYS <= set(result)


def test_default_thresholds():
    assert DEFAULT_MAX_COMPOSITE_DROP == 0.02
    assert DEFAULT_MAX_DISAGREEMENT_INCREASE == 0.1
    result = check_regression(_run(0.6), _run(0.6))
    assert result["max_composite_drop"] == 0.02
    assert result["max_disagreement_increase"] == 0.1


def test_thresholds_are_configurable():
    runs = (_run(0.57), _run(0.60))  # drop 0.03
    assert check_regression(*runs, max_composite_drop=0.05)["passed"] is True
    assert check_regression(*runs, max_composite_drop=0.02)["passed"] is False
    rise = (_run(0.6, 0.5), _run(0.6, 0.1))  # +0.4
    assert check_regression(*rise, max_disagreement_increase=0.5)["passed"] is True
    assert check_regression(*rise, max_disagreement_increase=0.1)["passed"] is False


# --- Checks-row sanitization ------------------------------------------------------------------

def test_check_rows_list_none_and_empty_are_silent(caplog):
    with caplog.at_level(logging.WARNING, logger=_LOGGER):
        assert _check_rows_list(None) == []
        assert _check_rows_list([]) == []
    assert caplog.records == []


def test_check_rows_list_non_list_warns_and_empties(caplog):
    for bad in ("checks", 3, {"name": "x"}, (1, 2), range(2)):
        caplog.clear()
        with caplog.at_level(logging.WARNING, logger=_LOGGER):
            assert _check_rows_list(bad) == []
        assert any("not a list" in r.message for r in caplog.records)


def test_check_rows_list_skips_unusable_rows(caplog):
    rows = [
        {"name": "ok", "passed": True},          # usable
        "not-a-dict",                             # skipped
        {"passed": True},                         # missing name
        {"name": "x"},                            # missing passed
        {"name": 3, "passed": True},              # name not str
        {"name": "y", "passed": 1},               # passed not bool
    ]
    with caplog.at_level(logging.WARNING, logger=_LOGGER):
        usable = _check_rows_list(rows)
    assert usable == [{"name": "ok", "passed": True}]
    assert len(caplog.records) >= 5


def test_check_rows_list_all_unusable_warns(caplog):
    with caplog.at_level(logging.WARNING, logger=_LOGGER):
        assert _check_rows_list([{"name": 1, "passed": True}]) == []
    assert any("no usable rows" in r.message for r in caplog.records)


# --- Failed checks ----------------------------------------------------------------------------

def test_failed_checks_names_failed_rows():
    result = check_regression(_run(0.4), _run(0.6))
    assert failed_checks(result) == ["no_composite_regression"]


def test_failed_checks_robust_to_malformed_checks():
    assert failed_checks({"checks": "nope"}) == []
    assert failed_checks({}) == []
    assert failed_checks({"checks": [{"bogus": 1}, {"name": "f", "passed": False}]}) == ["f"]


# --- Regression headline ----------------------------------------------------------------------

def test_headline_ok_exact_format():
    result = check_regression(_run(0.61), _run(0.60))
    assert regression_headline(result) == "regression: OK (composite 0.6 -> 0.61, delta 0.01)"


def test_headline_blocked_exact_format():
    result = check_regression(_run(0.40), _run(0.60))
    assert regression_headline(result) == (
        "regression: BLOCKED (1/3 checks failed: no_composite_regression)")


def test_headline_no_checks_evaluated():
    assert regression_headline({}) == "regression: no checks evaluated"
    assert regression_headline({"checks": []}) == "regression: no checks evaluated"


def test_headline_non_list_checks_shows_no_checks(caplog):
    with caplog.at_level(logging.WARNING, logger=_LOGGER):
        assert regression_headline({"passed": True, "checks": "nope"}) == (
            "regression: no checks evaluated")
    assert any("not a list" in r.message for r in caplog.records)


# --- Pure evaluation --------------------------------------------------------------------------

def test_check_does_not_mutate_inputs():
    baseline = _run(0.60, 0.1)
    candidate = _run(0.55, 0.3)
    base_copy, cand_copy = copy.deepcopy(baseline), copy.deepcopy(candidate)
    check_regression(candidate, baseline)
    assert baseline == base_copy
    assert candidate == cand_copy
