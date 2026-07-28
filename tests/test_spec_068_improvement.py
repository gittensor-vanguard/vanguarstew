"""Spec 068 contract tests for benchmark/improvement.py (improvement / adoption gate).

Pins the as-built behavior described in specs/068-benchmark-improvement/spec.md with literal
expected check names, ``passed`` values and detail strings, using values whose ``repr`` is
stable across platforms. The score-source and error-scan semantics the gate borrows
(``_headline_source``, ``acceptance._partition_error``, ``trend.headline_score``) are pinned
here as consumed — including the lone-``tuned`` arm, all three per-repo scan sites, and the
non-finite / oversized / placeholder score cases. Integration / CLI coverage lives in
tests/test_improvement.py.
"""

import copy
import logging
import os
import sys
from decimal import Decimal

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from benchmark.improvement import (  # noqa: E402
    _CHECK_ROW_KEYS,
    DEFAULT_MIN_GAIN,
    _artifact_error,
    _check_rows_list,
    _dict,
    _headline_source,
    _is_number,
    _num,
    check_improvement,
    failed_checks,
    improvement_headline,
)

_LOGGER = "benchmark.improvement"

_RESULT_KEYS = ("passed", "checks", "baseline_composite", "candidate_composite",
                "gain", "min_gain")


def _numpy_bool():
    # numpy is not a test dependency; a stand-in whose type name matches numpy's scalar bool
    # exercises the same non-`bool` rejection arm the real np.bool_ would hit.
    cls = type("bool_", (), {})
    return cls()


def _art(score):
    return {"composite_mean": score}


def _named(result):
    return {c["name"]: c for c in result["checks"]}


# --- Constants ---------------------------------------------------------------------------

def test_constants_are_pinned():
    assert DEFAULT_MIN_GAIN == 0.02
    assert _CHECK_ROW_KEYS == ("name", "passed")


# --- Numeric helpers ---------------------------------------------------------------------

def test_is_number_semantics():
    assert _is_number(3) is True
    assert _is_number(0.2) is True
    assert _is_number(-1.5) is True
    assert _is_number(True) is False
    assert _is_number(False) is False
    assert _is_number(float("nan")) is False
    assert _is_number(float("inf")) is False
    assert _is_number(float("-inf")) is False
    for bad in (Decimal("0.5"), "0.5", None, [1], {}):
        assert _is_number(bad) is False, bad


def test_is_number_rejects_oversized_int():
    # math.isfinite raises OverflowError for an int too large for a float; caught, not raised.
    assert _is_number(10 ** 400) is False


def test_dict_helper():
    assert _dict({"a": 1}) == {"a": 1}
    for bad in (42, None, "x", [1], True):
        assert _dict(bad) == {}


def test_num_formats_three_decimals_or_na():
    assert _num(0.1) == "0.100"
    assert _num(0.5) == "0.500"
    assert _num(-0.2) == "-0.200"
    assert _num(2) == "2.000"
    for na in (None, True, float("nan"), float("inf"), float("-inf"), 10 ** 400, "0.5"):
        assert _num(na) == "n/a", na


# --- Score and cleanliness sources -------------------------------------------------------

def test_headline_source_generalization_vs_top_level():
    tuned, held = {"composite_mean": 0.7}, {"composite_mean": 0.6}
    gen = {"tuned": tuned, "held_out": held, "composite_mean": 0.1}
    assert _headline_source(gen) is tuned
    flat = {"composite_mean": 0.5}
    assert _headline_source(flat) is flat


def test_headline_source_lone_tuned_is_top_level():
    # held_out missing or non-dict -> the artifact itself is evaluated, never the lone tuned.
    lone = {"tuned": {"composite_mean": 0.9}, "composite_mean": 0.5}
    assert _headline_source(lone) is lone
    non_dict_held = {"tuned": {"composite_mean": 0.9}, "held_out": "gone",
                     "composite_mean": 0.5}
    assert _headline_source(non_dict_held) is non_dict_held
    result = check_improvement(_art(0.7), lone)
    assert result["baseline_composite"] == 0.5      # top-level score, not tuned's 0.9


def test_scores_reject_non_finite_and_placeholder():
    # A non-finite / oversized composite_mean is not a score; nor is the scored_repos: 0
    # placeholder. Each fails both_scored with the missing-score detail.
    for bad in (float("inf"), float("nan"), 10 ** 400):
        result = check_improvement(_art(bad), _art(0.5))
        assert result["candidate_composite"] is None
        assert _named(result)["both_scored"]["detail"] == (
            "a composite score is missing from one artifact")
    placeholder = {"composite_mean": 0.0, "scored_repos": 0}
    result = check_improvement(placeholder, _art(0.5))
    assert result["candidate_composite"] is None
    assert result["passed"] is False


def test_artifact_error_scans_three_sites():
    assert _artifact_error({"composite_mean": 0.5, "error": "boom"}) == "boom"
    assert _artifact_error(
        {"composite_mean": 0.5, "per_repo": [{"ok": True}, {"error": "clone failed"}]}
    ) == "clone failed"
    assert _artifact_error(
        {"composite_mean": 0.5, "per_repo": ["  corrupt row  "]}) == "  corrupt row  "
    assert _artifact_error(_art(0.5)) is None


def test_artifact_error_ignores_held_out_and_falsy():
    # Only the evaluated (tuned) partition's cleanliness gates adoption.
    gen = {"tuned": {"composite_mean": 0.7},
           "held_out": {"composite_mean": 0.1, "error": "ho-fail"}}
    assert _artifact_error(gen) is None
    result = check_improvement(gen, _art(0.5))
    assert result["passed"] is True and result["gain"] == 0.2
    # ...but a tuned per_repo failure is named.
    dirty = {"tuned": {"composite_mean": 0.7, "per_repo": [{"error": "clone failed"}]},
             "held_out": {"composite_mean": 0.1}}
    check = _named(check_improvement(dirty, _art(0.5)))["both_scored"]
    assert check["passed"] is False
    assert check["detail"] == "candidate error: 'clone failed'"
    # Falsy errors are clean at every site.
    assert _artifact_error({"composite_mean": 0.5, "error": ""}) is None
    assert _artifact_error({"composite_mean": 0.5, "per_repo": [{"error": None}, ""]}) is None
    assert check_improvement({"composite_mean": 0.7, "error": ""}, _art(0.5))["passed"] is True


def test_artifact_error_ignores_malformed_containers():
    assert _artifact_error({"composite_mean": 0.5, "per_repo": "notalist"}) is None
    assert _artifact_error({"composite_mean": 0.5, "per_repo": [42, None, []]}) is None
    assert _artifact_error(None) is None
    assert _artifact_error(42) is None


# --- Gate --------------------------------------------------------------------------------

def test_result_carries_all_keys():
    result = check_improvement(_art(0.7), _art(0.5))
    for key in _RESULT_KEYS:
        assert key in result, key
    assert [c["name"] for c in result["checks"]] == ["both_scored", "improves_by_margin"]
    for row in result["checks"]:
        assert set(row) == {"name", "passed", "detail"}
        assert type(row["passed"]) is bool
    assert result["min_gain"] == 0.02


def test_adopts_on_sufficient_gain():
    result = check_improvement(_art(0.7), _art(0.5))
    assert result["passed"] is True
    assert result["gain"] == 0.2
    named = _named(result)
    assert named["both_scored"]["detail"] == (
        "baseline composite 0.500, candidate composite 0.700")
    assert named["improves_by_margin"]["detail"] == "gain 0.200 >= 0.02"


def test_holds_on_insufficient_gain_keeps_detail_form():
    # The ">=" detail form is kept even when the check FAILS, with min_gain raw-interpolated.
    result = check_improvement(_art(0.51), _art(0.5))
    check = _named(result)["improves_by_margin"]
    assert check["passed"] is False
    assert check["detail"] == "gain 0.010 >= 0.02"
    assert result["passed"] is False


def test_holds_on_negative_gain():
    result = check_improvement(_art(0.3), _art(0.5))
    assert result["gain"] == -0.2
    check = _named(result)["improves_by_margin"]
    assert check["passed"] is False
    assert check["detail"] == "gain -0.200 >= 0.02"


def test_both_scored_baseline_error_precedence():
    # A baseline error is named even when the candidate also errored.
    result = check_improvement({"composite_mean": 0.7, "error": "cand-bad"},
                               {"composite_mean": 0.5, "error": "base-bad"})
    named = _named(result)
    assert named["both_scored"]["detail"] == "baseline error: 'base-bad'"
    assert named["improves_by_margin"]["detail"] == "cannot compare composites"
    assert result["gain"] is None


def test_both_scored_reports_candidate_error():
    result = check_improvement({"composite_mean": 0.7, "error": "boom"}, _art(0.5))
    assert _named(result)["both_scored"]["detail"] == "candidate error: 'boom'"


def test_both_scored_missing_score_and_none_artifacts():
    result = check_improvement(_art(0.7), {"note": "unscored"})
    assert _named(result)["both_scored"]["detail"] == (
        "a composite score is missing from one artifact")
    # None / non-dict artifacts fail the checks rather than raise.
    result = check_improvement(None, None)
    named = _named(result)
    assert named["both_scored"]["detail"] == "a composite score is missing from one artifact"
    assert named["improves_by_margin"]["detail"] == "cannot compare composites"
    assert result["passed"] is False
    assert check_improvement(42, "x")["passed"] is False


def test_min_gain_is_raw_nan_and_neg_inf_arms():
    # min_gain participates unvalidated: NaN fails every comparison (and interpolates raw);
    # -inf passes any defined gain.
    result = check_improvement(_art(0.7), _art(0.5), min_gain=float("nan"))
    check = _named(result)["improves_by_margin"]
    assert check["passed"] is False
    assert check["detail"] == "gain 0.200 >= nan"
    result = check_improvement(_art(0.7), _art(0.5), min_gain=float("-inf"))
    assert result["passed"] is True


# --- Check-row sanitation ----------------------------------------------------------------

def test_check_rows_list_none_and_empty_silent(caplog):
    with caplog.at_level(logging.WARNING, logger=_LOGGER):
        assert _check_rows_list(None) == []
        assert _check_rows_list([]) == []
    assert not caplog.records


def test_check_rows_list_warns_on_non_list(caplog):
    with caplog.at_level(logging.WARNING, logger=_LOGGER):
        assert _check_rows_list({"name": "x", "passed": True}) == []
    assert any("not a list" in r.message for r in caplog.records)


def test_check_rows_list_skips_and_warns_on_malformed_rows(caplog):
    good = {"name": "ok", "passed": True}
    with caplog.at_level(logging.WARNING, logger=_LOGGER):
        assert _check_rows_list([good, "junk", {"name": "x"}, {"passed": True},
                                 {"name": 5, "passed": True},
                                 {"name": "n", "passed": 1}]) == [good]
    msgs = " ".join(r.message for r in caplog.records)
    assert "not an object" in msgs and "missing required key" in msgs
    assert "not str" in msgs and "not bool" in msgs


def test_check_rows_list_accepts_empty_name_here():
    # Only isinstance(name, str) is required — an empty name survives, unlike judge_gate /
    # run_clean, whose _check_row_field demands a non-empty str.
    row = {"name": "", "passed": False}
    assert _check_rows_list([row]) == [row]
    assert failed_checks({"checks": [row]}) == [""]


def test_check_rows_list_rejects_numpy_bool():
    # isinstance(passed, bool) admits only native bools: a numpy-shaped scalar bool is dropped
    # (no _is_passed type-name allowance here, unlike run_clean).
    stand_in = _numpy_bool()
    assert type(stand_in).__name__ == "bool_"
    assert _check_rows_list([{"name": "n", "passed": stand_in}]) == []


def test_check_rows_list_warns_when_no_usable_rows(caplog):
    with caplog.at_level(logging.WARNING, logger=_LOGGER):
        assert _check_rows_list([{"name": "n", "passed": 1}]) == []
    assert any("no usable rows" in r.message for r in caplog.records)


# --- Failed checks and headline ----------------------------------------------------------

def test_failed_checks_names_and_non_dict():
    result = {"checks": [{"name": "a", "passed": True}, {"name": "b", "passed": False}]}
    assert failed_checks(result) == ["b"]
    assert failed_checks(42) == []
    assert failed_checks(None) == []


def test_headline_no_checks():
    assert improvement_headline({"checks": []}) == "improvement: no checks evaluated"
    assert improvement_headline(42) == "improvement: no checks evaluated"
    assert improvement_headline({"checks": 42}) == "improvement: no checks evaluated"
    # Rows that all fail sanitation leave zero usable checks too.
    assert improvement_headline({"checks": [{"name": "n", "passed": 1}]}) == (
        "improvement: no checks evaluated")


def test_headline_adopt_literal():
    result = check_improvement(_art(0.7), _art(0.5))
    assert improvement_headline(result) == (
        "improvement: ADOPT (composite 0.500 -> 0.700, gain 0.200)")


def test_headline_adopt_renders_na_triple():
    # A hand-built passing result with missing fields renders n/a for all three figures.
    result = {"passed": True, "checks": [{"name": "a", "passed": True}]}
    assert improvement_headline(result) == (
        "improvement: ADOPT (composite n/a -> n/a, gain n/a)")


def test_headline_hold_counts_sanitized_rows_only():
    result = check_improvement(_art(0.51), _art(0.5))
    assert improvement_headline(result) == (
        "improvement: HOLD (1/2 checks failed: improves_by_margin)")
    # Malformed rows are excluded from BOTH the failed and total counts.
    hand_built = {"passed": False,
                  "checks": [{"name": "a", "passed": True},
                             {"name": "b", "passed": False},
                             "junk",
                             {"name": "c", "passed": 1}]}
    assert improvement_headline(hand_built) == "improvement: HOLD (1/2 checks failed: b)"


# --- Pure evaluation ---------------------------------------------------------------------

def test_check_does_not_mutate_inputs():
    candidate = {"tuned": {"composite_mean": 0.7, "per_repo": [{"error": "x"}]},
                 "held_out": {"composite_mean": 0.6}}
    baseline = {"composite_mean": 0.5, "per_repo": [{"ok": True}]}
    snap_c, snap_b = copy.deepcopy(candidate), copy.deepcopy(baseline)
    check_improvement(candidate, baseline)
    assert candidate == snap_c and baseline == snap_b
