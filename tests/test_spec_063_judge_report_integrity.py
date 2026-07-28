"""Contract tests for specs/063-benchmark-judge-report-integrity — assert
judge_report_integrity.py satisfies the spec's EARS criteria.

Covers, in direct response to the Spec 057/059/061/062 rejection class: `_is_number` rejecting
`decimal.Decimal` (and other non-int/float numerics), warning EMISSION for every warn branch,
the full `_NUMPY_BOOL_TYPENAMES` numpy coverage with a stand-in proven to hit the branch, the
`int`-vs-`bool` verdict rejection, both `_check_slice` telemetry branches, and every headline
branch. Literal expected strings; offline, deterministic.
"""

import copy
import logging
import os
import sys
from decimal import Decimal
from fractions import Fraction

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from benchmark.judge_report_integrity import (  # noqa: E402
    _CHECK_ROW_KEYS,
    _NUMPY_BOOL_TYPENAMES,
    _REPORT_TALLY,
    _TALLY_KEYS,
    _check_row_field,
    _check_rows_list,
    _dict,
    _expand_slice,
    _expected_disagreement_rate,
    _is_number,
    _is_passed,
    _malformed_per_repo_rows,
    _per_repo_list,
    _report_slices,
    _slice_has_judge_telemetry,
    _stats_dual_order_tasks,
    _tally_counts,
    check_judge_report_integrity,
    failed_checks,
    integrity_headline,
)

_LOGGER = "benchmark.judge_report_integrity"


def _numpy_bool(name):
    cls = type(name, (), {})
    cls.__name__ = name
    return cls()


class _BoolSub(int):
    """A bool-like subclass; `type(...) is bool` is False for it."""


def _named(result):
    return {c["name"]: c for c in result["checks"]}


def _slice(wins=1, losses=2, ties=0, disagree=1, dual=4, rate=0.25, **over):
    s = {
        "tasks": 2,
        "tally": {"challenger": wins, "baseline": losses, "tie": ties},
        "judge_report": {"wins": wins, "losses": losses, "ties": ties,
                         "dual_order_tasks": dual, "disagreements": disagree,
                         "disagreement_rate": rate},
        "judge_order_stats": {"dual_order_tasks": dual, "disagree": disagree},
    }
    s.update(over)
    return s


# --- Constants ---------------------------------------------------------------------------

def test_constants_are_pinned():
    assert _TALLY_KEYS == ("challenger", "baseline", "tie")
    assert _REPORT_TALLY == ("wins", "losses", "ties")
    assert _CHECK_ROW_KEYS == ("name", "passed")
    assert _NUMPY_BOOL_TYPENAMES == frozenset({"bool_", "bool8", "bool"})
    assert set(check_judge_report_integrity(_slice())) == {"passed", "checks"}


# --- Numeric helper ----------------------------------------------------------------------

def test_is_number_accepts_finite_int_float():
    assert _is_number(0) and _is_number(3) and _is_number(0.5) and _is_number(-2)


def test_is_number_rejects_bool_non_finite_oversized():
    assert _is_number(True) is False and _is_number(False) is False
    for bad in (float("nan"), float("inf"), float("-inf")):
        assert _is_number(bad) is False, bad
    assert _is_number(10 ** 400) is False and _is_number(-(10 ** 400)) is False


def test_is_number_rejects_decimal_and_other_numeric_types():
    # The helper is isinstance-based on built-in int/float only; other numeric types are rejected.
    for bad in (Decimal("0.5"), Fraction(1, 2), 1 + 0j, "0.5", None, [1], {}):
        assert _is_number(bad) is False, bad


# --- Verdict helper ----------------------------------------------------------------------

def test_is_passed_bool_and_numpy_typenames():
    assert _is_passed(True) and _is_passed(False)
    for name in ("bool_", "bool8", "bool"):
        stand_in = _numpy_bool(name)
        assert type(stand_in).__name__ == name        # proves it hits the module's branch
        assert _is_passed(stand_in) is True, name


def test_is_passed_rejects_int_and_bool_subclass():
    assert _is_passed(1) is False and _is_passed(0) is False
    assert _is_passed(_BoolSub(1)) is False           # type(...) is bool, not isinstance


# --- Dict / per_repo coercion ------------------------------------------------------------

def test_dict_helper():
    assert _dict({"a": 1}) == {"a": 1}
    for bad in (42, None, "x", [1], True):
        assert _dict(bad) == {}


def test_per_repo_list_none_and_empty_silent(caplog):
    with caplog.at_level(logging.WARNING, logger=_LOGGER):
        assert _per_repo_list(None) == []
        assert _per_repo_list([]) == []
    assert not caplog.records


def test_per_repo_list_warns_on_non_list(caplog):
    with caplog.at_level(logging.WARNING, logger=_LOGGER):
        assert _per_repo_list(42) == []
    assert any("not a list" in r.message for r in caplog.records)


def test_per_repo_list_drops_non_dict_without_per_entry_warning(caplog):
    keep = {"tasks": 1}
    with caplog.at_level(logging.WARNING, logger=_LOGGER):
        assert _per_repo_list([keep, "junk", 7]) == [keep]
    assert not caplog.records          # unlike the check-rows helper, no per-entry warning


# --- Check-row field & sanitation --------------------------------------------------------

def test_check_row_field_semantics():
    assert _check_row_field("name", "ok") is True
    assert _check_row_field("name", "  ") is False and _check_row_field("name", 5) is False
    assert _check_row_field("passed", True) is True and _check_row_field("passed", 1) is False
    assert _check_row_field("other", "x") is False


def test_check_rows_list_none_and_empty_silent(caplog):
    with caplog.at_level(logging.WARNING, logger=_LOGGER):
        assert _check_rows_list(None) == [] and _check_rows_list([]) == []
    assert not caplog.records


def test_check_rows_list_warns_on_non_list(caplog):
    with caplog.at_level(logging.WARNING, logger=_LOGGER):
        assert _check_rows_list(42) == []
    assert any("not a list" in r.message for r in caplog.records)


def test_check_rows_list_skips_and_warns_on_malformed_rows(caplog):
    good = {"name": "ok", "passed": True}
    with caplog.at_level(logging.WARNING, logger=_LOGGER):
        assert _check_rows_list([good, "junk", {"name": "x"}, {"passed": True},
                                 {"name": "", "passed": True},
                                 {"name": "n", "passed": 1}]) == [good]
    msgs = " ".join(r.message for r in caplog.records)
    assert "not an object" in msgs and "missing required key" in msgs and "not a usable" in msgs


def test_check_rows_list_warns_when_no_usable_rows(caplog):
    with caplog.at_level(logging.WARNING, logger=_LOGGER):
        assert _check_rows_list([{"name": "n", "passed": 1}]) == []
    assert any("no usable rows" in r.message for r in caplog.records)


# --- Tally & stats helpers ---------------------------------------------------------------

def test_tally_counts_requires_all_keys_numeric():
    assert _tally_counts({"challenger": 1, "baseline": 2, "tie": 0}) == {
        "challenger": 1, "baseline": 2, "tie": 0}
    assert _tally_counts({"challenger": 1, "baseline": 2}) is None
    assert _tally_counts({"challenger": 1, "baseline": 2, "tie": True}) is None
    assert _tally_counts(42) is None


def test_stats_dual_order_tasks_field_then_sum():
    assert _stats_dual_order_tasks({"dual_order_tasks": 5}) == 5
    assert _stats_dual_order_tasks({"agree": 2, "disagree": 1, "tie": 1}) == 4
    assert _stats_dual_order_tasks({"agree": 2, "disagree": 1}) is None


def test_expected_disagreement_rate():
    assert _expected_disagreement_rate({"dual_order_tasks": 4, "disagree": 2}) == 0.5
    assert _expected_disagreement_rate({"dual_order_tasks": 0, "disagree": 2}) is None
    assert _expected_disagreement_rate({"dual_order_tasks": 4, "disagree": "x"}) is None


# --- Slice detection ---------------------------------------------------------------------

def test_slice_has_judge_telemetry_branches():
    assert _slice_has_judge_telemetry({"tasks": 1}) is True
    assert _slice_has_judge_telemetry({"tasks": 0}) is False
    assert _slice_has_judge_telemetry({"judge_report": {}}) is True
    assert _slice_has_judge_telemetry({"judge_order_stats": {}}) is True
    assert _slice_has_judge_telemetry({"scored_repos": 2}) is True
    assert _slice_has_judge_telemetry({}) is False


def test_expand_slice_per_repo_first():
    # per_repo checked first: an aggregate expands its rows, not itself.
    part = {"judge_report": {}, "per_repo": [{"tasks": 1, "judge_report": {}}]}
    assert _expand_slice("tuned", part) == [("tuned:repo-0", part["per_repo"][0])]
    leaf = {"judge_report": {}}
    assert _expand_slice("run", leaf) == [("run", leaf)]
    assert _expand_slice("run", {}) == []


def test_generalization_and_multi_and_run_slices():
    run = _slice()
    assert _report_slices({"per_repo": [dict(run, tasks=1)]})[0][0] == "repo-0"
    gen = {"tuned": {"judge_report": {}, "tasks": 1}, "held_out": {"judge_report": {}, "tasks": 1},
           "generalization_gap": 0.0}
    labels = [lbl for lbl, _ in _report_slices(gen)]
    assert labels == ["tuned", "held_out"]
    assert _report_slices(run)[0][0] == "run"


def test_no_telemetry_yields_no_slices():
    assert _report_slices({"composite_mean": 0.5}) == []


# --- Per-slice checks --------------------------------------------------------------------

def test_report_and_stats_present():
    ok = _named(check_judge_report_integrity(_slice()))
    assert ok["report_present"]["passed"] and ok["stats_present"]["passed"]
    missing = _named(check_judge_report_integrity(
        {"tasks": 1, "judge_report": None, "judge_order_stats": None}))
    assert missing["report_present"]["passed"] is False
    assert missing["stats_present"]["passed"] is False


def test_tally_matches_and_no_tally_branch():
    ok = _named(check_judge_report_integrity(_slice()))
    assert ok["wins_match_tally"]["passed"] and ok["losses_match_tally"]["passed"]

    mismatch = _slice()
    mismatch["judge_report"]["wins"] = 9          # report disagrees with tally challenger=1
    assert _named(check_judge_report_integrity(mismatch))["wins_match_tally"]["passed"] is False

    no_tally = _slice()
    del no_tally["tally"]
    nt = _named(check_judge_report_integrity(no_tally))
    assert nt["wins_match_tally"]["detail"] == "no tally to compare for wins"
    assert nt["wins_match_tally"]["passed"] is True


def test_dual_disagreements_and_rate_match():
    ok = _named(check_judge_report_integrity(_slice(disagree=1, dual=4, rate=0.25)))
    assert ok["dual_order_tasks_match"]["passed"]
    assert ok["disagreements_match"]["passed"]
    assert ok["disagreement_rate_matches"]["passed"]

    wrong = _named(check_judge_report_integrity(_slice(disagree=1, dual=4, rate=0.9)))
    assert wrong["disagreement_rate_matches"]["passed"] is False


def test_rate_na_branch():
    s = _slice(disagree=0, dual=0, rate=None)
    s["judge_report"]["dual_order_tasks"] = 0
    s["judge_report"]["disagreements"] = 0
    result = _named(check_judge_report_integrity(s))
    assert result["disagreement_rate_matches"]["passed"] is True
    assert result["disagreement_rate_matches"]["detail"] == "no dual-order tasks; rate n/a"


def test_missing_stats_fails_the_three_comparisons():
    s = {"tasks": 1, "judge_report": {"wins": 1}, "judge_order_stats": None}
    result = _named(check_judge_report_integrity(s))
    for name in ("dual_order_tasks_match", "disagreements_match", "disagreement_rate_matches"):
        assert result[name]["passed"] is False
        assert result[name]["detail"] == "cannot compare without judge_order_stats"


# --- per_repo well-formedness ------------------------------------------------------------

def test_malformed_per_repo_string_rows_flagged():
    art = {"per_repo": [dict(_slice(), tasks=1), "CLONE FAILED: boom"]}
    check = _named(check_judge_report_integrity(art))["per_repo_rows_wellformed"]
    assert check["passed"] is False and "repo-1" in check["detail"]


def test_dict_error_row_and_blanks_not_flagged():
    art = {"per_repo": [dict(_slice(), tasks=1), {"error": "too small"}, 7, None, [], "  "]}
    assert _named(check_judge_report_integrity(art))["per_repo_rows_wellformed"]["passed"] is True
    assert _malformed_per_repo_rows(art) == []


def test_no_per_repo_container_omits_check():
    assert _malformed_per_repo_rows({"rows": []}) is None
    assert "per_repo_rows_wellformed" not in _named(check_judge_report_integrity(_slice()))


# --- Top-level result --------------------------------------------------------------------

def test_non_dict_artifact_fails_artifact_shape():
    for bad in (42, None, "x", [1]):
        result = check_judge_report_integrity(bad)
        assert result["passed"] is False
        assert [c["name"] for c in result["checks"]] == ["artifact_shape"]
        assert "artifact must be a JSON object" in result["checks"][0]["detail"]


def test_result_always_carries_passed_and_checks():
    for art in (42, {"composite_mean": 0.5}, _slice()):
        assert set(check_judge_report_integrity(art)) == {"passed", "checks"}
    empty = check_judge_report_integrity({"composite_mean": 0.5})
    assert empty["checks"][0]["detail"] == "no scored replay slice with judge telemetry to verify"


# --- Failed checks and headline ----------------------------------------------------------

def test_failed_checks_names():
    result = {"checks": [{"name": "a", "passed": True}, {"name": "b", "passed": False}]}
    assert failed_checks(result) == ["b"]
    assert failed_checks(42) == []


def test_headline_no_checks():
    assert integrity_headline({"checks": []}) == "judge report integrity: no checks evaluated"
    assert integrity_headline(42) == "judge report integrity: no checks evaluated"
    assert integrity_headline({"checks": 42}) == "judge report integrity: no checks evaluated"


def test_headline_consistent():
    result = {"passed": True, "checks": [{"name": "a", "passed": True}]}
    assert integrity_headline(result) == "judge report integrity: CONSISTENT (1 checks passed)"


def test_headline_inconsistent_lists_failures():
    result = {"passed": False, "checks": [{"name": "a", "passed": True},
                                          {"name": "b", "passed": False}]}
    assert integrity_headline(result) == (
        "judge report integrity: INCONSISTENT (1/2 checks failed: b)")


# --- Pure evaluation ---------------------------------------------------------------------

def test_check_does_not_mutate_artifact():
    art = {"per_repo": [dict(_slice(), tasks=1)]}
    snapshot = copy.deepcopy(art)
    check_judge_report_integrity(art)
    assert art == snapshot
