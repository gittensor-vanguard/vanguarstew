"""Contract tests for specs/036-benchmark-skip-budget — assert skip_budget.py satisfies the
spec's EARS criteria: input coercion, count parsing, fail-closed gate evaluation, checks-row
sanitization, headline branches, and pure evaluation. Offline, deterministic.
"""

import copy
import logging
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from benchmark.skip_budget import (  # noqa: E402
    DEFAULT_MAX_SKIP_RATE,
    DEFAULT_MIN_SCORED,
    _check_rows_list,
    _counts,
    _dict,
    _is_bool,
    _is_int,
    check_skip_budget,
    failed_checks,
    skip_budget_headline,
)

_LOGGER = "benchmark.skip_budget"
_CHECK_ORDER = ["multi_repo_accounting", "enough_scored", "skip_within_budget"]
_REQUIRED_KEYS = frozenset({
    "passed", "checks", "repos", "scored_repos", "skipped",
    "skip_rate", "min_scored", "max_skip_rate",
})


def _tally(repos, scored, skipped=None, **extra):
    result = {"repos": repos, "scored_repos": scored}
    if skipped is not None:
        result["skipped"] = skipped
    result.update(extra)
    return result


def _names(result):
    return [c["name"] for c in result["checks"]]


def _warnings(caplog):
    return [r for r in caplog.records if r.name == _LOGGER]


# --- Input coercion -------------------------------------------------------------------------


@pytest.mark.parametrize("bad", (None, "not a dict", 42, [1, 2], ()))
def test_non_dict_result_coerced_to_empty_dict(bad):
    out = check_skip_budget(bad)
    assert out["passed"] is False
    assert out["repos"] is None and out["scored_repos"] is None
    assert _names(out) == _CHECK_ORDER


def test_dict_helper_returns_dict_or_empty():
    assert _dict({"a": 1}) == {"a": 1}
    assert _dict(None) == {}


# --- Whole-number count semantics -----------------------------------------------------------


def test_is_int_rejects_bool():
    assert not _is_int(True)
    assert not _is_int(False)
    assert _counts({"repos": True, "scored_repos": 1}) is None
    assert _counts({"repos": 5, "scored_repos": False}) is None


@pytest.mark.parametrize("value", (5.0, 4.0, 0.0))
def test_is_int_rejects_float_whole_numbers(value):
    assert not _is_int(value)
    assert _counts({"repos": value, "scored_repos": 4}) is None
    assert _counts({"repos": 5, "scored_repos": value}) is None


# --- Boolean semantics ----------------------------------------------------------------------


def test_is_bool_accepts_bool_rejects_int():
    assert _is_bool(True)
    assert _is_bool(False)
    assert not _is_bool(1)
    assert not _is_bool(0)
    assert not _is_bool("x")


# --- Multi-repo accounting ------------------------------------------------------------------


def test_counts_coherent_tally():
    assert _counts({"repos": 8, "scored_repos": 7}) == (8, 7)
    assert _counts({"repos": 8, "scored_repos": 7, "skipped": 1}) == (8, 7)
    assert _counts({"repos": 4, "scored_repos": 4}) == (4, 4)


def test_counts_incoherent_returns_none():
    assert _counts({"repos": 0, "scored_repos": 0}) is None
    assert _counts({"repos": -1, "scored_repos": 0}) is None
    assert _counts({"repos": 5, "scored_repos": -1}) is None
    assert _counts({"repos": 3, "scored_repos": 5}) is None
    assert _counts({"scored_repos": 3}) is None
    assert _counts({"repos": 5}) is None


def test_counts_skipped_field_must_reconcile():
    assert _counts({"repos": 8, "scored_repos": 7, "skipped": 2}) is None
    assert _counts({"repos": 8, "scored_repos": 7, "skipped": 1.0}) is None
    assert _counts({"repos": 8, "scored_repos": 7, "skipped": 1}) == (8, 7)


# --- Gate evaluation ------------------------------------------------------------------------


def test_well_covered_run_passes():
    result = check_skip_budget(_tally(8, 7), min_scored=3, max_skip_rate=0.25)  # skip 1/8 = 0.125
    assert result["passed"] is True
    assert _names(result) == _CHECK_ORDER
    assert result["scored_repos"] == 7
    assert result["skipped"] == 1
    assert result["skip_rate"] == 0.125


def test_too_few_scored_fails_enough_scored():
    result = check_skip_budget(_tally(3, 2), min_scored=3, max_skip_rate=0.9)  # only 2 scored
    assert result["passed"] is False
    assert failed_checks(result) == ["enough_scored"]


def test_too_many_skipped_fails_skip_within_budget():
    result = check_skip_budget(_tally(6, 2), min_scored=1, max_skip_rate=0.25)  # skip 4/6 = 0.667
    assert result["passed"] is False
    assert failed_checks(result) == ["skip_within_budget"]
    assert result["skip_rate"] == 0.667


def test_incoherent_tally_fails_dependent_checks_closed():
    result = check_skip_budget({"repos": "x", "scored_repos": 2})
    assert result["passed"] is False
    assert failed_checks(result) == _CHECK_ORDER
    assert result["skipped"] is None
    assert result["skip_rate"] is None


def test_bounds_are_inclusive():
    assert check_skip_budget(_tally(4, 3), min_scored=1, max_skip_rate=0.25)["passed"] is True   # 0.25
    assert check_skip_budget(_tally(4, 2), min_scored=1, max_skip_rate=0.25)["passed"] is False  # 0.50
    assert check_skip_budget(_tally(8, 3), min_scored=3, max_skip_rate=1.0)["passed"] is True    # ==min
    assert check_skip_budget(_tally(8, 2), min_scored=3, max_skip_rate=1.0)["passed"] is False


def test_default_thresholds():
    result = check_skip_budget(_tally(8, 7))
    assert result["min_scored"] == DEFAULT_MIN_SCORED == 3
    assert result["max_skip_rate"] == DEFAULT_MAX_SKIP_RATE == 0.25


def test_result_always_includes_required_keys():
    for result_in in (_tally(8, 7), {"repos": "x"}, {}, None):
        out = check_skip_budget(result_in)
        assert _REQUIRED_KEYS <= frozenset(out)
        assert _names(out) == _CHECK_ORDER


# --- Checks-row sanitization ----------------------------------------------------------------


def test_check_rows_list_none_and_empty_are_silent(caplog):
    with caplog.at_level(logging.WARNING, logger=_LOGGER):
        assert _check_rows_list(None) == []
        assert _check_rows_list([]) == []
    assert _warnings(caplog) == []


def test_check_rows_list_non_list_warns_and_empties(caplog):
    with caplog.at_level(logging.WARNING, logger=_LOGGER):
        assert _check_rows_list("garbage") == []
    assert any("not a list" in r.getMessage() for r in _warnings(caplog))


def test_check_rows_list_skips_unusable_rows():
    rows = [
        {"name": "ok", "passed": True},
        42,                                     # not a dict
        {"name": "no_passed"},                  # missing passed
        {"passed": True},                       # missing name
        {"name": 1, "passed": True},            # non-str name
        {"name": "int_passed", "passed": 1},    # non-bool passed
    ]
    assert _check_rows_list(rows) == [{"name": "ok", "passed": True}]


def test_check_rows_list_all_unusable_warns(caplog):
    with caplog.at_level(logging.WARNING, logger=_LOGGER):
        assert _check_rows_list([{"bad": 1}]) == []
    assert any("no usable rows" in r.getMessage() for r in _warnings(caplog))


# --- Failed checks --------------------------------------------------------------------------


def test_failed_checks_names_failed_rows():
    result = check_skip_budget(_tally(6, 2), min_scored=1, max_skip_rate=0.25)
    assert failed_checks(result) == ["skip_within_budget"]


def test_failed_checks_robust_to_malformed_checks():
    assert failed_checks({"checks": "garbage"}) == []
    assert failed_checks({"checks": [{"name": "a", "passed": False},
                                     {"name": "b", "passed": True}]}) == ["a"]
    assert failed_checks({}) == []
    assert failed_checks("not a dict") == []


# --- Skip budget headline -------------------------------------------------------------------


def test_headline_covered_exact_format():
    result = check_skip_budget(_tally(8, 7), min_scored=3, max_skip_rate=0.25)
    assert skip_budget_headline(result) == (
        "skip budget: COVERED (7 of 8 repos scored, skip rate 0.125)"
    )


def test_headline_under_covered_exact_format():
    result = check_skip_budget(_tally(6, 2), min_scored=1, max_skip_rate=0.25)
    assert skip_budget_headline(result) == (
        "skip budget: UNDER-COVERED (1/3 checks failed: skip_within_budget)"
    )


def test_headline_no_checks_evaluated():
    assert skip_budget_headline({}) == "skip budget: no checks evaluated"
    assert skip_budget_headline({"checks": []}) == "skip budget: no checks evaluated"
    assert skip_budget_headline("nope") == "skip budget: no checks evaluated"


def test_headline_non_list_checks_shows_no_checks():
    assert skip_budget_headline({"checks": "garbage", "passed": True}) == (
        "skip budget: no checks evaluated"
    )


# --- Pure evaluation ------------------------------------------------------------------------


def test_check_does_not_mutate_result():
    result_in = {"repos": 8, "scored_repos": 7, "skipped": 1}
    snapshot = copy.deepcopy(result_in)
    check_skip_budget(result_in)
    assert result_in == snapshot
