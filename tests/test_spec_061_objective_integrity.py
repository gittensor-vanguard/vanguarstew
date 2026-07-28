"""Contract tests for specs/061-benchmark-objective-integrity — assert objective_integrity.py
satisfies the spec's EARS criteria, including constants, malformed rows, empty slices, detail
truncation, per_repo well-formedness, every headline branch, and pure evaluation.

Anchor expectations are pinned as LITERAL values rather than re-derived from
score.objective_component, so a silent anchor change is caught here. Offline, deterministic.
"""

import copy
import logging
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from benchmark.objective_integrity import (  # noqa: E402
    _CHECK_ROW_KEYS,
    _RECALL_KEYS,
    DEFAULT_TOLERANCE,
    _check_rows_list,
    _dict,
    _is_number,
    _is_ratio,
    _malformed_per_repo_rows,
    _mean,
    _per_repo_list,
    _round3,
    _rows_list,
    check_objective_integrity,
    failed_checks,
    integrity_headline,
)


def _row(recall=0.5, **objective_extra):
    """A row whose objective_component is the LITERAL `recall` (module recall is the only axis)."""
    objective = {"module_recall": recall}
    objective.update(objective_extra)
    return {"objective": objective}


def _run(rows=None, objective_mean=0.5, **extra):
    result = {
        "rows": rows if rows is not None else [_row(0.5)],
        "composite_parts": {"objective_mean": objective_mean},
    }
    result.update(extra)
    return result


def _named(result):
    return {c["name"]: c for c in result["checks"]}


# --- Constants ---------------------------------------------------------------------------

def test_constants_are_pinned():
    assert DEFAULT_TOLERANCE == 0.002
    assert _RECALL_KEYS == ("weighted_module_recall", "module_recall")
    assert _CHECK_ROW_KEYS == ("name", "passed")


# --- Numeric helpers ---------------------------------------------------------------------

def test_is_number_semantics():
    assert _is_number(0.5) and _is_number(0) and _is_number(3)
    assert not _is_number(True) and not _is_number(False)
    assert not _is_number("0.5") and not _is_number(None) and not _is_number([1])
    assert not _is_number(float("nan")) and not _is_number(float("inf"))


def test_is_number_rejects_oversized_int():
    # math.isfinite raises OverflowError on an int too large to convert to float.
    assert _is_number(10 ** 400) is False


def test_is_ratio_bounds():
    assert _is_ratio(0.0) and _is_ratio(1.0) and _is_ratio(0.5)
    assert not _is_ratio(-0.01) and not _is_ratio(1.01)
    assert not _is_ratio(True) and not _is_ratio(float("nan"))


def test_dict_helper_returns_dict_or_empty():
    assert _dict({"a": 1}) == {"a": 1}
    for bad in (42, None, "x", [1], True):
        assert _dict(bad) == {}


def test_round3_and_mean():
    assert _round3(0.12345) == 0.123
    assert _round3("x") is None and _round3(True) is None
    assert _mean([]) is None
    assert _mean([0.2, 0.4]) == 0.3


# --- Row / per_repo coercion -------------------------------------------------------------

def test_rows_list_coerces_none_non_list_and_non_dict_rows(caplog):
    assert _rows_list(None) == []
    with caplog.at_level(logging.WARNING, logger="benchmark.objective_integrity"):
        assert _rows_list(42) == []
    assert any("not a list" in r.message for r in caplog.records)
    keep = {"objective": {}}
    with caplog.at_level(logging.WARNING, logger="benchmark.objective_integrity"):
        assert _rows_list([keep, "junk", 7]) == [keep]


def test_per_repo_list_coercion():
    assert _per_repo_list(None) == []
    assert _per_repo_list(42) == []
    entry = {"tasks": 1}
    assert _per_repo_list([entry, "junk", 3]) == [entry]


# --- Slice selection ---------------------------------------------------------------------

def test_single_repo_rows_slice_is_unprefixed():
    names = _named(check_objective_integrity(_run()))
    assert "rows_present" in names           # label "run" -> no prefix
    assert not any(n.startswith("run:") for n in names)


def test_multi_repo_slices_are_labelled():
    art = {"per_repo": [
        {"tasks": 2, "rows": [_row(0.5)], "composite_parts": {"objective_mean": 0.5}},
        {"tasks": 0, "rows": [_row(0.5)]},          # zero tasks -> not a slice
        {"tasks": 2, "rows": None},                  # no rows -> not a slice
    ]}
    names = _named(check_objective_integrity(art))
    assert "repo-0:rows_present" in names
    assert not any(n.startswith("repo-1") or n.startswith("repo-2") for n in names)


def test_generalization_slices_are_partition_labelled():
    part = {"rows": [_row(0.5)], "composite_parts": {"objective_mean": 0.5}}
    art = {"tuned": dict(part), "held_out": dict(part), "generalization_gap": 0.0}
    names = _named(check_objective_integrity(art))
    assert "tuned:rows_present" in names and "held_out:rows_present" in names


def test_no_scored_slice_reports_artifact_shape():
    result = check_objective_integrity({"composite_mean": 0.5})
    assert result["passed"] is False
    assert _named(result)["artifact_shape"]["detail"] == (
        "no scored replay slice with per-task rows to verify")


# --- Per-slice checks --------------------------------------------------------------------

def test_rows_present_and_objectives_present():
    ok = _named(check_objective_integrity(_run()))
    assert ok["rows_present"]["passed"] is True
    assert ok["rows_present"]["detail"] == "1 usable row(s)"
    assert ok["objectives_present"]["passed"] is True

    bad = _named(check_objective_integrity(_run(rows=[{"objective": 42}, _row(0.5)])))
    assert bad["objectives_present"]["passed"] is False
    assert bad["objectives_present"]["detail"] == "1 row(s) missing a dict objective"


def test_recall_fields_valid_flags_bool_and_out_of_range():
    boolean = _named(check_objective_integrity(
        _run(rows=[{"objective": {"weighted_module_recall": True}}])))
    assert boolean["recall_fields_valid"]["passed"] is False
    assert "weighted_module_recall is bool" in boolean["recall_fields_valid"]["detail"]

    over = _named(check_objective_integrity(_run(rows=[_row(1.5)])))
    assert over["recall_fields_valid"]["passed"] is False
    assert "is not a ratio in [0, 1]" in over["recall_fields_valid"]["detail"]


def test_recall_absent_keys_are_ignored():
    # An objective with neither recall key present reports no recall problem.
    ok = _named(check_objective_integrity(
        _run(rows=[{"objective": {"actual_kinds": []}}], objective_mean=0.0)))
    assert ok["recall_fields_valid"]["passed"] is True
    assert ok["recall_fields_valid"]["detail"] == "all recall fields are finite ratios in [0, 1]"


def test_kind_recall_only_when_actual_kinds():
    # actual_kinds falsy -> kind_recall never inspected, even when it is junk.
    ignored = _named(check_objective_integrity(
        _run(rows=[_row(0.5, actual_kinds=[], kind_recall="junk")])))
    assert ignored["kind_recall_valid"]["passed"] is True

    flagged = _named(check_objective_integrity(
        _run(rows=[_row(0.5, actual_kinds=["feat"], kind_recall=True)])))
    assert flagged["kind_recall_valid"]["passed"] is False
    assert "kind_recall is bool" in flagged["kind_recall_valid"]["detail"]


def test_objective_mean_matches_rows_within_tolerance():
    # LITERAL pin: a single row of module_recall 0.5 fixes the row mean at 0.5.
    ok = _named(check_objective_integrity(_run(objective_mean=0.5)))
    assert ok["objective_mean_matches_rows"]["passed"] is True
    # Just inside the default tolerance (0.002).
    assert _named(check_objective_integrity(
        _run(objective_mean=0.502)))["objective_mean_matches_rows"]["passed"] is True
    # Outside it.
    off = _named(check_objective_integrity(_run(objective_mean=0.9)))
    assert off["objective_mean_matches_rows"]["passed"] is False
    assert "objective_mean 0.9 vs row mean 0.5" in off["objective_mean_matches_rows"]["detail"]


def test_objective_mean_unavailable_fails_closed():
    missing = _named(check_objective_integrity({"rows": [_row(0.5)]}))
    assert missing["objective_mean_matches_rows"]["passed"] is False
    assert missing["objective_mean_matches_rows"]["detail"] == (
        "cannot compare objective_mean to row objective components")


# --- Detail truncation -------------------------------------------------------------------

def test_recall_detail_truncates_after_three_with_ellipsis():
    rows = [_row(1.5) for _ in range(4)]
    detail = _named(check_objective_integrity(_run(rows=rows)))["recall_fields_valid"]["detail"]
    assert detail.count("row[") == 3 and detail.endswith(" ...")


def test_kind_recall_detail_truncates_after_three_without_ellipsis():
    rows = [_row(0.5, actual_kinds=["feat"], kind_recall=True) for _ in range(4)]
    detail = _named(check_objective_integrity(_run(rows=rows)))["kind_recall_valid"]["detail"]
    assert detail.count("row[") == 3 and not detail.endswith(" ...")


# --- per_repo well-formedness ------------------------------------------------------------

def test_malformed_per_repo_string_rows_flagged():
    art = {"per_repo": [
        {"tasks": 1, "rows": [_row(0.5)], "composite_parts": {"objective_mean": 0.5}},
        "CLONE FAILED: boom",
    ]}
    check = _named(check_objective_integrity(art))["per_repo_rows_wellformed"]
    assert check["passed"] is False
    assert "repo-1" in check["detail"]


def test_per_repo_dict_error_row_not_flagged():
    # A dict row carrying its own error is an unscored repo, not an objective inconsistency;
    # ints / None / lists / empty strings stay ignored too.
    art = {"per_repo": [
        {"tasks": 1, "rows": [_row(0.5)], "composite_parts": {"objective_mean": 0.5}},
        {"error": "too small"}, 7, None, [], "   ",
    ]}
    assert _named(check_objective_integrity(art))["per_repo_rows_wellformed"]["passed"] is True
    assert _malformed_per_repo_rows(art) == []


def test_no_per_repo_container_omits_wellformed_check():
    assert _malformed_per_repo_rows({"rows": []}) is None
    assert "per_repo_rows_wellformed" not in _named(check_objective_integrity(_run()))


# --- Top-level result --------------------------------------------------------------------

def test_non_dict_artifact_fails_artifact_shape():
    for bad in (42, None, "x", [1]):
        result = check_objective_integrity(bad)
        assert result["passed"] is False
        assert [c["name"] for c in result["checks"]] == ["artifact_shape"]
        assert "artifact must be a JSON object" in result["checks"][0]["detail"]


def test_result_always_carries_passed_checks_tolerance():
    for art in (42, {}, _run()):
        result = check_objective_integrity(art)
        assert set(result) >= {"passed", "checks", "tolerance"}


def test_tolerance_echoes_caller():
    assert check_objective_integrity(_run(), tolerance=0.05)["tolerance"] == 0.05
    assert check_objective_integrity(_run())["tolerance"] == DEFAULT_TOLERANCE


# --- Checks-row sanitation ---------------------------------------------------------------

def test_check_rows_list_skips_malformed_rows(caplog):
    good = {"name": "ok", "passed": True}
    assert _check_rows_list(None) == []
    with caplog.at_level(logging.WARNING, logger="benchmark.objective_integrity"):
        assert _check_rows_list(42) == []
        assert _check_rows_list([good, "junk", {"name": "x"}, {"passed": True},
                                 {"name": 5, "passed": True}]) == [good]


def test_check_rows_list_rejects_non_bool_passed():
    # `type(...) is not bool` -> a truthy int is rejected, not coerced.
    assert _check_rows_list([{"name": "x", "passed": 1}]) == []


# --- Failed checks and headline ----------------------------------------------------------

def test_failed_checks_names():
    result = {"checks": [{"name": "a", "passed": True}, {"name": "b", "passed": False}]}
    assert failed_checks(result) == ["b"]
    assert failed_checks(42) == []


def test_headline_no_checks():
    assert integrity_headline({"checks": []}) == "objective integrity: no checks evaluated"
    assert integrity_headline(42) == "objective integrity: no checks evaluated"


def test_headline_valid():
    result = {"passed": True, "checks": [{"name": "a", "passed": True},
                                         {"name": "b", "passed": True}]}
    assert integrity_headline(result) == "objective integrity: VALID (2 checks passed)"


def test_headline_invalid_lists_failures():
    result = {"passed": False, "checks": [{"name": "a", "passed": True},
                                          {"name": "b", "passed": False}]}
    assert integrity_headline(result) == (
        "objective integrity: INVALID (1/2 checks failed: b)")


# --- Pure evaluation ---------------------------------------------------------------------

def test_check_does_not_mutate_artifact():
    art = _run()
    snapshot = copy.deepcopy(art)
    check_objective_integrity(art)
    assert art == snapshot
