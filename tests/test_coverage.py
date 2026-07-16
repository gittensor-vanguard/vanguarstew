"""Tests for the multi-repo coverage breadth gate (deterministic, offline)."""

import copy
import logging
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from benchmark.coverage import (  # noqa: E402
    DEFAULT_MIN_REPOS,
    DEFAULT_MIN_TASKS,
    _check_rows_list,
    _collect_per_repo_entries,
    _per_repo_list,
    check_coverage,
    coverage_headline,
    failed_checks,
)


def _repo(tasks=2, error=None, name="a"):
    r = {"repo": name, "tasks": tasks, "composite_mean": 0.6 if tasks else 0.0}
    if error is not None:
        r["error"] = error
    return r


def _multi(*repos, scored_repos=None, skipped=None):
    scored = scored_repos if scored_repos is not None else sum(1 for r in repos if r.get("tasks", 0) > 0)
    skipped_n = skipped if skipped is not None else len(repos) - scored
    return {
        "repos": len(repos),
        "scored_repos": scored,
        "skipped": skipped_n,
        "composite_mean": 0.6,
        "per_repo": list(repos),
    }


def _names(result):
    return [c["name"] for c in result["checks"]]


def test_a_broad_multi_repo_run_passes():
    result = check_coverage(_multi(_repo(2, name="a"), _repo(3, name="b"), _repo(2, name="c")))
    assert result["passed"] is True
    assert result["repos_scored"] == 3
    assert result["total_tasks"] == 7
    assert _names(result) == ["is_multi_repo", "min_repos_scored", "max_skipped", "min_tasks"]


def test_too_few_scored_repos_fails():
    result = check_coverage(_multi(_repo(2), _repo(0, error="too small")), min_repos=2)
    assert result["passed"] is False
    assert "min_repos_scored" in failed_checks(result)
    assert result["repos_scored"] == 1


def test_too_many_skipped_fails():
    result = check_coverage(
        _multi(_repo(2), _repo(0, error="x"), _repo(0, error="y")),
        max_skipped=1,
    )
    assert result["passed"] is False
    assert "max_skipped" in failed_checks(result)
    assert result["repos_skipped"] == 2


def test_too_few_total_tasks_fails():
    result = check_coverage(_multi(_repo(1), _repo(1)), min_tasks=3)
    assert result["passed"] is False
    assert "min_tasks" in failed_checks(result)
    assert result["total_tasks"] == 2


def test_single_repo_result_fails_is_multi_repo():
    single = {"tasks": 5, "composite_mean": 0.7, "tally": {"challenger": 3, "baseline": 2, "tie": 0}}
    result = check_coverage(single)
    assert result["passed"] is False
    assert failed_checks(result) == [
        "is_multi_repo", "min_repos_scored", "max_skipped", "min_tasks",
    ]


def test_generalization_combines_both_partitions():
    report = {
        "tuned": _multi(_repo(2, name="t1"), _repo(2, name="t2")),
        "held_out": _multi(_repo(2, name="h1")),
        "generalization_gap": 0.05,
    }
    result = check_coverage(report, min_repos=3, min_tasks=6)
    assert result["passed"] is True
    assert result["source"] == "generalization"
    assert result["repos_scored"] == 3
    assert result["total_tasks"] == 6


def test_generalization_with_skipped_across_partitions():
    report = {
        "tuned": _multi(_repo(2), _repo(0, error="skip")),
        "held_out": _multi(_repo(2)),
        "generalization_gap": 0.1,
    }
    result = check_coverage(report, min_repos=2, max_skipped=1, min_tasks=4)
    assert result["passed"] is True
    assert result["repos_scored"] == 2
    assert result["repos_skipped"] == 1


def test_corrupt_string_row_counts_as_skipped_others_ignored():
    # A non-empty string per_repo row is a corrupt/errored repo: it counts as a skipped repo
    # (into repos_total and repos_skipped), not silently dropped — mirroring error_repo_share
    # (#1362) and freeze_coverage (#1386). A dict row with a non-numeric tasks count carries no
    # usable task signal and is still ignored, and empty/whitespace strings carry no repo signal.
    multi = _multi(_repo(2), _repo(3))
    multi["per_repo"].append("errored-repo")     # corrupt string -> counts as skipped
    multi["per_repo"].append({"tasks": "many"})  # non-numeric tasks -> ignored
    multi["per_repo"].append("   ")              # whitespace -> ignored
    result = check_coverage(multi)
    assert result["repos_scored"] == 2
    assert result["repos_skipped"] == 1
    assert result["repos_total"] == 3
    assert result["total_tasks"] == 5


def test_corrupt_string_rows_trip_max_skipped_gate():
    # Two corrupt string rows are two skipped repos; they must fail the max_skipped gate rather
    # than false-passing SUFFICIENT because they were dropped from the count.
    result = check_coverage({"per_repo": [_repo(5), _repo(5), "errored-c", "errored-d"]})
    assert result["repos_scored"] == 2
    assert result["repos_skipped"] == 2
    assert result["repos_total"] == 4
    assert result["passed"] is False


def test_non_list_per_repo_is_treated_as_empty():
    result = check_coverage({"per_repo": 42})
    assert result["repos_scored"] == 0
    assert result["passed"] is False


def test_thresholds_are_configurable():
    run = _multi(_repo(2), _repo(2))
    assert check_coverage(run, min_repos=2, min_tasks=4)["passed"] is True
    assert check_coverage(run, min_repos=3)["passed"] is False
    assert check_coverage(run, min_tasks=5)["passed"] is False


def test_malformed_or_non_dict_result_fails_gracefully():
    for bad in (None, "not a dict", 42, [1, 2]):
        result = check_coverage(bad)
        assert result["passed"] is False
        assert result["checks"]
        assert result["repos_scored"] == 0


def test_headline_reports_sufficient_and_insufficient():
    ok = coverage_headline(check_coverage(_multi(_repo(2), _repo(2))))
    assert "SUFFICIENT" in ok
    bad = coverage_headline(check_coverage({"tasks": 3}))
    assert "INSUFFICIENT" in bad
    assert coverage_headline({}) == "coverage: no checks evaluated"
    assert DEFAULT_MIN_REPOS == 2 and DEFAULT_MIN_TASKS == 3


def test_every_check_reported_even_when_several_fail():
    result = check_coverage({"tasks": 1})
    assert len(result["checks"]) == 4
    assert set(failed_checks(result)) == {
        "is_multi_repo", "min_repos_scored", "max_skipped", "min_tasks",
    }


def test_check_coverage_does_not_mutate_the_result():
    run = _multi(_repo(2), _repo(2))
    snapshot = copy.deepcopy(run)
    check_coverage(run)
    assert run == snapshot


def test_collect_per_repo_entries_helpers():
    entries, source = _collect_per_repo_entries(_multi(_repo(1)))
    assert source == "multi" and len(entries) == 1
    gen = {"tuned": {"per_repo": [_repo(1)]}, "held_out": {"per_repo": [_repo(2)]}, "generalization_gap": 0.0}
    entries, source = _collect_per_repo_entries(gen)
    assert source == "generalization" and len(entries) == 2
    assert _collect_per_repo_entries({"tasks": 1}) == ([], "none")
    assert _per_repo_list([1, 2]) == [1, 2]
    assert _per_repo_list("bad") == []


# --- #760: checks row sanitization for coverage headlines ---------------------------

_MALFORMED_CHECKS = [
    42, 3.14, True, {"name": "is_multi_repo"}, "not a list",
    ({"name": "is_multi_repo", "passed": False},),
    range(2),
]
_FALSY_SCALAR_CHECKS = [0, 0.0, False, ""]


def test_check_rows_list_accepts_only_real_lists():
    rows = [{"name": "is_multi_repo", "passed": True}]
    for bad in _MALFORMED_CHECKS:
        assert _check_rows_list(bad) == [], bad
    assert _check_rows_list(rows) == rows
    assert _check_rows_list(None) == []
    assert _check_rows_list([]) == []


@pytest.mark.parametrize("bad", _FALSY_SCALAR_CHECKS)
def test_check_rows_list_treats_falsy_scalars_as_non_list(bad, caplog):
    with caplog.at_level(logging.WARNING, logger="benchmark.coverage"):
        assert _check_rows_list(bad) == []
    assert any("not a list" in r.message for r in caplog.records)


def test_check_rows_list_missing_key_emits_no_warning(caplog):
    with caplog.at_level(logging.WARNING, logger="benchmark.coverage"):
        assert _check_rows_list(None) == []
    assert not caplog.records


def test_check_rows_list_empty_list_emits_no_warning(caplog):
    with caplog.at_level(logging.WARNING, logger="benchmark.coverage"):
        assert _check_rows_list([]) == []
    assert not caplog.records


def test_check_rows_list_warns_for_tuple_container(caplog):
    row = ({"name": "is_multi_repo", "passed": False},)
    with caplog.at_level(logging.WARNING, logger="benchmark.coverage"):
        assert _check_rows_list(row) == []
    assert any("checks is tuple" in r.message for r in caplog.records)


def test_check_rows_list_warns_for_skipped_rows(caplog):
    mixed = [42, {"name": "is_multi_repo", "passed": True}]
    with caplog.at_level(logging.WARNING, logger="benchmark.coverage"):
        assert len(_check_rows_list(mixed)) == 1
    assert any("checks[0] is int" in r.message for r in caplog.records)
    assert not any("no usable rows" in r.message for r in caplog.records)


def test_check_rows_list_warns_when_every_entry_is_unusable(caplog):
    junk = [42, "bad", None]
    with caplog.at_level(logging.WARNING, logger="benchmark.coverage"):
        assert _check_rows_list(junk) == []
    messages = [r.message for r in caplog.records]
    assert any("checks[0] is int" in m for m in messages)
    assert any("no usable rows" in m for m in messages)


def test_check_rows_list_warns_when_only_malformed_dict_rows(caplog):
    junk = [{}, {"name": 42, "passed": True}, {"name": "is_multi_repo", "passed": "no"}]
    with caplog.at_level(logging.WARNING, logger="benchmark.coverage"):
        assert _check_rows_list(junk) == []
    messages = [r.message for r in caplog.records]
    assert any("missing required key(s)" in m for m in messages)
    assert any("name is int" in m for m in messages)
    assert any("passed is str" in m for m in messages)
    assert any("no usable rows" in m for m in messages)


def test_check_rows_list_returns_only_valid_rows():
    valid = [
        {"name": "is_multi_repo", "passed": False},
        {"name": "min_repos_scored", "passed": True},
    ]
    assert _check_rows_list(valid) == valid
    mixed = [
        valid[0],
        42,
        {},
        {"name": 99, "passed": False},
        {"name": "is_multi_repo", "passed": 1},
        valid[1],
    ]
    assert _check_rows_list(mixed) == valid


def test_check_rows_list_skips_row_missing_name(caplog):
    with caplog.at_level(logging.WARNING, logger="benchmark.coverage"):
        assert _check_rows_list([{"passed": False}]) == []
    assert any("missing required key(s) ['name']" in r.message for r in caplog.records)


def test_check_rows_list_skips_row_missing_passed(caplog):
    with caplog.at_level(logging.WARNING, logger="benchmark.coverage"):
        assert _check_rows_list([{"name": "is_multi_repo"}]) == []
    assert any("missing required key(s) ['passed']" in r.message for r in caplog.records)


def test_coverage_headline_survives_non_list_checks():
    base = {"passed": False, "repos_scored": 0, "total_tasks": 0}
    for bad in _MALFORMED_CHECKS:
        assert coverage_headline({**base, "checks": bad}) == (
            "coverage: no checks evaluated"
        ), bad


@pytest.mark.parametrize("bad", _FALSY_SCALAR_CHECKS)
def test_coverage_headline_survives_falsy_scalar_checks(bad):
    assert coverage_headline({"checks": bad, "passed": False}) == (
        "coverage: no checks evaluated"
    )


def test_coverage_headline_survives_rows_missing_required_keys():
    for checks in (
        [{"passed": False}],
        [{"name": "is_multi_repo"}],
        [{}],
        [{"name": 42, "passed": True}],
        [{"name": "is_multi_repo", "passed": 1}],
    ):
        assert coverage_headline({"checks": checks, "passed": False}) == (
            "coverage: no checks evaluated"
        )


def test_coverage_headline_uses_sanitized_row_count(caplog):
    checks = [{"name": "is_multi_repo", "passed": False}, 42]
    with caplog.at_level(logging.WARNING, logger="benchmark.coverage"):
        line = coverage_headline({"checks": checks, "passed": False})
    assert line == "coverage: INSUFFICIENT (1/1 checks failed: is_multi_repo)"
    assert any("checks[1] is int" in r.message for r in caplog.records)


def test_coverage_headline_logs_warning_for_non_list_checks(caplog):
    with caplog.at_level(logging.WARNING, logger="benchmark.coverage"):
        line = coverage_headline({"checks": 42, "passed": False})
    assert line == "coverage: no checks evaluated"
    assert any("checks is int" in r.message for r in caplog.records)


def test_failed_checks_survives_non_list_checks():
    for bad in _MALFORMED_CHECKS:
        assert failed_checks({"checks": bad}) == [], bad


def test_failed_checks_never_raises_on_malformed_rows():
    for checks in (
        [{"passed": False}],
        [{"name": "is_multi_repo"}],
        [{}],
        [42],
        [{"name": 42, "passed": True}],
        [{"name": "is_multi_repo", "passed": "no"}],
    ):
        assert failed_checks({"checks": checks}) == []


def test_failed_checks_logs_warning_for_skipped_rows(caplog):
    checks = [
        {"name": "is_multi_repo", "passed": False},
        42,
        {"name": "min_repos_scored", "passed": True},
    ]
    with caplog.at_level(logging.WARNING, logger="benchmark.coverage"):
        assert failed_checks({"checks": checks}) == ["is_multi_repo"]
    assert any("checks[1] is int" in r.message for r in caplog.records)


# --- non-finite (NaN/Infinity) numeric fields must fail checks, not raise (#927) ----------


def test_non_finite_per_repo_tasks_fail_coverage_instead_of_raising():
    # the exact repro from #927: previously ValueError from int(float("nan"))
    result = check_coverage({"per_repo": [{"tasks": float("nan")}], "composite_mean": 0.5})
    assert result["passed"] is False

    # a NaN-task repo reads as unscored/taskless, exactly like a wrong-typed tasks field:
    # it drops out of the scored count and the task total instead of crashing the gate
    art = _multi(_repo(name="a"), _repo(name="b", tasks=4))
    art["per_repo"][0]["tasks"] = float("nan")
    art["scored_repos"] = 2
    result = check_coverage(art)
    assert result["total_tasks"] == 4
    assert "min_repos_scored" in [c["name"] for c in result["checks"] if not c["passed"]]


def test_non_finite_per_repo_tasks_never_raise_for_any_variant():
    for bad in (float("nan"), float("inf"), float("-inf"), 10**400):
        art = _multi(_repo(name="a"), _repo(name="b"))
        art["per_repo"][0]["tasks"] = bad
        result = check_coverage(art)   # must not raise
        assert isinstance(result["passed"], bool), bad


def test_non_finite_top_level_counts_fall_back_to_derived_values():
    # a non-finite scored_repos/skipped is malformed and ignored, exactly like a
    # wrong-typed one -- the gate falls back to counts derived from per_repo
    art = _multi(_repo(name="a"), _repo(name="b"))
    art["scored_repos"] = float("inf")
    art["skipped"] = float("nan")
    result = check_coverage(art)       # must not raise
    assert result["repos_scored"] == 2
    assert result["passed"] is True
