"""Contract tests for specs/046-benchmark-repo-task-mean — assert repo_task_mean.py satisfies
the spec's EARS criteria: task-count parsing, per_repo row handling, partition stats,
artifact-kind branches, headline branches, logging, and pure evaluation. Offline, deterministic.
"""

import copy
import logging
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from benchmark.repo_task_mean import (  # noqa: E402
    _dict,
    _is_int,
    _partition_stats,
    _rows_from_per_repo,
    repo_task_mean_headline,
    summarize_repo_task_mean,
)

_REQUIRED_KEYS = frozenset({
    "kind",
    "scored_repos",
    "total_tasks",
    "mean_tasks_per_repo",
    "partitions",
})


def _repo(tasks, name="r"):
    return {"repo": name, "tasks": tasks, "composite_mean": 0.6}


def _multi(*task_counts):
    return {
        "repos": len(task_counts),
        "scored_repos": sum(1 for t in task_counts if t > 0),
        "composite_mean": 0.6,
        "per_repo": [_repo(t, f"r{i}") for i, t in enumerate(task_counts)],
    }


# --- Input coercion -------------------------------------------------------------------------


@pytest.mark.parametrize("bad", (None, "not a dict", 42, [1, 2], ()))
def test_non_dict_artifact_coerced_to_empty_dict(bad):
    out = summarize_repo_task_mean(bad)
    assert out["kind"] == "invalid"
    assert out["scored_repos"] == 0
    assert out["mean_tasks_per_repo"] is None
    assert out["partitions"] is None


def test_dict_helper_returns_dict_or_empty():
    assert _dict({"a": 1}) == {"a": 1}
    assert _dict(None) == {}


# --- Whole-number count semantics -----------------------------------------------------------


def test_is_int_rejects_bool():
    assert not _is_int(True)
    assert not _is_int(False)
    assert _partition_stats([_repo(True)])["mean_tasks_per_repo"] is None


@pytest.mark.parametrize("value", (5.0, 4.0, 0.0))
def test_is_int_rejects_float_whole_numbers(value):
    assert not _is_int(value)
    assert _partition_stats([_repo(value)])["scored_repos"] == 0


# --- Per-repo row parsing -------------------------------------------------------------------


def test_rows_from_per_repo_none_is_empty():
    assert _rows_from_per_repo(None) == []


def test_rows_from_per_repo_non_list_warns(caplog):
    with caplog.at_level(logging.WARNING):
        assert _rows_from_per_repo("not a list") == []
    assert "repo_task_mean" in caplog.text
    assert "not a list" in caplog.text


def test_rows_from_per_repo_skips_non_dict_entries(caplog):
    per_repo = ["bad", _repo(3), 42, None]
    with caplog.at_level(logging.WARNING):
        rows = _rows_from_per_repo(per_repo)
    assert rows == [_repo(3)]
    assert caplog.text.count("not an object") >= 2


# --- Partition stats ------------------------------------------------------------------------


def test_partition_stats_happy_path():
    out = _partition_stats([_repo(4), _repo(2), _repo(0)])
    assert out == {"scored_repos": 2, "total_tasks": 6, "mean_tasks_per_repo": 3.0}


def test_partition_stats_zero_scored_mean_none():
    assert _partition_stats([_repo(0), _repo(0)]) == {
        "scored_repos": 0,
        "total_tasks": 0,
        "mean_tasks_per_repo": None,
    }


def test_partition_stats_skips_non_positive_tasks():
    assert _partition_stats([_repo(-1), _repo(5)])["total_tasks"] == 5


# --- Artifact-kind branches -----------------------------------------------------------------


def test_single_kind_positive_and_zero_tasks():
    out = summarize_repo_task_mean({"composite_mean": 0.6, "tasks": 8})
    assert out["kind"] == "single"
    assert out["scored_repos"] == 1
    assert out["total_tasks"] == 8
    assert out["mean_tasks_per_repo"] == 8.0
    assert out["partitions"] is None

    zero = summarize_repo_task_mean({"tasks": 0})
    assert zero["scored_repos"] == 0
    assert zero["total_tasks"] == 0
    assert zero["mean_tasks_per_repo"] is None


def test_multi_kind_aggregates():
    out = summarize_repo_task_mean(_multi(6, 0, 4))
    assert out["kind"] == "multi"
    assert out["scored_repos"] == 2
    assert out["total_tasks"] == 10
    assert out["mean_tasks_per_repo"] == 5.0
    assert out["partitions"] is None


def test_generalization_partitions_and_overall():
    art = {
        "tuned": _multi(4, 2),
        "held_out": _multi(3),
        "generalization_gap": 0.1,
    }
    out = summarize_repo_task_mean(art)
    assert out["kind"] == "generalization"
    assert out["scored_repos"] == 3
    assert out["total_tasks"] == 9
    assert out["mean_tasks_per_repo"] == 3.0
    assert out["partitions"]["tuned"]["mean_tasks_per_repo"] == 3.0
    assert out["partitions"]["held_out"]["mean_tasks_per_repo"] == 3.0


def test_invalid_kind_returns_zeroed_summary():
    out = summarize_repo_task_mean({})
    assert out["kind"] == "invalid"
    assert out["scored_repos"] == 0
    assert out["total_tasks"] == 0
    assert out["mean_tasks_per_repo"] is None
    assert out["partitions"] is None


def test_summary_always_includes_required_keys():
    for artifact in (
        {"tasks": 4, "composite_mean": 0.6},
        _multi(2, 3),
        {"tuned": _multi(1), "held_out": _multi(2), "generalization_gap": 0.0},
        {},
        None,
    ):
        out = summarize_repo_task_mean(artifact)
        assert _REQUIRED_KEYS <= frozenset(out)


# --- Repo task mean headline ----------------------------------------------------------------


def test_headline_happy_path_exact_format():
    out = summarize_repo_task_mean(_multi(3, 3))
    assert repo_task_mean_headline(out) == "repo task mean: multi 2 scored repo(s), mean 3.000 tasks/repo"


def test_headline_none_mean_shows_na():
    out = {"kind": "multi", "scored_repos": 0, "mean_tasks_per_repo": None}
    assert repo_task_mean_headline(out) == "repo task mean: multi 0 scored repo(s), mean n/a tasks/repo"


def test_headline_nan_mean_formats_as_nan():
    out = {"kind": "single", "scored_repos": 1, "mean_tasks_per_repo": float("nan")}
    assert repo_task_mean_headline(out) == "repo task mean: single 1 scored repo(s), mean nan tasks/repo"


def test_headline_unknown_kind_fallback():
    out = {"kind": None, "scored_repos": 2, "mean_tasks_per_repo": 1.5}
    assert repo_task_mean_headline(out) == "repo task mean: unknown 2 scored repo(s), mean 1.500 tasks/repo"


def test_headline_non_dict_summary_coerced():
    assert repo_task_mean_headline("nope") == "repo task mean: unknown None scored repo(s), mean n/a tasks/repo"


# --- Pure evaluation ------------------------------------------------------------------------


def test_summarize_does_not_mutate_artifact():
    art = _multi(4, 2)
    snapshot = copy.deepcopy(art)
    summarize_repo_task_mean(art)
    assert art == snapshot
