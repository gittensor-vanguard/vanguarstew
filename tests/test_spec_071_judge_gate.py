"""Spec 071 contract tests for benchmark/judge_gate.py (judge robustness gate).

Pins the as-built behavior described in specs/071-benchmark-judge-gate/spec.md with literal
expected check names, ``passed`` values and detail strings, using values whose ``repr`` is stable
across platforms. Integration / CLI coverage lives in tests/test_judge_gate.py.
"""

import logging
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from benchmark.judge_gate import (  # noqa: E402
    _CHECK_ROW_KEYS,
    DEFAULT_MAX_DISAGREEMENT,
    DEFAULT_MIN_DUAL_ORDER_TASKS,
    _check_row_field,
    _dict,
    _disagreement_rate,
    _disagreement_rate_from_telemetry,
    _dual_order_tasks,
    _is_int,
    _is_number,
    _is_passed,
    _judge_source,
    check_judge,
    failed_checks,
    judge_headline,
)


def _named(checks):
    return {c["name"]: c for c in checks}


def _robust(dual_tasks=5, disagree=1):
    return {"judge_dual_order": True,
            "judge_order_stats": {"dual_order_tasks": dual_tasks, "disagree": disagree}}


# --- Constants -----------------------------------------------------------------------------------

def test_constants_are_pinned():
    assert (DEFAULT_MAX_DISAGREEMENT, DEFAULT_MIN_DUAL_ORDER_TASKS) == (0.3, 2)
    assert _CHECK_ROW_KEYS == ("name", "passed")


# --- Numeric / type helpers ----------------------------------------------------------------------

def test_is_number_semantics():
    assert _is_number(3) is True
    assert _is_number(0.2) is True
    assert _is_number(True) is False
    assert _is_number(float("nan")) is False
    assert _is_number(float("inf")) is False
    assert _is_number("3") is False


def test_is_number_rejects_oversized_int():
    assert _is_number(10 ** 400) is False


def test_is_int_semantics():
    assert _is_int(3) is True
    assert _is_int(True) is False
    assert _is_int(3.0) is False


def test_dict_helper():
    d = {"a": 1}
    assert _dict(d) is d
    for bad in (None, 5, "x", [1]):
        assert _dict(bad) == {}


def test_is_passed_accepts_bool_rejects_int():
    assert _is_passed(True) is True
    assert _is_passed(False) is True
    assert _is_passed(1) is False
    assert _is_passed(0) is False


def test_check_row_field():
    assert _check_row_field("name", "dual_order_judging") is True
    assert _check_row_field("name", "") is False
    assert _check_row_field("name", 7) is False
    assert _check_row_field("passed", True) is True
    assert _check_row_field("passed", 1) is False


# --- Dual-order task count -----------------------------------------------------------------------

def test_dual_order_tasks_prefers_report_then_stats():
    assert _dual_order_tasks({"judge_report": {"dual_order_tasks": 6},
                              "judge_order_stats": {"dual_order_tasks": 3}}) == 6
    assert _dual_order_tasks({"judge_order_stats": {"dual_order_tasks": 3}}) == 3
    assert _dual_order_tasks({"judge_report": {"dual_order_tasks": float("inf")}}) is None
    assert _dual_order_tasks({}) is None


# --- Disagreement rate ---------------------------------------------------------------------------

def test_rate_from_coherent_counts():
    assert _disagreement_rate_from_telemetry({"dual_order_tasks": 5, "disagree": 1}) == 0.2


def test_rate_derives_dual_from_agree_disagree_tie():
    # no dual_order_tasks -> dual = agree + disagree + tie = 5; 1/5 = 0.2
    assert _disagreement_rate_from_telemetry({"agree": 3, "disagree": 1, "tie": 1}) == 0.2


def test_rate_incoherent_pair_falls_back_to_stored():
    # disagree (5) > dual (4) is incoherent -> no recompute; stored rate used, else None.
    assert _disagreement_rate_from_telemetry({"dual_order_tasks": 4, "disagree": 5}) is None
    assert _disagreement_rate_from_telemetry(
        {"dual_order_tasks": 4, "disagree": 5, "disagreement_rate": 0.9}) == 0.9
    # no counts at all -> stored rate.
    assert _disagreement_rate_from_telemetry({"disagreement_rate": 0.25}) == 0.25


def test_rate_prefers_order_stats_over_report():
    source = {"judge_order_stats": {"dual_order_tasks": 5, "disagree": 1},
              "judge_report": {"disagreement_rate": 0.9}}
    assert _disagreement_rate(source) == 0.2   # authoritative order_stats wins over stale report


# --- Evaluated partition -------------------------------------------------------------------------

def test_judge_source_generalization_vs_top_level():
    gen = {"tuned": {"judge_dual_order": True}, "held_out": {"judge_dual_order": False}}
    assert _judge_source(gen) is gen["tuned"]
    top = {"judge_dual_order": True, "tuned": {"judge_dual_order": True}}   # no held_out dict
    assert _judge_source(top) is top


# --- Gate ----------------------------------------------------------------------------------------

_RESULT_KEYS = {"passed", "checks", "dual_order", "dual_order_tasks", "disagreement_rate",
                "max_disagreement", "min_dual_order_tasks"}


def test_result_carries_all_keys():
    assert set(check_judge(_robust())) == _RESULT_KEYS


def test_robust_run_passes_all():
    result = check_judge(_robust(5, 1))     # dual-order, 5 tasks, disagreement 0.2
    assert result["passed"] is True
    assert [c["name"] for c in result["checks"]] == [
        "dual_order_judging", "enough_dual_order_tasks", "low_disagreement"]
    assert result["dual_order"] is True
    assert result["dual_order_tasks"] == 5
    assert result["disagreement_rate"] == 0.2
    assert _named(result["checks"])["low_disagreement"]["detail"] == "disagreement_rate 0.2 <= 0.3"


def test_derived_dual_order_from_task_count():
    # multi-repo aggregate: no judge_dual_order flag; derived from pooled dual_order_tasks > 0.
    result = check_judge({"judge_report": {"dual_order_tasks": 4, "disagree": 1}})
    checks = _named(result["checks"])
    assert result["dual_order"] is True
    assert checks["dual_order_judging"]["passed"] is True
    assert result["disagreement_rate"] == 0.25


def test_not_dual_order_fails_closed():
    result = check_judge({})     # no flag, no count
    checks = _named(result["checks"])
    assert result["dual_order"] is False
    assert checks["dual_order_judging"]["passed"] is False
    assert checks["dual_order_judging"]["detail"] == (
        "not dual-order judged (judge_dual_order=None, dual_order_tasks=None)")


def test_too_few_tasks_fails():
    result = check_judge(_robust(1, 0))     # 1 dual-order task < min 2
    checks = _named(result["checks"])
    assert checks["enough_dual_order_tasks"]["passed"] is False
    assert checks["enough_dual_order_tasks"]["detail"] == "1 dual-order task(s) (min 2)"


def test_high_disagreement_fails():
    result = check_judge(_robust(5, 3))     # 3/5 = 0.6 > 0.3
    checks = _named(result["checks"])
    assert result["disagreement_rate"] == 0.6
    assert checks["low_disagreement"]["passed"] is False


def test_non_finite_task_count_fails_closed():
    # inf dual_order_tasks must not clear enough_dual_order_tasks (inf >= min).
    result = check_judge({"judge_dual_order": True,
                          "judge_order_stats": {"dual_order_tasks": float("inf")}})
    checks = _named(result["checks"])
    assert result["dual_order_tasks"] is None
    assert checks["enough_dual_order_tasks"]["passed"] is False
    assert checks["enough_dual_order_tasks"]["detail"] == "dual-order task count unavailable"


def test_non_dict_result_fails_not_raises():
    result = check_judge("not-a-dict")
    assert result["passed"] is False
    assert result["dual_order"] is False


# --- Checks-row sanitation -----------------------------------------------------------------------

def test_check_rows_list_skips_malformed_rows():
    result = {"checks": [
        {"name": "dual_order_judging", "passed": True},
        "not-a-dict",
        {"name": "x"},                       # missing passed
        {"passed": True},                    # missing name
        {"name": 7, "passed": True},         # non-str name
    ]}
    assert failed_checks(result) == []       # only the first survives and it passed


def test_check_rows_list_rejects_non_bool_passed():
    result = {"checks": [{"name": "a", "passed": 1}, {"name": "b", "passed": False}]}
    assert failed_checks(result) == ["b"]    # int passed rejected; only b survives, and it failed


def test_check_rows_list_warns_when_all_unusable(caplog):
    with caplog.at_level(logging.WARNING, logger="benchmark.judge_gate"):
        assert failed_checks({"checks": [{"name": "a"}]}) == []
    assert any("no usable rows" in r.message for r in caplog.records)


# --- Failed checks and headline ------------------------------------------------------------------

def test_failed_checks_names():
    result = {"checks": [{"name": "low_disagreement", "passed": False},
                         {"name": "dual_order_judging", "passed": True}]}
    assert failed_checks(result) == ["low_disagreement"]


def test_headline_no_checks():
    assert judge_headline({"checks": []}) == "judge: no checks evaluated"
    assert judge_headline({}) == "judge: no checks evaluated"
    assert judge_headline("nope") == "judge: no checks evaluated"


def test_headline_robust():
    result = check_judge(_robust(5, 1))
    assert judge_headline(result) == "judge: ROBUST (dual-order, 5 tasks, disagreement 0.2)"


def test_headline_shaky_lists_failures():
    result = check_judge(_robust(5, 3))     # high disagreement
    line = judge_headline(result)
    assert line.startswith("judge: SHAKY (")
    assert "low_disagreement" in line


# --- Pure evaluation -----------------------------------------------------------------------------

def test_check_does_not_mutate_result():
    import copy
    artifact = {"tuned": _robust(5, 1), "held_out": _robust(4, 1)}
    snapshot = copy.deepcopy(artifact)
    check_judge(artifact)
    assert artifact == snapshot
