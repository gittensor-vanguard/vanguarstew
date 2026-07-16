"""Contract tests for specs/040-benchmark-dual-order-share — assert dual_order_share.py
satisfies the spec's EARS criteria: count parsing, slice/generalization branches, headline
branches, and pure evaluation. Offline, deterministic.
"""

import copy
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from benchmark.dual_order_share import (  # noqa: E402
    _dict,
    _is_int,
    _is_number,
    _slice_summary,
    dual_order_share_headline,
    summarize_dual_order_share,
)

_REQUIRED_KEYS = frozenset({"kind", "total", "dual_order_tasks", "dual_order_share", "partitions"})


def _stats(agree=3, disagree=1, tie=1, single=0, offline=0):
    return {
        "composite_mean": 0.6,
        "judge_order_stats": {
            "agree": agree,
            "disagree": disagree,
            "tie": tie,
            "single": single,
            "offline": offline,
        },
    }


# --- Input coercion -------------------------------------------------------------------------


@pytest.mark.parametrize("bad", (None, "not a dict", 42, [1, 2], ()))
def test_non_dict_artifact_coerced_to_empty_dict(bad):
    out = summarize_dual_order_share(bad)
    assert out["kind"] == "invalid"
    assert out["dual_order_share"] is None
    assert out["partitions"] is None


def test_dict_helper_returns_dict_or_empty():
    assert _dict({"a": 1}) == {"a": 1}
    assert _dict(None) == {}


# --- Whole-number count semantics -----------------------------------------------------------


def test_is_int_rejects_bool():
    assert not _is_int(True)
    assert not _is_int(False)
    assert _slice_summary(_stats(agree=True, disagree=0, tie=0, single=0, offline=0))[
        "dual_order_share"
    ] is None


@pytest.mark.parametrize("value", (5.0, 4.0, 0.0))
def test_is_int_rejects_float_whole_numbers(value):
    assert not _is_int(value)
    art = {"judge_order_stats": {"agree": value, "disagree": 0, "tie": 0, "single": 0, "offline": 0}}
    assert _slice_summary(art)["dual_order_share"] is None


# --- Finite numeric semantics ---------------------------------------------------------------


def test_bool_and_non_finite_not_numeric():
    assert not _is_number(True)
    assert not _is_number(False)
    assert not _is_number(float("nan"))
    assert not _is_number(float("inf"))
    assert _is_number(0.0)
    assert _is_number(1)


# --- Slice summary --------------------------------------------------------------------------


def test_slice_summary_happy_path():
    out = _slice_summary(_stats(agree=2, disagree=1, tie=1, single=2, offline=0))
    assert out == {"total": 6, "dual_order_tasks": 4, "dual_order_share": round(4 / 6, 3)}


def test_slice_summary_zero_total_share_none():
    out = _slice_summary(_stats(0, 0, 0, 0, 0))
    assert out["total"] == 0
    assert out["dual_order_tasks"] == 0
    assert out["dual_order_share"] is None


def test_slice_summary_malformed_stats():
    art = {"judge_order_stats": {"agree": 1, "disagree": "x", "tie": 0, "single": 0, "offline": 0}}
    assert _slice_summary(art) == {"total": None, "dual_order_tasks": None, "dual_order_share": None}


def test_slice_summary_negative_counts():
    assert _slice_summary(_stats(-1, 0, 0, 0, 0))["dual_order_share"] is None


# --- Artifact-kind branches -----------------------------------------------------------------


def test_single_and_multi_kinds():
    single = summarize_dual_order_share(_stats(agree=4, disagree=0, tie=0, single=1, offline=0))
    assert single["kind"] == "single"
    assert single["dual_order_tasks"] == 4
    assert single["dual_order_share"] == 0.8
    assert single["partitions"] is None

    multi = summarize_dual_order_share({
        "per_repo": [{}, {}],
        **_stats(agree=4, disagree=0, tie=0, single=1, offline=0),
    })
    assert multi["kind"] == "multi"
    assert multi["dual_order_share"] == 0.8
    assert multi["partitions"] is None


def test_generalization_partitions_and_overall():
    summary = summarize_dual_order_share({
        "generalization_gap": 0.05,
        "tuned": _stats(agree=4, disagree=0, tie=0, single=0, offline=0),
        "held_out": _stats(agree=2, disagree=0, tie=0, single=2, offline=0),
    })
    assert summary["kind"] == "generalization"
    assert summary["dual_order_tasks"] == 6
    assert summary["total"] == 8
    assert summary["dual_order_share"] == 0.75
    assert summary["partitions"]["tuned"]["dual_order_share"] == 1.0
    assert summary["partitions"]["held_out"]["dual_order_share"] == 0.5


def test_generalization_partial_partition_withholds_overall():
    summary = summarize_dual_order_share({
        "generalization_gap": 0.0,
        "tuned": {"judge_order_stats": {"agree": 1, "disagree": 0, "tie": 0, "single": 0, "offline": 0}},
        "held_out": {},
    })
    assert summary["dual_order_share"] is None
    assert summary["total"] is None
    assert summary["dual_order_tasks"] is None
    assert summary["partitions"]["tuned"]["dual_order_share"] == 1.0
    assert summary["partitions"]["held_out"]["dual_order_share"] is None


def test_generalization_malformed_partition_does_not_crash():
    summary = summarize_dual_order_share({
        "generalization_gap": 0.0,
        "tuned": _stats(agree=1, disagree=0, tie=0, single=0, offline=0),
        "held_out": {"judge_order_stats": {"agree": None, "disagree": 0, "tie": 0, "single": 0, "offline": 0}},
    })
    assert summary["dual_order_share"] is None
    assert summary["total"] is None


def test_invalid_kind_returns_none_fields():
    out = summarize_dual_order_share({})
    assert out["kind"] == "invalid"
    assert out["total"] is None
    assert out["dual_order_tasks"] is None
    assert out["dual_order_share"] is None
    assert out["partitions"] is None


def test_summary_always_includes_required_keys():
    for artifact in (
        _stats(agree=4, disagree=0, tie=0, single=1, offline=0),
        {"generalization_gap": 0.0, "tuned": _stats(), "held_out": {}},
        {},
        None,
    ):
        out = summarize_dual_order_share(artifact)
        assert _REQUIRED_KEYS <= frozenset(out)


# --- Dual order share headline --------------------------------------------------------------


def test_headline_happy_path_exact_format():
    summary = summarize_dual_order_share(_stats(agree=4, disagree=0, tie=0, single=1, offline=0))
    assert dual_order_share_headline(summary) == "dual-order share: 80.0% (4/5 categorized task(s))"


def test_headline_zero_total_unavailable():
    assert dual_order_share_headline({"total": 0}) == "dual-order share: no judge stats available"
    assert dual_order_share_headline({"total": None}) == "dual-order share: no judge stats available"
    assert dual_order_share_headline({}) == "dual-order share: no judge stats available"


def test_headline_none_share_shows_na():
    assert dual_order_share_headline({"total": 5, "dual_order_tasks": 4, "dual_order_share": None}) == (
        "dual-order share: n/a (4/5 categorized task(s))"
    )


def test_headline_nan_share_shows_na():
    out = {"total": 5, "dual_order_tasks": 4, "dual_order_share": float("nan")}
    assert dual_order_share_headline(out) == "dual-order share: n/a (4/5 categorized task(s))"


def test_headline_non_dict_summary_coerced():
    assert dual_order_share_headline("nope") == "dual-order share: no judge stats available"


# --- Pure evaluation ------------------------------------------------------------------------


def test_summarize_does_not_mutate_artifact():
    art = _stats(agree=4, disagree=0, tie=0, single=1, offline=0)
    snapshot = copy.deepcopy(art)
    summarize_dual_order_share(art)
    assert art == snapshot
