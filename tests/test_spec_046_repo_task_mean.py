"""Contract tests for specs/046-benchmark-repo-task-mean — assert repo_task_mean.py satisfies
the spec's EARS criteria: count parsing, per_repo row extraction, partition stats, artifact-kind
branches (including the generalization partition split), the headline, and pure evaluation.
Offline, deterministic.
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

_REQUIRED_KEYS = frozenset({"kind", "scored_repos", "total_tasks", "mean_tasks_per_repo", "partitions"})


# --- Input coercion -------------------------------------------------------------------------


@pytest.mark.parametrize("bad", (None, "not a dict", 42, [1, 2], ()))
def test_non_dict_artifact_coerced_to_empty_dict(bad):
    out = summarize_repo_task_mean(bad)
    assert out["kind"] == "invalid"
    assert out["mean_tasks_per_repo"] is None
    assert out["partitions"] is None


def test_dict_helper_returns_dict_or_empty():
    d = {"a": 1}
    assert _dict(d) is d
    for bad in (None, "x", 3, [1], ()):
        assert _dict(bad) == {}


# --- Whole-number count semantics (_is_int) -------------------------------------------------


def test_is_int_rejects_bool():
    assert _is_int(0) and _is_int(7)
    assert not _is_int(True) and not _is_int(False)


def test_is_int_rejects_float_whole_numbers():
    assert not _is_int(5.0)
    assert not _is_int("5")
    assert not _is_int(None)


# --- per_repo row extraction (_rows_from_per_repo) ------------------------------------------


def test_rows_from_per_repo_none_and_non_list():
    assert _rows_from_per_repo(None) == []
    assert _rows_from_per_repo("garbage") == []
    assert _rows_from_per_repo(42) == []


def test_rows_from_per_repo_skips_non_dict_rows():
    rows = _rows_from_per_repo([{"tasks": 4}, "junk", 5, {"tasks": 2}])
    assert rows == [{"tasks": 4}, {"tasks": 2}]


def test_rows_from_per_repo_warns_on_non_list(caplog):
    with caplog.at_level(logging.WARNING, logger="benchmark.repo_task_mean"):
        assert _rows_from_per_repo("garbage") == []
    assert any("per_repo is str" in r.message for r in caplog.records)


# --- Partition stats (_partition_stats) -----------------------------------------------------


def test_partition_stats_counts_only_positive_int_tasks():
    # 4 and 2 count; 0, -1, 3.0, True(bool), missing do not.
    stats = _partition_stats([
        {"tasks": 4}, {"tasks": 2}, {"tasks": 0}, {"tasks": -1},
        {"tasks": 3.0}, {"tasks": True}, {"other": 1},
    ])
    assert stats == {"scored_repos": 2, "total_tasks": 6, "mean_tasks_per_repo": 3.0}


def test_partition_stats_empty_yields_none_mean():
    assert _partition_stats([]) == {"scored_repos": 0, "total_tasks": 0, "mean_tasks_per_repo": None}
    assert _partition_stats([{"tasks": 0}])["mean_tasks_per_repo"] is None


# --- Artifact-kind branches (summarize_repo_task_mean) --------------------------------------


def test_single_artifact():
    out = summarize_repo_task_mean({"tasks": 5})
    assert out["kind"] == "single"
    assert out["scored_repos"] == 1 and out["total_tasks"] == 5
    assert out["mean_tasks_per_repo"] == 5.0 and out["partitions"] is None


def test_single_without_positive_tasks():
    # A single artifact (has a `tasks` key) whose tasks is not a positive int scores nothing.
    for bad in ({"tasks": 0}, {"tasks": -3}, {"tasks": 2.0}, {"tasks": True}):
        out = summarize_repo_task_mean(bad)
        assert out["kind"] == "single"
        assert out["scored_repos"] == 0 and out["mean_tasks_per_repo"] is None


def test_multi_artifact():
    out = summarize_repo_task_mean({"per_repo": [{"tasks": 4}, {"tasks": 2}, {"tasks": 0}]})
    assert out["kind"] == "multi" and out["partitions"] is None
    assert out["scored_repos"] == 2 and out["total_tasks"] == 6
    assert out["mean_tasks_per_repo"] == 3.0


def test_generalization_partitions_and_overall():
    art = {
        "generalization_gap": 0.1,
        "tuned": {"per_repo": [{"tasks": 4}, {"tasks": 2}]},   # 2 repos, 6 tasks
        "held_out": {"per_repo": [{"tasks": 3}]},              # 1 repo, 3 tasks
    }
    out = summarize_repo_task_mean(art)
    assert out["kind"] == "generalization"
    assert out["scored_repos"] == 3 and out["total_tasks"] == 9       # summed across partitions
    assert out["mean_tasks_per_repo"] == 3.0
    assert out["partitions"]["tuned"]["mean_tasks_per_repo"] == 3.0
    assert out["partitions"]["held_out"]["scored_repos"] == 1


def test_invalid_kind_returns_zeroed_fields():
    out = summarize_repo_task_mean({})
    assert out["kind"] == "invalid"
    assert out["scored_repos"] == 0 and out["total_tasks"] == 0
    assert out["mean_tasks_per_repo"] is None and out["partitions"] is None


def test_summary_always_includes_required_keys():
    for art in ({}, {"tasks": 5}, {"per_repo": [{"tasks": 1}]},
                {"generalization_gap": 0.1, "tuned": {"per_repo": []}, "held_out": {"per_repo": []}}):
        assert _REQUIRED_KEYS <= set(summarize_repo_task_mean(art))


# --- Repo task mean headline (repo_task_mean_headline) --------------------------------------


def test_headline_exact_format():
    summary = summarize_repo_task_mean({"per_repo": [{"tasks": 4}, {"tasks": 2}]})
    assert repo_task_mean_headline(summary) == "repo task mean: multi 2 scored repo(s), mean 3.000 tasks/repo"


def test_headline_none_mean_shows_na():
    summary = summarize_repo_task_mean({"per_repo": []})
    assert repo_task_mean_headline(summary) == "repo task mean: multi 0 scored repo(s), mean n/a tasks/repo"


def test_headline_non_dict_summary_coerced():
    assert repo_task_mean_headline("not a dict") == (
        "repo task mean: unknown None scored repo(s), mean n/a tasks/repo"
    )


# --- Pure evaluation ------------------------------------------------------------------------


def test_summarize_does_not_mutate_artifact():
    art = {
        "generalization_gap": 0.1,
        "tuned": {"per_repo": [{"tasks": 4}, {"tasks": 2}]},
        "held_out": {"per_repo": [{"tasks": 3}]},
    }
    snapshot = copy.deepcopy(art)
    summarize_repo_task_mean(art)
    assert art == snapshot
