"""Contract tests for specs/047-benchmark-dual-order-coverage — assert dual_order_coverage.py
satisfies the spec's EARS criteria: count parsing, coverage ratio, generalization branches,
headline branches, and pure evaluation. Offline, deterministic.
"""

import copy
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from benchmark.dual_order_coverage import (  # noqa: E402
    _combined,
    _coverage,
    _dict,
    _dual_order_tasks,
    _is_int,
    _is_ratio,
    _slice_coverage,
    _task_total,
    dual_order_coverage_headline,
    summarize_dual_order_coverage,
)

_REQUIRED_KEYS = frozenset({"kind", "dual_order_tasks", "tasks", "coverage", "partitions"})


def _slice(tasks=10, dual=4, **extra):
    return {
        "tasks": tasks,
        "judge_order_stats": {"dual_order_tasks": dual},
        **extra,
    }


# --- Input coercion -------------------------------------------------------------------------


@pytest.mark.parametrize("bad", (None, "not a dict", 42, [1, 2], ()))
def test_non_dict_artifact_coerced_to_empty_dict(bad):
    out = summarize_dual_order_coverage(bad)
    assert out["kind"] == "invalid"
    assert out["coverage"] is None
    assert out["partitions"] is None


def test_dict_helper_returns_dict_or_empty():
    assert _dict({"a": 1}) == {"a": 1}
    assert _dict(None) == {}


# --- Whole-number count semantics -----------------------------------------------------------


def test_is_int_rejects_bool():
    assert not _is_int(True)
    assert not _is_int(False)
    assert _dual_order_tasks(_slice(tasks=10, dual=True)) is None
    assert _task_total(_slice(tasks=True, dual=0)) is None


@pytest.mark.parametrize("value", (5.0, 4.0, 0.0))
def test_is_int_rejects_float_whole_numbers(value):
    assert not _is_int(value)
    assert _task_total(_slice(tasks=value, dual=4)) is None
    assert _dual_order_tasks(_slice(tasks=10, dual=value)) is None


# --- Ratio semantics ------------------------------------------------------------------------


def test_is_ratio_rejects_bool():
    assert not _is_ratio(True)
    assert not _is_ratio(False)


def test_is_ratio_accepts_numeric():
    assert _is_ratio(0.4)
    assert _is_ratio(1)
    assert _is_ratio(0.0)


# --- Count extraction -----------------------------------------------------------------------


def test_dual_order_tasks_and_task_total_happy_path():
    slice_ = _slice(tasks=10, dual=4)
    assert _dual_order_tasks(slice_) == 4
    assert _task_total(slice_) == 10


def test_task_total_sums_per_repo_when_no_top_level_tasks():
    # Multi-repo / generalization slices carry no top-level `tasks`; the total is summed from
    # per_repo, else None when per_repo is missing/empty or any entry is malformed.
    assert _task_total({"per_repo": [{"tasks": 3}, {"tasks": 3}]}) == 6
    assert _task_total({"per_repo": []}) is None
    assert _task_total({"per_repo": [{"tasks": 3}, {"tasks": "x"}]}) is None
    assert _task_total({"per_repo": "nope"}) is None
    # A valid top-level `tasks` still takes priority over per_repo.
    assert _task_total({"tasks": 4, "per_repo": [{"tasks": 99}]}) == 4


def test_count_helpers_missing_stats():
    assert _dual_order_tasks({"tasks": 10}) is None
    assert _task_total({"judge_order_stats": {"dual_order_tasks": 4}}) is None


def test_count_helpers_non_dict_stats():
    assert _dual_order_tasks({"tasks": 10, "judge_order_stats": "nope"}) is None


def test_count_helpers_negative_rejected():
    assert _task_total(_slice(tasks=-1, dual=0)) is None
    assert _dual_order_tasks(_slice(tasks=10, dual=-2)) is None


# --- Coverage ratio -------------------------------------------------------------------------


def test_coverage_happy_path():
    assert _coverage(4, 10) == 0.4
    assert _coverage(10, 10) == 1.0


@pytest.mark.parametrize(
    "dual,total",
    (
        (None, 10),
        (4, None),
        (0, 0),
        (5, 0),
    ),
)
def test_coverage_none_branches(dual, total):
    assert _coverage(dual, total) is None


def test_coverage_dual_exceeds_total():
    assert _coverage(5, 3) is None


# --- Slice coverage -------------------------------------------------------------------------


def test_slice_coverage_happy_path():
    assert _slice_coverage(_slice(tasks=10, dual=4)) == {
        "dual_order_tasks": 4,
        "tasks": 10,
        "coverage": 0.4,
    }


def test_slice_coverage_non_dict():
    assert _slice_coverage(None) == {
        "dual_order_tasks": None,
        "tasks": None,
        "coverage": None,
    }


# --- Combined coverage ----------------------------------------------------------------------


def test_combined_happy_path():
    tuned = _slice_coverage(_slice(tasks=6, dual=6))
    held_out = _slice_coverage(_slice(tasks=4, dual=2))
    assert _combined(tuned, held_out) == {
        "dual_order_tasks": 8,
        "tasks": 10,
        "coverage": 0.8,
    }


def test_combined_partial_withholds():
    tuned = _slice_coverage(_slice(tasks=6, dual=6))
    held_out = _slice_coverage({})
    assert _combined(tuned, held_out) == {
        "dual_order_tasks": None,
        "tasks": None,
        "coverage": None,
    }


# --- Artifact-kind branches -----------------------------------------------------------------


def test_single_and_multi_kinds():
    single = summarize_dual_order_coverage(_slice(tasks=10, dual=4))
    assert single["kind"] == "single"
    assert single["coverage"] == 0.4
    assert single["partitions"] is None

    multi = summarize_dual_order_coverage({**_slice(tasks=8, dual=6), "per_repo": [{}, {}]})
    assert multi["kind"] == "multi"
    assert multi["coverage"] == 0.75
    assert multi["partitions"] is None


def test_generalization_partitions_and_overall():
    summary = summarize_dual_order_coverage({
        "generalization_gap": 0.05,
        "tuned": _slice(tasks=6, dual=6),
        "held_out": _slice(tasks=4, dual=2),
    })
    assert summary["kind"] == "generalization"
    assert summary["dual_order_tasks"] == 8
    assert summary["tasks"] == 10
    assert summary["coverage"] == 0.8
    assert summary["partitions"]["tuned"]["coverage"] == 1.0
    assert summary["partitions"]["held_out"]["coverage"] == 0.5


def test_generalization_partial_partition_withholds_overall():
    summary = summarize_dual_order_coverage({
        "generalization_gap": 0.0,
        "tuned": _slice(tasks=6, dual=6),
        "held_out": {},
    })
    assert summary["coverage"] is None
    assert summary["dual_order_tasks"] is None
    assert summary["tasks"] is None
    assert summary["partitions"]["tuned"]["coverage"] == 1.0
    assert summary["partitions"]["held_out"]["coverage"] is None


def test_invalid_kind_returns_none_fields():
    out = summarize_dual_order_coverage({})
    assert out["kind"] == "invalid"
    assert out["dual_order_tasks"] is None
    assert out["tasks"] is None
    assert out["coverage"] is None
    assert out["partitions"] is None


def test_summary_always_includes_required_keys():
    for artifact in (
        _slice(tasks=10, dual=4),
        {"generalization_gap": 0.0, "tuned": _slice(), "held_out": {}},
        {},
        None,
    ):
        out = summarize_dual_order_coverage(artifact)
        assert _REQUIRED_KEYS <= frozenset(out)


# --- Dual-order coverage headline -----------------------------------------------------------


def test_headline_happy_path_exact_format():
    summary = summarize_dual_order_coverage(_slice(tasks=10, dual=4))
    assert dual_order_coverage_headline(summary) == (
        "dual-order coverage: 40.0% (4/10 tasks judged in both orders)"
    )


def test_headline_missing_counts_degrades():
    assert dual_order_coverage_headline({"coverage": None, "dual_order_tasks": None, "tasks": None}) == (
        "dual-order coverage: n/a"
    )
    assert dual_order_coverage_headline({"coverage": 0.4, "dual_order_tasks": None, "tasks": 10}) == (
        "dual-order coverage: 40.0%"
    )


def test_headline_non_dict_summary_coerced():
    assert dual_order_coverage_headline("nope") == "dual-order coverage: n/a"
    assert dual_order_coverage_headline(None) == "dual-order coverage: n/a"


# --- Pure evaluation ------------------------------------------------------------------------


def test_summarize_does_not_mutate_artifact():
    art = _slice(tasks=10, dual=4)
    snapshot = copy.deepcopy(art)
    summarize_dual_order_coverage(art)
    assert art == snapshot
