"""Spec 069 contract tests for benchmark/generalization_gate.py (generalization gate).

Pins the as-built behavior described in specs/069-benchmark-generalization-gate/spec.md with
literal expected values whose ``repr`` is stable across platforms. The imported ``_partition_error``
is exercised through the observable ``no_partition_error`` verdict (its own contract is Spec 072).
Integration / CLI coverage lives in tests/test_generalization_gate.py.
"""

import logging
import math
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from benchmark.generalization_gate import (  # noqa: E402
    _CHECK_ROW_KEYS,
    DEFAULT_MAX_GAP,
    DEFAULT_MIN_HELD_OUT_REPOS,
    _check_rows_list,
    _composite,
    _dict,
    _is_number,
    _num,
    _scored_repos,
    check_generalization,
    failed_checks,
    generalization_headline,
)


def _named(checks):
    return {c["name"]: c for c in checks}


def _partition(composite, repos, tasks_each=2):
    return {"composite_mean": composite, "scored_repos": repos,
            "per_repo": [{"tasks": tasks_each} for _ in range(repos)]}


def _gen(tuned_c, tuned_r, held_c, held_r):
    return {"generalization_gap": round(tuned_c - held_c, 3),
            "tuned": _partition(tuned_c, tuned_r),
            "held_out": _partition(held_c, held_r)}


# --- Constants -----------------------------------------------------------------------------------

def test_constants_are_pinned():
    assert (DEFAULT_MAX_GAP, DEFAULT_MIN_HELD_OUT_REPOS) == (0.1, 3)
    assert _CHECK_ROW_KEYS == ("name", "passed")


# --- Numeric helpers (each edge asserted independently) ------------------------------------------

def test_is_number_accepts_finite():
    assert _is_number(0.6) is True
    assert _is_number(3) is True
    assert _is_number(0) is True


def test_is_number_rejects_bool():
    assert _is_number(True) is False
    assert _is_number(False) is False


def test_is_number_rejects_nan():
    assert _is_number(math.nan) is False


def test_is_number_rejects_inf_and_negative_inf():
    assert _is_number(math.inf) is False
    assert _is_number(-math.inf) is False


def test_is_number_rejects_str():
    assert _is_number("0.6") is False
    assert _is_number(None) is False


def test_is_number_rejects_oversized_int():
    assert _is_number(10 ** 400) is False


def test_num_formats_or_na():
    assert _num(0.5) == "0.500"
    assert _num(None) == "n/a"
    assert _num(math.nan) == "n/a"


def test_dict_helper():
    d = {"a": 1}
    assert _dict(d) is d
    for bad in (None, 5, "x", [1]):
        assert _dict(bad) == {}


# --- Composite -----------------------------------------------------------------------------------

def test_composite_masks_unscored_placeholder():
    assert _composite({"composite_mean": 0.0, "scored_repos": 0}) is None
    assert _composite({"composite_mean": 0.6, "scored_repos": 3}) == 0.6


def test_composite_keeps_genuine_zero():
    assert _composite({"composite_mean": 0.0}) == 0.0          # no scored_repos key


def test_composite_non_finite_is_none():
    assert _composite({"composite_mean": float("inf"), "scored_repos": 3}) is None
    assert _composite({"composite_mean": "x"}) is None
    assert _composite("not-a-dict") is None


# --- Held-out repo count -------------------------------------------------------------------------

def test_scored_repos_prefers_count():
    assert _scored_repos({"scored_repos": 4}) == 4


def test_scored_repos_per_repo_fallback():
    # 3 entries, one skipped (tasks == 0) -> 2 scored; an entry with no tasks is still counted.
    assert _scored_repos({"per_repo": [{"tasks": 2}, {"tasks": 0}, {"tasks": 1}]}) == 2
    assert _scored_repos({"per_repo": [{"tasks": 2}, {"repo": "x"}]}) == 2


def test_scored_repos_non_list_is_none():
    assert _scored_repos({"per_repo": "nope"}) is None
    assert _scored_repos({}) is None


# --- Gate ----------------------------------------------------------------------------------------

_RESULT_KEYS = {"passed", "checks", "tuned_composite", "held_out_composite", "gap",
                "held_out_repos", "max_gap", "min_held_out_repos"}


def test_result_carries_all_keys():
    assert set(check_generalization(_gen(0.65, 3, 0.60, 3))) == _RESULT_KEYS


def test_generalizes_passes_all_checks():
    result = check_generalization(_gen(0.65, 3, 0.60, 3))   # gap 0.05 <= 0.1, 3 held-out repos
    assert result["passed"] is True
    assert [c["name"] for c in result["checks"]] == [
        "has_partitions", "no_partition_error", "enough_held_out_repos", "gap_within_tolerance"]
    assert result["gap"] == 0.05 and result["held_out_repos"] == 3
    assert _named(result["checks"])["gap_within_tolerance"]["detail"] == "tuned - held-out = 0.050 <= 0.1"


def test_overfit_gap_exceeds_tolerance():
    result = check_generalization(_gen(0.70, 3, 0.40, 3))   # gap 0.30 > 0.1
    checks = _named(result["checks"])
    assert result["gap"] == 0.3
    assert checks["gap_within_tolerance"]["passed"] is False
    assert result["passed"] is False


def test_missing_partition_fails_has_partitions():
    result = check_generalization({"tuned": _partition(0.65, 3),
                                   "held_out": {"composite_mean": 0.0, "scored_repos": 0}})
    checks = _named(result["checks"])
    assert checks["has_partitions"]["passed"] is False
    assert checks["has_partitions"]["detail"] == (
        "a composite is missing from the tuned or held-out partition")
    assert result["gap"] is None
    assert checks["gap_within_tolerance"]["detail"] == "cannot compare the partitions"


def test_partition_error_fails_no_partition_error():
    result = check_generalization({
        "tuned": _partition(0.65, 3),
        "held_out": {"composite_mean": 0.6, "scored_repos": 3,
                     "per_repo": [{"error": "clone failed"}]}})
    checks = _named(result["checks"])
    assert checks["no_partition_error"]["passed"] is False
    assert "partition error(s):" in checks["no_partition_error"]["detail"]


def test_too_few_held_out_repos_fails():
    result = check_generalization(_gen(0.65, 3, 0.60, 2))   # 2 held-out repos < 3
    checks = _named(result["checks"])
    assert checks["enough_held_out_repos"]["passed"] is False
    assert checks["enough_held_out_repos"]["detail"] == "2 held-out repo(s) >= 3"


def test_held_out_exceeding_tuned_is_within_tolerance():
    result = check_generalization(_gen(0.60, 3, 0.65, 3))
    checks = _named(result["checks"])
    assert result["gap"] == -0.05
    assert checks["gap_within_tolerance"]["passed"] is True


# --- Checks-row sanitation -----------------------------------------------------------------------

def test_check_rows_list_warns_on_non_list_checks(caplog):
    with caplog.at_level(logging.WARNING, logger="benchmark.generalization_gate"):
        assert _check_rows_list(42) == []
    assert any(
        r.message == "generalization: checks is int, not a list; treating as empty"
        for r in caplog.records
    )
    caplog.clear()
    with caplog.at_level(logging.WARNING, logger="benchmark.generalization_gate"):
        assert _check_rows_list(None) == []
    assert caplog.records == []                       # a None checks key is silent


def test_check_rows_list_skips_malformed_rows():
    result = {"checks": [
        {"name": "has_partitions", "passed": True},
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
    with caplog.at_level(logging.WARNING, logger="benchmark.generalization_gate"):
        assert _check_rows_list([{"name": "a"}]) == []
    assert any("no usable rows" in r.message for r in caplog.records)


# --- Failed checks and headline ------------------------------------------------------------------

def test_failed_checks_names():
    result = {"checks": [{"name": "gap_within_tolerance", "passed": False},
                         {"name": "has_partitions", "passed": True}]}
    assert failed_checks(result) == ["gap_within_tolerance"]


def test_headline_no_checks():
    assert generalization_headline({"checks": []}) == "generalization: no checks evaluated"
    assert generalization_headline({}) == "generalization: no checks evaluated"
    assert generalization_headline("nope") == "generalization: no checks evaluated"


def test_headline_generalizes():
    result = check_generalization(_gen(0.65, 3, 0.60, 3))
    assert generalization_headline(result) == (
        "generalization: GENERALIZES (tuned 0.650 -> held-out 0.600, gap 0.050)")


def test_headline_overfit_lists_failures():
    result = check_generalization(_gen(0.70, 3, 0.40, 3))
    line = generalization_headline(result)
    assert line.startswith("generalization: OVERFIT (")
    assert "gap_within_tolerance" in line


# --- Pure evaluation -----------------------------------------------------------------------------

def test_check_does_not_mutate_artifact():
    import copy
    artifact = _gen(0.65, 3, 0.60, 3)
    snapshot = copy.deepcopy(artifact)
    check_generalization(artifact)
    assert artifact == snapshot
