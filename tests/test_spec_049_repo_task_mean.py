"""Contract tests for specs/049-benchmark-repo-task-mean — assert repo_task_mean.py satisfies
the spec's EARS criteria: per-repo parsing, partition stats, artifact-kind branches, headline
branches, and pure evaluation. Offline, deterministic.
"""

import copy
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
    assert out["mean_tasks_per_repo"] is None
    assert out["partitions"] is None


def test_dict_helper_returns_dict_or_empty():
    assert _dict({"a": 1}) == {"a": 1}
    assert _dict(None) == {}


# --- Whole-number count semantics -----------------------------------------------------------


def test_is_int_rejects_bool():
    assert not _is_int(True)
    assert not _is_int(False)
    assert _partition_stats([_repo(True, "r0")])["mean_tasks_per_repo"] is None


@pytest.mark.parametrize("value", (5.0, 4.0, 0.0))
def test_is_int_rejects_float_whole_numbers(value):
    assert not _is_int(value)
    assert _partition_stats([_repo(value, "r0")])["mean_tasks_per_repo"] is None


# --- Per-repo row parsing -------------------------------------------------------------------


def test_rows_from_per_repo_none_and_non_list():
    assert _rows_from_per_repo(None) == []
    assert _rows_from_per_repo("not-a-list") == []


def test_rows_from_per_repo_skips_non_dict_entries():
    rows = _rows_from_per_repo(["bad", _repo(3), 42])
    assert rows == [_repo(3)]


# --- Partition stats ------------------------------------------------------------------------


def test_partition_stats_happy_path():
    assert _partition_stats([_repo(6), _repo(4)]) == {
        "scored_repos": 2,
        "total_tasks": 10,
        "mean_tasks_per_repo": 5.0,
    }


def test_partition_stats_zero_scored_none_mean():
    assert _partition_stats([_repo(0), _repo(-1), {"repo": "r2"}]) == {
        "scored_repos": 0,
        "total_tasks": 0,
        "mean_tasks_per_repo": None,
    }


# --- Artifact-kind branches -----------------------------------------------------------------


def test_single_kind():
    out = summarize_repo_task_mean({"composite_mean": 0.6, "tasks": 8})
    assert out == {
        "kind": "single",
        "scored_repos": 1,
        "total_tasks": 8,
        "mean_tasks_per_repo": 8.0,
        "partitions": None,
    }

    zero = summarize_repo_task_mean({"composite_mean": 0.6, "tasks": 0})
    assert zero["scored_repos"] == 0
    assert zero["mean_tasks_per_repo"] is None


def test_multi_kind():
    out = summarize_repo_task_mean(_multi(6, 0, 4))
    assert out["kind"] == "multi"
    assert out["scored_repos"] == 2
    assert out["total_tasks"] == 10
    assert out["mean_tasks_per_repo"] == 5.0
    assert out["partitions"] is None


def test_generalization_partitions():
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


def test_invalid_kind():
    out = summarize_repo_task_mean({})
    assert out["kind"] == "invalid"
    assert out["scored_repos"] == 0
    assert out["mean_tasks_per_repo"] is None
    assert out["partitions"] is None


def test_summary_always_includes_required_keys():
    for artifact in (
        {"composite_mean": 0.6, "tasks": 8},
        _multi(4, 2),
        {"tuned": _multi(3), "held_out": _multi(1), "generalization_gap": 0.0},
        None,
    ):
        out = summarize_repo_task_mean(artifact)
        assert _REQUIRED_KEYS <= frozenset(out)


# --- Repo task mean headline ----------------------------------------------------------------


def test_headline_exact_format():
    out = summarize_repo_task_mean(_multi(3, 3))
    assert repo_task_mean_headline(out) == (
        "repo task mean: multi 2 scored repo(s), mean 3.000 tasks/repo"
    )


def test_headline_none_mean_shows_na():
    out = summarize_repo_task_mean(_multi(0, 0))
    assert repo_task_mean_headline(out) == (
        "repo task mean: multi 0 scored repo(s), mean n/a tasks/repo"
    )


def test_headline_non_dict_summary_coerced():
    assert repo_task_mean_headline("nope") == (
        "repo task mean: unknown None scored repo(s), mean n/a tasks/repo"
    )


# --- Pure evaluation ------------------------------------------------------------------------


def test_summarize_does_not_mutate_artifact():
    art = _multi(4, 2)
    snapshot = copy.deepcopy(art)
    summarize_repo_task_mean(art)
    assert art == snapshot
