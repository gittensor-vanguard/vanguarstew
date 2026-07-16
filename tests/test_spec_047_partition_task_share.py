"""Contract tests for specs/047-benchmark-partition-task-share — assert partition_task_share.py
satisfies the spec's EARS criteria: per-repo parsing, partition shares, artifact-kind branches,
headline branches, and pure evaluation. Offline, deterministic.
"""

import copy
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from benchmark.partition_task_share import (  # noqa: E402
    _dict,
    _is_int,
    _is_number,
    _partition_entry,
    _partition_share,
    _rows_from_per_repo,
    _scored_tasks,
    partition_task_share_headline,
    summarize_partition_task_share,
)

_REQUIRED_KEYS = frozenset({"kind", "total_tasks", "partitions"})


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
    out = summarize_partition_task_share(bad)
    assert out["kind"] == "invalid"
    assert out["total_tasks"] == 0
    assert out["partitions"] is None


def test_dict_helper_returns_dict_or_empty():
    assert _dict({"a": 1}) == {"a": 1}
    assert _dict(None) == {}


# --- Whole-number count semantics -----------------------------------------------------------


def test_is_int_rejects_bool():
    assert not _is_int(True)
    assert not _is_int(False)
    assert _partition_share(True, 5) is None


@pytest.mark.parametrize("value", (5.0, 4.0, 0.0))
def test_is_int_rejects_float_whole_numbers(value):
    assert not _is_int(value)
    assert _partition_share(value, 5) is None
    assert _partition_share(5, value) is None


# --- Finite numeric semantics ---------------------------------------------------------------


def test_bool_and_non_finite_not_numeric():
    assert not _is_number(True)
    assert not _is_number(False)
    assert not _is_number(float("nan"))
    assert not _is_number(float("inf"))
    assert _is_number(0.0)
    assert _is_number(1)


# --- Per-repo row parsing -------------------------------------------------------------------


def test_rows_from_per_repo_none_and_non_list():
    assert _rows_from_per_repo(None) == []
    assert _rows_from_per_repo("not-a-list") == []


def test_rows_from_per_repo_skips_non_dict_entries():
    rows = _rows_from_per_repo(["bad", _repo(3), 42])
    assert rows == [_repo(3)]


# --- Scored task counting -------------------------------------------------------------------


def test_scored_tasks_sums_positive_ints():
    assert _scored_tasks([_repo(4), _repo(2)]) == 6


def test_scored_tasks_skips_invalid_tasks():
    per_repo = [
        _repo(0),
        _repo(-1),
        {"repo": "r2"},
        _repo(5.0),
        _repo(3),
    ]
    assert _scored_tasks(per_repo) == 3


# --- Partition share ------------------------------------------------------------------------


def test_partition_share_valid_and_invalid():
    assert _partition_share(3, 10) == 0.3
    assert _partition_share(0, 10) == 0.0
    assert _partition_share(3, 0) is None
    assert _partition_share(3, -1) is None


def test_partition_entry_shape():
    assert _partition_entry(4, 8) == {"tasks": 4, "share": 0.5}


# --- Artifact-kind branches -----------------------------------------------------------------


def test_single_kind():
    out = summarize_partition_task_share({"composite_mean": 0.6, "tasks": 8})
    assert out == {"kind": "single", "total_tasks": 8, "partitions": None}

    zero = summarize_partition_task_share({"composite_mean": 0.6, "tasks": 0})
    assert zero["kind"] == "single"
    assert zero["total_tasks"] == 0


def test_multi_kind_with_and_without_tasks():
    scored = summarize_partition_task_share(_multi(4, 0, 2))
    assert scored["kind"] == "multi"
    assert scored["total_tasks"] == 6
    assert scored["partitions"]["multi"] == {"tasks": 6, "share": 1.0}

    empty = summarize_partition_task_share({"per_repo": [], "composite_mean": 0.5, "repos": 0})
    assert empty["total_tasks"] == 0
    assert empty["partitions"] is None


def test_generalization_partitions():
    art = {
        "tuned": _multi(6, 2),
        "held_out": _multi(4),
        "generalization_gap": 0.1,
    }
    out = summarize_partition_task_share(art)
    assert out["kind"] == "generalization"
    assert out["total_tasks"] == 12
    assert out["partitions"]["tuned"] == {"tasks": 8, "share": round(8 / 12, 3)}
    assert out["partitions"]["held_out"] == {"tasks": 4, "share": round(4 / 12, 3)}

    zero = summarize_partition_task_share({
        "tuned": _multi(0, 0),
        "held_out": _multi(0),
        "generalization_gap": None,
    })
    assert zero["total_tasks"] == 0
    assert zero["partitions"]["tuned"]["share"] is None
    assert zero["partitions"]["held_out"]["share"] is None


def test_invalid_kind():
    out = summarize_partition_task_share({})
    assert out["kind"] == "invalid"
    assert out["total_tasks"] == 0
    assert out["partitions"] is None


def test_summary_always_includes_required_keys():
    for artifact in (
        {"composite_mean": 0.6, "tasks": 8},
        _multi(4, 2),
        {"tuned": _multi(3), "held_out": _multi(1), "generalization_gap": 0.0},
        None,
    ):
        out = summarize_partition_task_share(artifact)
        assert _REQUIRED_KEYS <= frozenset(out)


# --- Partition task share headline ----------------------------------------------------------


def test_headline_generalization_exact_format():
    art = {
        "tuned": _multi(6),
        "held_out": _multi(2),
        "generalization_gap": 0.1,
    }
    out = summarize_partition_task_share(art)
    assert partition_task_share_headline(out) == (
        "partition task share: 8 task(s) (tuned 75.0%, held-out 25.0%)"
    )


def test_headline_multi_kind():
    out = summarize_partition_task_share(_multi(4, 2))
    assert partition_task_share_headline(out) == "partition task share: multi 6 scored task(s)"


def test_headline_no_scored_tasks_exact():
    out = summarize_partition_task_share(_multi(0, 0))
    assert partition_task_share_headline(out) == "partition task share: no scored tasks"


def test_headline_nan_share_shows_na():
    out = {
        "kind": "generalization",
        "total_tasks": 4,
        "partitions": {
            "tuned": {"tasks": 4, "share": float("nan")},
            "held_out": {"tasks": 0, "share": 0.0},
        },
    }
    assert partition_task_share_headline(out) == (
        "partition task share: 4 task(s) (tuned n/a, held-out 0.0%)"
    )


def test_headline_non_dict_summary_coerced():
    assert partition_task_share_headline("nope") == "partition task share: no scored tasks"


# --- Pure evaluation ------------------------------------------------------------------------


def test_summarize_does_not_mutate_artifact():
    art = _multi(4, 2)
    snapshot = copy.deepcopy(art)
    summarize_partition_task_share(art)
    assert art == snapshot
