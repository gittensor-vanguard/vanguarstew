"""Contract tests for specs/048-benchmark-repo-task-mean.

These tests document the as-built EARS contract for benchmark.repo_task_mean:
input coercion, task-count semantics, artifact-kind branches, headline output,
and pure evaluation. Offline and deterministic.
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
    repo_task_mean_headline,
    summarize_repo_task_mean,
)

_REQUIRED_KEYS = frozenset(
    {"kind", "scored_repos", "total_tasks", "mean_tasks_per_repo", "partitions"}
)


def _repo(tasks, name="r"):
    return {"repo": name, "tasks": tasks, "composite_mean": 0.6}


def _multi(*task_counts):
    return {
        "repos": len(task_counts),
        "scored_repos": sum(1 for t in task_counts if isinstance(t, int) and not isinstance(t, bool) and t > 0),
        "composite_mean": 0.6,
        "per_repo": [_repo(t, f"r{i}") for i, t in enumerate(task_counts)],
    }


@pytest.mark.parametrize("bad", (None, "not a dict", 42, [1, 2], ()))
def test_non_dict_artifact_returns_invalid_summary(bad):
    out = summarize_repo_task_mean(bad)
    assert out["kind"] == "invalid"
    assert out["scored_repos"] == 0
    assert out["total_tasks"] == 0
    assert out["mean_tasks_per_repo"] is None
    assert out["partitions"] is None


def test_dict_helper_returns_dict_or_empty():
    assert _dict({"a": 1}) == {"a": 1}
    assert _dict(None) == {}
    assert _dict("bad") == {}


def test_is_int_rejects_bool_and_float():
    assert _is_int(3)
    assert not _is_int(True)
    assert not _is_int(False)
    assert not _is_int(3.0)


def test_single_positive_integer_tasks_scores_one_repo():
    out = summarize_repo_task_mean({"composite_mean": 0.6, "tasks": 8})
    assert out["kind"] == "single"
    assert out["scored_repos"] == 1
    assert out["total_tasks"] == 8
    assert out["mean_tasks_per_repo"] == 8.0


@pytest.mark.parametrize("tasks", (0, -1, True, 3.0, "3", None))
def test_single_non_positive_or_non_int_tasks_score_zero(tasks):
    out = summarize_repo_task_mean({"composite_mean": 0.6, "tasks": tasks})
    assert out["scored_repos"] == 0
    assert out["total_tasks"] == 0
    assert out["mean_tasks_per_repo"] is None


def test_missing_per_repo_is_empty():
    assert _partition_stats(None) == {
        "scored_repos": 0,
        "total_tasks": 0,
        "mean_tasks_per_repo": None,
    }


def test_non_list_per_repo_logs_warning(caplog):
    with caplog.at_level(logging.WARNING):
        out = _partition_stats("bad")
    assert out["scored_repos"] == 0
    assert "not a list" in caplog.text


def test_non_dict_rows_are_skipped_with_warning(caplog):
    with caplog.at_level(logging.WARNING):
        out = _partition_stats(["bad", _repo(5)])
    assert out["scored_repos"] == 1
    assert out["total_tasks"] == 5
    assert "not an object" in caplog.text


def test_only_positive_integer_tasks_count():
    out = summarize_repo_task_mean(_multi(6, 0, -1, True, 4, 3.0))
    assert out["scored_repos"] == 2
    assert out["total_tasks"] == 10
    assert out["mean_tasks_per_repo"] == 5.0


def test_multi_summary_uses_positive_task_rows():
    out = summarize_repo_task_mean(_multi(3, 6, 0))
    assert out["kind"] == "multi"
    assert out["scored_repos"] == 2
    assert out["total_tasks"] == 9
    assert out["mean_tasks_per_repo"] == 4.5
    assert out["partitions"] is None


def test_generalization_reports_partition_and_combined_means():
    out = summarize_repo_task_mean(
        {
            "generalization_gap": 0.1,
            "tuned": _multi(4, 2),
            "held_out": _multi(3, 0),
        }
    )
    assert out["kind"] == "generalization"
    assert out["scored_repos"] == 3
    assert out["total_tasks"] == 9
    assert out["mean_tasks_per_repo"] == 3.0
    assert out["partitions"]["tuned"]["mean_tasks_per_repo"] == 3.0
    assert out["partitions"]["held_out"]["mean_tasks_per_repo"] == 3.0


def test_invalid_kind_returns_zero_counts():
    out = summarize_repo_task_mean({})
    assert out["kind"] == "invalid"
    assert out["scored_repos"] == 0
    assert out["total_tasks"] == 0
    assert out["mean_tasks_per_repo"] is None
    assert out["partitions"] is None


def test_summary_always_has_required_keys():
    for artifact in (
        {"composite_mean": 0.6, "tasks": 1},
        _multi(2, 0),
        {"generalization_gap": 0.0, "tuned": _multi(1), "held_out": {}},
        {},
        None,
    ):
        assert _REQUIRED_KEYS <= frozenset(summarize_repo_task_mean(artifact))


def test_headline_formats_mean_to_three_decimals():
    summary = summarize_repo_task_mean(_multi(2, 5))
    assert repo_task_mean_headline(summary) == (
        "repo task mean: multi 2 scored repo(s), mean 3.500 tasks/repo"
    )


def test_headline_missing_or_non_numeric_mean_uses_na():
    assert repo_task_mean_headline({}) == (
        "repo task mean: unknown None scored repo(s), mean n/a tasks/repo"
    )
    assert repo_task_mean_headline({"kind": "multi", "scored_repos": 2, "mean_tasks_per_repo": True}) == (
        "repo task mean: multi 2 scored repo(s), mean n/a tasks/repo"
    )


def test_headline_non_dict_summary_is_coerced():
    assert repo_task_mean_headline(None) == (
        "repo task mean: unknown None scored repo(s), mean n/a tasks/repo"
    )


def test_summarize_does_not_mutate_artifact():
    artifact = {"generalization_gap": 0.1, "tuned": _multi(4, 2), "held_out": _multi(3)}
    before = copy.deepcopy(artifact)
    summarize_repo_task_mean(artifact)
    assert artifact == before
