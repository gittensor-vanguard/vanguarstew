"""Contract tests for specs/041-benchmark-partition-task-share — assert partition_task_share.py
satisfies the spec's EARS criteria: task-count parsing, per_repo row handling, partition shares,
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


def test_extra_artifact_keys_ignored():
    art = {"composite_mean": 0.9, "tasks": 5, "extra_field": "ignored", "nested": {"x": 1}}
    out = summarize_partition_task_share(art)
    assert out["total_tasks"] == 5
    assert out["kind"] == "single"


# --- Whole-number count semantics -----------------------------------------------------------


def test_is_int_rejects_bool():
    assert not _is_int(True)
    assert not _is_int(False)
    art = {"per_repo": [_repo(True)], "composite_mean": 0.5}
    assert _scored_tasks(art["per_repo"]) == 0


@pytest.mark.parametrize("value", (4.0, 3.0, 0.0))
def test_is_int_rejects_float_whole_numbers(value):
    assert not _is_int(value)
    art = {"per_repo": [_repo(value)], "composite_mean": 0.5}
    assert _scored_tasks(art["per_repo"]) == 0


def test_is_int_rejects_numpy_integer_scalars():
    np = pytest.importorskip("numpy")
    assert not _is_int(np.int64(4))
    art = {"per_repo": [_repo(np.int64(4))], "composite_mean": 0.5}
    assert _scored_tasks(art["per_repo"]) == 0


# --- Finite numeric semantics ---------------------------------------------------------------


def test_bool_and_non_finite_not_numeric():
    assert not _is_number(True)
    assert not _is_number(False)
    assert not _is_number(float("nan"))
    assert not _is_number(float("inf"))
    assert _is_number(0.0)
    assert _is_number(1)


# --- Per-repo row parsing -------------------------------------------------------------------


def test_rows_from_per_repo_none_is_empty():
    assert _rows_from_per_repo(None) == []


def test_rows_from_per_repo_non_list_warns(caplog):
    with caplog.at_level(logging.WARNING):
        assert _rows_from_per_repo("not a list") == []
    assert "partition_task_share" in caplog.text
    assert "not a list" in caplog.text


def test_rows_from_per_repo_skips_non_dict_entries(caplog):
    per_repo = ["bad", _repo(3), 42, None]
    with caplog.at_level(logging.WARNING):
        rows = _rows_from_per_repo(per_repo)
    assert rows == [_repo(3)]
    assert caplog.text.count("not an object") >= 2


# --- Scored-task counting -------------------------------------------------------------------


def test_scored_tasks_sums_positive_ints_only():
    per_repo = [_repo(4), _repo(2), _repo(0)]
    assert _scored_tasks(per_repo) == 6


def test_scored_tasks_skips_negative_and_missing():
    per_repo = [_repo(-1), _repo(4), {"repo": "r2"}]
    assert _scored_tasks(per_repo) == 4


def test_scored_tasks_rejects_bool_tasks():
    per_repo = [_repo(True), _repo(3)]
    assert _scored_tasks(per_repo) == 3


# --- Partition share ------------------------------------------------------------------------


def test_partition_share_happy_path():
    assert _partition_share(3, 10) == 0.3


def test_partition_share_zero_tasks_is_zero_not_none():
    assert _partition_share(0, 10) == 0.0
    assert _partition_share(0, 10) is not None


def test_partition_share_invalid_total_is_none():
    assert _partition_share(3, 0) is None
    assert _partition_share(3, -1) is None
    assert _partition_share(3.0, 10) is None


def test_partition_entry_shape():
    assert _partition_entry(4, 8) == {"tasks": 4, "share": 0.5}


# --- Artifact-kind branches -----------------------------------------------------------------


def test_single_kind_counts_top_level_tasks():
    out = summarize_partition_task_share({"composite_mean": 0.6, "tasks": 8})
    assert out["kind"] == "single"
    assert out["total_tasks"] == 8
    assert out["partitions"] is None


def test_single_zero_or_missing_tasks():
    assert summarize_partition_task_share({"tasks": 0})["total_tasks"] == 0
    assert summarize_partition_task_share({"composite_mean": 0.5})["total_tasks"] == 0


def test_multi_kind_aggregates_and_partitions():
    out = summarize_partition_task_share(_multi(4, 0, 2))
    assert out["kind"] == "multi"
    assert out["total_tasks"] == 6
    assert out["partitions"]["multi"]["tasks"] == 6
    assert out["partitions"]["multi"]["share"] == 1.0


def test_multi_zero_tasks_partitions_none():
    out = summarize_partition_task_share(_multi(0, 0))
    assert out["total_tasks"] == 0
    assert out["partitions"] is None


def test_generalization_partitions_and_shares():
    art = {
        "tuned": _multi(6, 2),
        "held_out": _multi(4),
        "generalization_gap": 0.1,
    }
    out = summarize_partition_task_share(art)
    assert out["kind"] == "generalization"
    assert out["total_tasks"] == 12
    assert out["partitions"]["tuned"]["tasks"] == 8
    assert out["partitions"]["held_out"]["tasks"] == 4
    assert out["partitions"]["tuned"]["share"] == round(8 / 12, 3)
    assert out["partitions"]["held_out"]["share"] == round(4 / 12, 3)


def test_generalization_empty_partition_share_zero():
    art = {
        "tuned": _multi(3, 3),
        "held_out": {},
        "generalization_gap": None,
    }
    out = summarize_partition_task_share(art)
    assert out["total_tasks"] == 6
    assert out["partitions"]["held_out"]["tasks"] == 0
    assert out["partitions"]["held_out"]["share"] == 0.0


def test_generalization_zero_total_share_none():
    art = {
        "tuned": _multi(0, 0),
        "held_out": _multi(0),
        "generalization_gap": None,
    }
    out = summarize_partition_task_share(art)
    assert out["total_tasks"] == 0
    assert out["partitions"]["tuned"]["share"] is None
    assert out["partitions"]["held_out"]["share"] is None


def test_invalid_kind_returns_zeroed_summary():
    out = summarize_partition_task_share({})
    assert out["kind"] == "invalid"
    assert out["total_tasks"] == 0
    assert out["partitions"] is None


def test_summary_always_includes_required_keys():
    for artifact in (
        {"tasks": 4, "composite_mean": 0.6},
        _multi(2, 3),
        {"tuned": _multi(1), "held_out": _multi(2), "generalization_gap": 0.0},
        {},
        None,
    ):
        out = summarize_partition_task_share(artifact)
        assert _REQUIRED_KEYS <= frozenset(out)


# --- Partition task share headline ----------------------------------------------------------


def test_headline_no_scored_tasks_exact():
    assert partition_task_share_headline({"total_tasks": 0}) == "partition task share: no scored tasks"
    assert partition_task_share_headline({"total_tasks": None}) == "partition task share: no scored tasks"
    assert partition_task_share_headline({}) == "partition task share: no scored tasks"


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


def test_headline_multi_exact_format():
    out = summarize_partition_task_share(_multi(4, 2))
    assert partition_task_share_headline(out) == "partition task share: multi 6 scored task(s)"


def test_headline_none_share_shows_na():
    out = {
        "kind": "generalization",
        "total_tasks": 4,
        "partitions": {
            "tuned": {"tasks": 4, "share": None},
            "held_out": {"tasks": 0, "share": 0.0},
        },
    }
    assert partition_task_share_headline(out) == (
        "partition task share: 4 task(s) (tuned n/a, held-out 0.0%)"
    )


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


def test_headline_unknown_kind_fallback():
    out = {"kind": None, "total_tasks": 5}
    assert partition_task_share_headline(out) == "partition task share: unknown 5 scored task(s)"


# --- Pure evaluation ------------------------------------------------------------------------


def test_summarize_does_not_mutate_artifact():
    art = _multi(4, 2)
    snapshot = copy.deepcopy(art)
    summarize_partition_task_share(art)
    assert art == snapshot
