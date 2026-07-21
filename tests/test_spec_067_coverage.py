"""Spec 067 contract tests for benchmark/coverage.py (multi-repo coverage gate).

Pins the as-built behavior described in specs/067-benchmark-coverage/spec.md with literal expected
check names, ``passed`` values and detail strings. Integration / CLI coverage lives in
tests/test_coverage.py.
"""

import logging
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from benchmark.coverage import (  # noqa: E402
    _CHECK_ROW_KEYS,
    DEFAULT_MAX_SKIPPED,
    DEFAULT_MIN_REPOS,
    DEFAULT_MIN_TASKS,
    _collect_per_repo_entries,
    _dict,
    _is_number,
    _partition_counts,
    _per_repo_list,
    _repo_tasks,
    _total_scored_tasks,
    check_coverage,
    coverage_headline,
    failed_checks,
)


def _named(checks):
    return {c["name"]: c for c in checks}


def _multi(*task_counts):
    return {"per_repo": [{"tasks": t} for t in task_counts]}


# --- Constants -----------------------------------------------------------------------------------

def test_constants_are_pinned():
    assert (DEFAULT_MIN_REPOS, DEFAULT_MAX_SKIPPED, DEFAULT_MIN_TASKS) == (2, 1, 3)
    assert _CHECK_ROW_KEYS == ("name", "passed")


# --- Helpers -------------------------------------------------------------------------------------

def test_is_number_semantics():
    assert _is_number(3) is True
    assert _is_number(0.0) is True
    assert _is_number(True) is False
    assert _is_number(float("nan")) is False
    assert _is_number(float("inf")) is False
    assert _is_number("3") is False


def test_is_number_rejects_oversized_int():
    assert _is_number(10 ** 400) is False


def test_dict_helper():
    d = {"a": 1}
    assert _dict(d) is d
    for bad in (None, 5, "x", [1]):
        assert _dict(bad) == {}


def test_per_repo_list_coercion(caplog):
    rows = [{"tasks": 1}]
    assert _per_repo_list(rows) is rows
    assert _per_repo_list(None) == []
    with caplog.at_level(logging.WARNING, logger="benchmark.coverage"):
        assert _per_repo_list(42) == []
    assert any("not a list" in r.message for r in caplog.records)


def test_repo_tasks():
    assert _repo_tasks({"tasks": 4}) == 4
    assert _repo_tasks({"tasks": 0}) == 0
    assert _repo_tasks({"tasks": "x"}) is None
    assert _repo_tasks({}) is None
    assert _repo_tasks("nope") is None


# --- Per-repo collection -------------------------------------------------------------------------

def test_collect_multi():
    entries, source = _collect_per_repo_entries({"per_repo": [{"tasks": 3}]})
    assert source == "multi" and entries == [{"tasks": 3}]


def test_collect_generalization():
    result = {"generalization_gap": 0.0,
              "tuned": {"per_repo": [{"tasks": 3}]},
              "held_out": {"per_repo": [{"tasks": 2}]}}
    entries, source = _collect_per_repo_entries(result)
    assert source == "generalization"
    assert entries == [{"tasks": 3}, {"tasks": 2}]


def test_collect_none():
    assert _collect_per_repo_entries({"composite_mean": 0.6}) == ([], "none")


# --- Counting ------------------------------------------------------------------------------------

def test_partition_counts_dicts_and_corrupt_strings():
    entries = [{"tasks": 3}, {"tasks": 0}, "corrupt", "   ", 42, {"tasks": "x"}]
    total, scored, skipped = _partition_counts(entries)
    # 3->scored, 0->skipped, "corrupt"->skipped; whitespace/int/non-numeric-tasks ignored.
    assert (total, scored, skipped) == (3, 1, 2)


def test_total_scored_tasks():
    assert _total_scored_tasks([{"tasks": 3}, {"tasks": 0}, {"tasks": 2}, "x"]) == 5


# --- Gate ----------------------------------------------------------------------------------------

_RESULT_KEYS = {"passed", "checks", "source", "repos_total", "repos_scored", "repos_skipped",
                "total_tasks", "min_repos", "max_skipped", "min_tasks"}


def test_result_carries_all_keys():
    assert set(check_coverage(_multi(3, 2))) == _RESULT_KEYS


def test_sufficient_multi_repo_passes():
    result = check_coverage(_multi(3, 2))          # 2 scored, 0 skipped, 5 tasks
    assert result["passed"] is True
    assert [c["name"] for c in result["checks"]] == [
        "is_multi_repo", "min_repos_scored", "max_skipped", "min_tasks"]
    assert result["repos_scored"] == 2 and result["total_tasks"] == 5


def test_min_repos_and_skipped_and_tasks_fail():
    # 1 scored, 2 skipped, 1 task -> below min_repos, above max_skipped, below min_tasks.
    result = check_coverage(_multi(1, 0, 0))
    checks = _named(result["checks"])
    assert result["passed"] is False
    assert checks["is_multi_repo"]["passed"] is True
    assert checks["min_repos_scored"]["passed"] is False
    assert checks["max_skipped"]["passed"] is False
    assert checks["min_tasks"]["passed"] is False
    assert checks["min_repos_scored"]["detail"] == "1 scored repo(s) >= min_repos 2"


def test_single_repo_forces_breadth_checks_false():
    result = check_coverage({"composite_mean": 0.6})   # not multi-repo
    checks = _named(result["checks"])
    assert checks["is_multi_repo"]["passed"] is False
    for name in ("min_repos_scored", "max_skipped", "min_tasks"):
        assert checks[name]["passed"] is False
        assert checks[name]["detail"] == "not applicable (single-repo artifact)"
    assert result["passed"] is False


# --- Checks-row sanitation -----------------------------------------------------------------------

def test_check_rows_list_skips_malformed_rows():
    result = {"checks": [
        {"name": "is_multi_repo", "passed": True},
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
    with caplog.at_level(logging.WARNING, logger="benchmark.coverage"):
        assert failed_checks({"checks": [{"name": "a"}]}) == []
    assert any("no usable rows" in r.message for r in caplog.records)


# --- Failed checks and headline ------------------------------------------------------------------

def test_failed_checks_names():
    result = {"checks": [{"name": "min_tasks", "passed": False},
                         {"name": "is_multi_repo", "passed": True}]}
    assert failed_checks(result) == ["min_tasks"]


def test_headline_no_checks():
    assert coverage_headline({"checks": []}) == "coverage: no checks evaluated"
    assert coverage_headline({}) == "coverage: no checks evaluated"
    assert coverage_headline("nope") == "coverage: no checks evaluated"


def test_headline_sufficient():
    result = check_coverage(_multi(3, 2))
    assert coverage_headline(result) == "coverage: SUFFICIENT (2 scored repo(s), 5 task(s))"


def test_headline_insufficient_lists_failures():
    result = check_coverage(_multi(1, 0, 0))
    line = coverage_headline(result)
    assert line.startswith("coverage: INSUFFICIENT (3/4 checks failed:")
    assert "min_repos_scored" in line and "max_skipped" in line and "min_tasks" in line


# --- Pure evaluation -----------------------------------------------------------------------------

def test_check_does_not_mutate_artifact():
    import copy
    artifact = {"generalization_gap": 0.0,
                "tuned": {"per_repo": [{"tasks": 3}]},
                "held_out": {"per_repo": [{"tasks": 2}]}}
    snapshot = copy.deepcopy(artifact)
    check_coverage(artifact)
    assert artifact == snapshot
