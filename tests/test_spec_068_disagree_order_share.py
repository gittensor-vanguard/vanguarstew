"""Contract tests for specs/068-benchmark-disagree-order-share — assert disagree_order_share.py
satisfies the spec's EARS criteria: binding shape, input coercion, _is_int / _is_number semantics,
the slice happy/zero-total/malformed/negative branches, all three artifact-kind branches, and every
headline branch. Literal expected strings; offline, deterministic.
"""

import copy
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from benchmark.disagree_order_share import (  # noqa: E402
    _dict,
    _is_int,
    _is_number,
    _order_stats,
    _slice_summary,
    disagree_order_share_headline,
    summarize_disagree_order_share,
)
from benchmark.order_share import STAT_KEYS  # noqa: E402

_REQUIRED = {"kind", "total", "disagree", "disagree_order_share", "partitions"}


def _stats(agree=0, disagree=0, tie=0, single=0, offline=0):
    return {"judge_order_stats": {"agree": agree, "disagree": disagree, "tie": tie,
                                  "single": single, "offline": offline}}


# --- Binding -----------------------------------------------------------------------------

def test_binding_exports_and_stat_keys():
    assert STAT_KEYS == ("agree", "disagree", "tie", "single", "offline")
    assert callable(summarize_disagree_order_share)
    assert callable(disagree_order_share_headline)
    assert callable(_slice_summary)


# --- Input coercion ----------------------------------------------------------------------

def test_non_dict_artifact_coerced_to_empty_dict():
    for bad in (42, None, "x", [1], True):
        summary = summarize_disagree_order_share(bad)
        assert _REQUIRED <= set(summary)
        assert summary["total"] is None and summary["disagree_order_share"] is None


def test_dict_helper_returns_dict_or_empty():
    assert _dict({"a": 1}) == {"a": 1}
    for bad in (42, None, "x", [1], True):
        assert _dict(bad) == {}


def test_order_stats_requires_dict():
    assert _order_stats({"judge_order_stats": {"agree": 1}}) == {"agree": 1}
    assert _order_stats({"judge_order_stats": 42}) == {}
    assert _order_stats(42) == {}


# --- Whole-number count semantics --------------------------------------------------------

def test_is_int_rejects_bool():
    assert _is_int(3) is True and _is_int(0) is True
    assert _is_int(True) is False and _is_int(False) is False


def test_is_int_rejects_float_whole_numbers():
    assert _is_int(3.0) is False and _is_int(0.0) is False


# --- Finite numeric semantics ------------------------------------------------------------

def test_bool_and_non_finite_not_numeric():
    assert _is_number(0.25) is True and _is_number(2) is True
    assert _is_number(True) is False
    for bad in (float("nan"), float("inf"), float("-inf"), "0.25", None):
        assert _is_number(bad) is False, bad


# --- Slice summary -----------------------------------------------------------------------

def test_slice_summary_happy_path():
    assert _slice_summary(_stats(agree=3, disagree=1)) == {
        "total": 4, "disagree": 1, "disagree_order_share": 0.25}


def test_slice_summary_zero_total_share_none():
    assert _slice_summary(_stats()) == {"total": 0, "disagree": 0, "disagree_order_share": None}


def test_slice_summary_malformed_stats():
    assert _slice_summary({"judge_order_stats": {"agree": "x"}}) == {
        "total": None, "disagree": None, "disagree_order_share": None}
    assert _slice_summary({"judge_order_stats": {"agree": True, "disagree": 1, "tie": 0,
                                                 "single": 0, "offline": 0}})["total"] is None


def test_slice_summary_negative_counts():
    assert _slice_summary(_stats(agree=-1, disagree=1)) == {
        "total": None, "disagree": None, "disagree_order_share": None}


# --- Artifact-kind branches --------------------------------------------------------------

def test_single_and_multi_kinds():
    single = summarize_disagree_order_share(_stats(agree=3, disagree=1))
    assert single["kind"] == "single"
    assert single["total"] == 4 and single["disagree_order_share"] == 0.25
    assert single["partitions"] is None

    multi = summarize_disagree_order_share(dict(_stats(agree=2, disagree=2), per_repo=[{}, {}]))
    assert multi["kind"] == "multi" and multi["partitions"] is None


def test_generalization_partitions_and_overall():
    art = {"generalization_gap": 0.0,
           "tuned": _stats(agree=3, disagree=1), "held_out": _stats(agree=1, disagree=1)}
    summary = summarize_disagree_order_share(art)
    assert summary["kind"] == "generalization"
    assert summary["partitions"]["tuned"]["disagree_order_share"] == 0.25
    assert summary["partitions"]["held_out"]["disagree_order_share"] == 0.5
    # overall: (1+1) / (4+2) = 0.333
    assert summary["total"] == 6 and summary["disagree"] == 2
    assert summary["disagree_order_share"] == 0.333


def test_generalization_partial_partition_withholds_overall():
    # held_out is a zero-task slice (share None) -> overall withheld, not masked by tuned.
    art = {"generalization_gap": 0.0, "tuned": _stats(agree=3, disagree=1), "held_out": _stats()}
    summary = summarize_disagree_order_share(art)
    assert summary["partitions"]["tuned"]["disagree_order_share"] == 0.25
    assert summary["total"] is None and summary["disagree_order_share"] is None


def test_generalization_malformed_partition_does_not_crash():
    art = {"generalization_gap": 0.0,
           "tuned": {"judge_order_stats": {"agree": "x"}}, "held_out": _stats(agree=1, disagree=1)}
    summary = summarize_disagree_order_share(art)
    assert summary["partitions"]["tuned"]["disagree_order_share"] is None
    assert summary["total"] is None


def test_invalid_kind_returns_none_fields():
    summary = summarize_disagree_order_share({})
    assert summary["kind"] == "invalid"
    assert summary["total"] is None and summary["disagree"] is None
    assert summary["disagree_order_share"] is None and summary["partitions"] is None


def test_summary_always_includes_required_keys():
    for art in (42, {}, _stats(agree=1, disagree=1),
                {"generalization_gap": 0.0, "tuned": _stats(), "held_out": _stats()}):
        assert _REQUIRED <= set(summarize_disagree_order_share(art))


# --- Headline ----------------------------------------------------------------------------

def test_headline_happy_path_exact_format():
    summary = summarize_disagree_order_share(_stats(agree=3, disagree=1))
    assert disagree_order_share_headline(summary) == (
        "disagree-order share: 25.0% (1/4 categorized task(s))")


def test_headline_zero_total_unavailable():
    for summary in ({"total": 0}, {"total": None}, {}, {"total": 3.0}):
        assert disagree_order_share_headline(summary) == (
            "disagree-order share: no judge stats available")


def test_headline_none_share_shows_na():
    summary = {"total": 4, "disagree": 1, "disagree_order_share": None}
    assert disagree_order_share_headline(summary) == (
        "disagree-order share: n/a (1/4 categorized task(s))")


def test_headline_nan_share_shows_na():
    summary = {"total": 4, "disagree": 1, "disagree_order_share": float("nan")}
    assert disagree_order_share_headline(summary) == (
        "disagree-order share: n/a (1/4 categorized task(s))")


def test_headline_non_dict_summary_coerced():
    assert disagree_order_share_headline(42) == "disagree-order share: no judge stats available"


# --- Pure evaluation ---------------------------------------------------------------------

def test_summarize_does_not_mutate_artifact():
    art = {"generalization_gap": 0.0, "tuned": _stats(agree=3, disagree=1),
           "held_out": _stats(agree=1, disagree=1)}
    snapshot = copy.deepcopy(art)
    summarize_disagree_order_share(art)
    assert art == snapshot
