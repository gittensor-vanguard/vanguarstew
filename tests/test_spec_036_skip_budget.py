"""Contract tests for specs/036-benchmark-skip-budget — assert skip_budget.py
satisfies the spec's EARS criteria: whole-number counts, multi-repo accounting, skip rate,
gate checks, result shape, checks-row sanitization, headline branches, and pure evaluation.
Offline, deterministic.
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
    _is_int,
    check_skip_budget,
    failed_checks,
    skip_budget_headline,
)

_REQUIRED_KEYS = frozenset({
    "passed", "checks", "repos", "scored_repos", "skipped",
    "skip_rate", "min_scored", "max_skip_rate",
})
_MALFORMED_CHECKS = [
    42, 3.14, True, {"name": "enough_scored"}, "not a list",
    ({"name": "enough_scored", "passed": False},),
    range(2),
]
_FALSY_SCALAR_CHECKS = [0, 0.0, False, ""]


def _multi(repos, scored, skipped=None, **extra):
    result = {"repos": repos, "scored_repos": scored, "composite_mean": 0.6}
    result["skipped"] = repos - scored if skipped is None else skipped
    result.update(extra)
    return result


def _names(result):
    return [c["name"] for c in result["checks"]]


# --- Constants ------------------------------------------------------------------------------


def test_default_min_scored_and_max_skip_rate():
    assert DEFAULT_MIN_SCORED == 3
    assert DEFAULT_MAX_SKIP_RATE == 0.25
    result = check_skip_budget(_multi(8, 7))
    assert result["min_scored"] == DEFAULT_MIN_SCORED
    assert result["max_skip_rate"] == DEFAULT_MAX_SKIP_RATE


# --- Whole-number count semantics -----------------------------------------------------------


def test_is_int_rejects_bool():
    assert not _is_int(True)
    assert not _is_int(False)
    assert _counts({"repos": True, "scored_repos": 1}) is None


@pytest.mark.parametrize("value", (8.0, 7.0, 0.0))
def test_is_int_rejects_float_whole_numbers(value):
    assert not _is_int(value)
    assert _counts({"repos": value, "scored_repos": 7}) is None
    assert _counts({"repos": 8, "scored_repos": value}) is None


def test_is_int_rejects_numpy_integer_scalars():
    np = pytest.importorskip("numpy")
    assert not _is_int(np.int64(8))
    assert not _is_int(np.int32(7))
    result = check_skip_budget({"repos": np.int64(8), "scored_repos": np.int64(7)})
    assert result["passed"] is False
    assert "multi_repo_accounting" in failed_checks(result)
    assert result["repos"] is None


# --- Input coercion -------------------------------------------------------------------------


@pytest.mark.parametrize("bad", (None, "not a dict", 42, [1, 2], ()))
def test_non_dict_result_coerced(bad):
    result = check_skip_budget(bad)
    assert result["passed"] is False
    assert result["checks"]
    assert result["repos"] is None


def test_dict_helper_returns_dict_or_empty():
    assert _dict({"a": 1}) == {"a": 1}
    assert _dict(None) == {}


def test_extra_input_keys_ignored():
    run = _multi(8, 7)
    run["unexpected_key"] = "ignored"
    run["tally"] = {"challenger": 99}
    snapshot = copy.deepcopy(run)
    result = check_skip_budget(run)
    assert result["passed"] is True
    assert run == snapshot


# --- Multi-repo accounting ------------------------------------------------------------------


def test_counts_happy_path():
    assert _counts({"repos": 8, "scored_repos": 7}) == (8, 7)


def test_counts_missing_skipped_ok():
    assert _counts({"repos": 5, "scored_repos": 5}) == (5, 5)


def test_counts_zero_repos():
    assert _counts({"repos": 0, "scored_repos": 0}) is None


def test_counts_negative_scored():
    assert _counts({"repos": 5, "scored_repos": -1}) is None


def test_counts_scored_exceeds_repos():
    assert _counts({"repos": 3, "scored_repos": 5}) is None


def test_counts_inconsistent_skipped():
    assert _counts({"repos": 8, "scored_repos": 6, "skipped": 0}) is None
    assert _counts({"repos": 8, "scored_repos": 6, "skipped": 2.0}) is None


def test_counts_non_integer_counts():
    assert _counts({"repos": "eight", "scored_repos": 7}) is None
    assert _counts({"repos": 8, "scored_repos": None}) is None


# --- Skip rate ------------------------------------------------------------------------------


def test_skip_rate_computed_and_rounded():
    result = check_skip_budget(_multi(3, 2), min_scored=1, max_skip_rate=0.4)
    assert result["skip_rate"] == 0.333


def test_skip_rate_none_when_incoherent():
    result = check_skip_budget({"composite_mean": 0.6})
    assert result["skip_rate"] is None
    assert any(c["detail"] == "skip rate unavailable" for c in result["checks"])


def test_full_coverage_skip_rate_is_zero_point_zero():
    result = check_skip_budget(_multi(5, 5), min_scored=3)
    assert result["skip_rate"] == 0.0
    assert result["skipped"] == 0


# --- Gate checks ----------------------------------------------------------------------------


def test_gate_always_reports_three_checks():
    result = check_skip_budget(_multi(8, 7))
    assert _names(result) == ["multi_repo_accounting", "enough_scored", "skip_within_budget"]
    assert all("name" in c and "passed" in c and "detail" in c for c in result["checks"])


def test_well_covered_run_passes():
    result = check_skip_budget(_multi(8, 7), min_scored=3, max_skip_rate=0.25)
    assert result["passed"] is True
    assert result["scored_repos"] == 7 and result["skipped"] == 1


def test_too_few_scored_fails():
    result = check_skip_budget(_multi(3, 2), min_scored=3, max_skip_rate=0.5)
    assert result["passed"] is False
    assert failed_checks(result) == ["enough_scored"]


def test_skip_rate_bound_inclusive():
    assert check_skip_budget(_multi(4, 3), min_scored=1, max_skip_rate=0.25)["passed"] is True
    assert check_skip_budget(_multi(4, 2), min_scored=1, max_skip_rate=0.25)["passed"] is False


def test_single_repo_fails_accounting():
    result = check_skip_budget({"composite_mean": 0.6, "tasks": 8})
    assert result["passed"] is False
    assert "multi_repo_accounting" in failed_checks(result)


# --- Gate result shape ----------------------------------------------------------------------


def test_gate_returns_required_keys():
    for artifact in (
        _multi(8, 7),
        {"composite_mean": 0.6},
        None,
    ):
        out = check_skip_budget(artifact)
        assert _REQUIRED_KEYS <= frozenset(out)


def test_incoherent_accounting_yields_none_fields():
    result = check_skip_budget({"repos": 0, "scored_repos": 0})
    assert result["repos"] is None
    assert result["scored_repos"] is None
    assert result["skipped"] is None
    assert result["skip_rate"] is None


# --- Malformed gate-result robustness -------------------------------------------------------


@pytest.mark.parametrize("bad", _MALFORMED_CHECKS)
def test_check_rows_list_treats_non_list_as_empty(bad):
    assert _check_rows_list(bad) == []


def test_check_rows_list_none_and_empty_silent(caplog):
    with caplog.at_level(logging.WARNING, logger="benchmark.skip_budget"):
        assert _check_rows_list(None) == []
        assert _check_rows_list([]) == []
    assert not caplog.records


@pytest.mark.parametrize("bad", _FALSY_SCALAR_CHECKS)
def test_check_rows_list_treats_falsy_scalars_as_non_list(bad, caplog):
    with caplog.at_level(logging.WARNING, logger="benchmark.skip_budget"):
        assert _check_rows_list(bad) == []
    assert any("not a list" in r.message for r in caplog.records)


def test_check_rows_list_skips_non_dict_rows(caplog):
    mixed = [42, {"name": "enough_scored", "passed": True}]
    with caplog.at_level(logging.WARNING, logger="benchmark.skip_budget"):
        assert len(_check_rows_list(mixed)) == 1
    assert any("checks[0] is int" in r.message for r in caplog.records)


def test_check_rows_list_warns_when_all_unusable(caplog):
    junk = [42, "bad", None]
    with caplog.at_level(logging.WARNING, logger="benchmark.skip_budget"):
        assert _check_rows_list(junk) == []
    messages = [r.message for r in caplog.records]
    assert any("no usable rows" in m for m in messages)


def test_check_rows_list_rejects_int_as_passed(caplog):
    with caplog.at_level(logging.WARNING, logger="benchmark.skip_budget"):
        assert _check_rows_list([{"name": "enough_scored", "passed": 1}]) == []
    assert any("passed is int" in r.message for r in caplog.records)


def test_failed_checks_tolerates_malformed_result():
    assert failed_checks({}) == []
    assert failed_checks("not a dict") == []
    assert failed_checks({"checks": "oops"}) == []
    assert failed_checks({"checks": [{"name": "enough_scored", "passed": False}]}) == [
        "enough_scored"
    ]


# --- Skip budget headline -------------------------------------------------------------------


def test_headline_covered_exact_format():
    ok = check_skip_budget(_multi(8, 8), min_scored=3)
    assert skip_budget_headline(ok) == "skip budget: COVERED (8 of 8 repos scored, skip rate 0.0)"

    partial = check_skip_budget(_multi(8, 7), min_scored=3, max_skip_rate=0.25)
    assert skip_budget_headline(partial) == (
        "skip budget: COVERED (7 of 8 repos scored, skip rate 0.125)"
    )


def test_headline_under_covered_exact_format():
    one_fail = check_skip_budget(_multi(3, 2), min_scored=3, max_skip_rate=0.5)
    assert skip_budget_headline(one_fail) == (
        "skip budget: UNDER-COVERED (1/3 checks failed: enough_scored)"
    )

    all_fail = check_skip_budget({})
    assert skip_budget_headline(all_fail) == (
        "skip budget: UNDER-COVERED (3/3 checks failed: "
        "multi_repo_accounting, enough_scored, skip_within_budget)"
    )


def test_headline_no_checks_evaluated():
    assert skip_budget_headline({}) == "skip budget: no checks evaluated"
    assert skip_budget_headline("not a dict") == "skip budget: no checks evaluated"
    assert skip_budget_headline({"checks": []}) == "skip budget: no checks evaluated"


@pytest.mark.parametrize("bad", _MALFORMED_CHECKS)
def test_headline_no_checks_when_passed_false_and_zero_sanitized(bad):
    line = skip_budget_headline({"passed": False, "checks": bad})
    assert line == "skip budget: no checks evaluated", bad


@pytest.mark.parametrize("bad", _MALFORMED_CHECKS)
def test_headline_no_checks_when_passed_true_and_zero_sanitized(bad):
    line = skip_budget_headline({"passed": True, "checks": bad, "scored_repos": 8, "repos": 8})
    assert line == "skip budget: no checks evaluated", bad


def test_headline_never_bare_none_from_gate():
    for artifact in (
        _multi(8, 8),
        _multi(6, 1),
        {"composite_mean": 0.6},
        None,
    ):
        line = skip_budget_headline(check_skip_budget(artifact))
        assert "None" not in line


def test_headline_extra_result_keys_ignored():
    gate = check_skip_budget(_multi(8, 8), min_scored=3)
    gate["extra_field"] = "ignored"
    assert skip_budget_headline(gate) == "skip budget: COVERED (8 of 8 repos scored, skip rate 0.0)"


def test_headline_skip_rate_unavailable_detail_not_in_headline():
    """n/a skip-rate path: incoherent accounting yields None skip_rate in gate, not in COVERED."""
    bad = check_skip_budget({"repos": 0, "scored_repos": 0})
    assert bad["skip_rate"] is None
    line = skip_budget_headline(bad)
    assert "skip rate unavailable" not in line
    assert "UNDER-COVERED" in line


# --- Pure evaluation ------------------------------------------------------------------------


def test_check_skip_budget_does_not_mutate_result():
    run = _multi(8, 7)
    snapshot = copy.deepcopy(run)
    check_skip_budget(run)
    assert run == snapshot
