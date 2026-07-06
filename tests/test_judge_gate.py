"""Tests for the pairwise-judge robustness gate (deterministic, offline)."""

import copy
import logging
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from benchmark.judge_gate import (  # noqa: E402
    DEFAULT_MAX_DISAGREEMENT,
    _check_rows_list,
    check_judge,
    failed_checks,
    judge_headline,
)


def _result(dual_order=True, dual_tasks=5, disagreement=0.1, stats_tasks=None):
    r = {
        "judge_dual_order": dual_order,
        "judge_report": {"disagreement_rate": disagreement, "dual_order_tasks": dual_tasks},
    }
    if stats_tasks is not None:
        r["judge_order_stats"] = {"dual_order_tasks": stats_tasks}
    return r


def _names(result):
    return [c["name"] for c in result["checks"]]


def test_a_robust_run_passes():
    result = check_judge(_result(dual_order=True, dual_tasks=5, disagreement=0.1))
    assert result["passed"] is True
    assert _names(result) == ["dual_order_judging", "enough_dual_order_tasks", "low_disagreement"]
    assert result["dual_order"] is True and result["dual_order_tasks"] == 5
    assert result["disagreement_rate"] == 0.1


def test_single_order_run_fails_dual_order_check():
    result = check_judge(_result(dual_order=False))
    assert result["passed"] is False
    assert "dual_order_judging" in failed_checks(result)


def test_high_disagreement_is_shaky():
    result = check_judge(_result(disagreement=0.5), max_disagreement=0.3)
    assert result["passed"] is False
    assert failed_checks(result) == ["low_disagreement"]


def test_too_few_dual_order_tasks_fails():
    result = check_judge(_result(dual_tasks=1), min_dual_order_tasks=2)
    assert result["passed"] is False
    assert "enough_dual_order_tasks" in failed_checks(result)


def test_dual_order_tasks_falls_back_to_judge_order_stats():
    # judge_report lacks the count; it is read from judge_order_stats instead.
    r = {"judge_dual_order": True, "judge_report": {"disagreement_rate": 0.1},
         "judge_order_stats": {"dual_order_tasks": 4}}
    result = check_judge(r)
    assert result["dual_order_tasks"] == 4 and result["passed"] is True


def test_disagreement_bound_is_inclusive():
    assert check_judge(_result(disagreement=0.3), max_disagreement=0.3)["passed"] is True
    assert check_judge(_result(disagreement=0.31), max_disagreement=0.3)["passed"] is False


def test_thresholds_are_configurable():
    run = _result(dual_tasks=3, disagreement=0.25)
    assert check_judge(run, max_disagreement=0.3, min_dual_order_tasks=3)["passed"] is True
    assert check_judge(run, max_disagreement=0.2)["passed"] is False
    assert check_judge(run, min_dual_order_tasks=4)["passed"] is False


def test_missing_disagreement_rate_fails_low_disagreement():
    r = {"judge_dual_order": True, "judge_report": {"dual_order_tasks": 5}}
    result = check_judge(r)
    assert "low_disagreement" in failed_checks(result)
    assert result["disagreement_rate"] is None


def test_malformed_or_non_dict_result_fails_gracefully():
    for bad in (None, "not a dict", 42, [1, 2]):
        result = check_judge(bad)
        assert result["passed"] is False
        assert result["checks"]
        assert result["dual_order"] is False and result["dual_order_tasks"] is None


def test_non_numeric_fields_do_not_crash():
    weird = {"judge_dual_order": "yes", "judge_report": {"disagreement_rate": "low",
             "dual_order_tasks": "many"}}
    result = check_judge(weird)
    assert result["passed"] is False
    assert set(failed_checks(result)) == {
        "dual_order_judging", "enough_dual_order_tasks", "low_disagreement",
    }


def test_headline_reports_robust_and_shaky():
    assert "ROBUST" in judge_headline(check_judge(_result()))
    shaky = judge_headline(check_judge(_result(disagreement=0.9)))
    assert "SHAKY" in shaky and "low_disagreement" in shaky
    assert judge_headline({}) == "judge: no checks evaluated"
    assert DEFAULT_MAX_DISAGREEMENT == 0.3


# --- #656: checks row sanitization for judge gate headlines -----------------------------

_MALFORMED_CHECKS = [
    42, 3.14, True, {"name": "dual_order_judging"}, "not a list",
    ({"name": "dual_order_judging", "passed": False},),  # tuple, not list
    range(2),  # iterable but not a list
]


def test_check_rows_list_accepts_only_real_lists():
    rows = [{"name": "dual_order_judging", "passed": True}]
    for bad in _MALFORMED_CHECKS:
        assert _check_rows_list(bad) == [], bad
    assert _check_rows_list(rows) == rows
    assert _check_rows_list(None) == []
    assert _check_rows_list([]) == []


def test_check_rows_list_missing_key_emits_no_warning(caplog):
    with caplog.at_level(logging.WARNING, logger="benchmark.judge_gate"):
        assert _check_rows_list(None) == []
    assert not caplog.records


def test_check_rows_list_empty_list_emits_no_warning(caplog):
    with caplog.at_level(logging.WARNING, logger="benchmark.judge_gate"):
        assert _check_rows_list([]) == []
    assert not caplog.records


def test_check_rows_list_warns_for_tuple_container(caplog):
    row = ({"name": "dual_order_judging", "passed": False},)
    with caplog.at_level(logging.WARNING, logger="benchmark.judge_gate"):
        assert _check_rows_list(row) == []
    assert any("checks is tuple" in r.message for r in caplog.records)


def test_check_rows_list_warns_for_skipped_rows(caplog):
    mixed = [42, {"name": "dual_order_judging", "passed": True}]
    with caplog.at_level(logging.WARNING, logger="benchmark.judge_gate"):
        assert len(_check_rows_list(mixed)) == 1
    assert any("checks[0] is int" in r.message for r in caplog.records)
    assert not any("no usable rows" in r.message for r in caplog.records)


def test_check_rows_list_warns_when_every_entry_is_unusable(caplog):
    junk = [42, "bad", None]
    with caplog.at_level(logging.WARNING, logger="benchmark.judge_gate"):
        assert _check_rows_list(junk) == []
    messages = [r.message for r in caplog.records]
    assert any("checks[0] is int" in m for m in messages)
    assert any("no usable rows" in m for m in messages)


def test_check_rows_list_skips_row_missing_name(caplog):
    with caplog.at_level(logging.WARNING, logger="benchmark.judge_gate"):
        assert _check_rows_list([{"passed": False}]) == []
    assert any("missing required key(s) ['name']" in r.message for r in caplog.records)


def test_check_rows_list_skips_row_missing_passed(caplog):
    with caplog.at_level(logging.WARNING, logger="benchmark.judge_gate"):
        assert _check_rows_list([{"name": "dual_order_judging"}]) == []
    assert any("missing required key(s) ['passed']" in r.message for r in caplog.records)


def test_check_rows_list_skips_empty_dict(caplog):
    with caplog.at_level(logging.WARNING, logger="benchmark.judge_gate"):
        assert _check_rows_list([{}]) == []
    assert any("missing required key(s)" in r.message for r in caplog.records)


def test_judge_headline_survives_non_list_checks():
    base = {"passed": False, "dual_order_tasks": 0, "disagreement_rate": 0.5}
    for bad in _MALFORMED_CHECKS:
        assert judge_headline({**base, "checks": bad}) == "judge: no checks evaluated", bad


def test_judge_headline_survives_rows_missing_required_keys():
    for checks in (
        [{"passed": False}],
        [{"name": "dual_order_judging"}],
        [{}],
    ):
        assert judge_headline({"checks": checks, "passed": False}) == "judge: no checks evaluated"


def test_judge_headline_uses_sanitized_row_count(caplog):
    checks = [{"name": "dual_order_judging", "passed": False}, 42]
    with caplog.at_level(logging.WARNING, logger="benchmark.judge_gate"):
        line = judge_headline({"checks": checks, "passed": False})
    assert line == "judge: SHAKY (1/1 checks failed: dual_order_judging)"
    assert any("checks[1] is int" in r.message for r in caplog.records)


def test_judge_headline_logs_warning_for_non_list_checks(caplog):
    with caplog.at_level(logging.WARNING, logger="benchmark.judge_gate"):
        line = judge_headline({"checks": 42, "passed": False})
    assert line == "judge: no checks evaluated"
    assert any("checks is int" in r.message for r in caplog.records)


def test_failed_checks_survives_non_list_checks():
    for bad in _MALFORMED_CHECKS:
        assert failed_checks({"checks": bad}) == [], bad


def test_failed_checks_never_raises_on_malformed_rows():
    for checks in (
        [{"passed": False}],
        [{"name": "dual_order_judging"}],
        [{}],
        [42],
    ):
        assert failed_checks({"checks": checks}) == []


def test_failed_checks_skips_non_dict_rows():
    checks = [
        {"name": "dual_order_judging", "passed": False},
        42,
        {"name": "low_disagreement", "passed": True},
    ]
    assert failed_checks({"checks": checks}) == ["dual_order_judging"]


def test_every_check_reported_even_when_all_fail():
    result = check_judge({"judge_dual_order": False, "judge_report": {"disagreement_rate": 0.9}})
    assert len(result["checks"]) == 3
    assert set(failed_checks(result)) == {
        "dual_order_judging", "enough_dual_order_tasks", "low_disagreement",
    }


def test_judge_report_dual_order_tasks_preferred_over_stats():
    # When both sources carry the count, judge_report (the canonical summary) wins.
    r = {"judge_dual_order": True,
         "judge_report": {"disagreement_rate": 0.1, "dual_order_tasks": 6},
         "judge_order_stats": {"dual_order_tasks": 99}}
    assert check_judge(r)["dual_order_tasks"] == 6


def test_a_realistic_shaky_run_names_all_failures():
    # Single-order, one task, high disagreement: every criterion fails and is reported.
    r = {"judge_dual_order": False,
         "judge_report": {"disagreement_rate": 0.6, "dual_order_tasks": 1}}
    result = check_judge(r, max_disagreement=0.3, min_dual_order_tasks=2)
    assert result["passed"] is False
    assert set(failed_checks(result)) == {
        "dual_order_judging", "enough_dual_order_tasks", "low_disagreement",
    }
    assert "SHAKY" in judge_headline(result)


def test_check_judge_does_not_mutate_the_result():
    run = _result()
    snapshot = copy.deepcopy(run)
    check_judge(run)
    assert run == snapshot
