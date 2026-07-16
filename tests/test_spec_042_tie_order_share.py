"""Contract tests for specs/042-benchmark-tie-order-share — assert tie_order_share.py
satisfies the spec's EARS criteria: count parsing, slice summary, artifact-kind branches
(including the generalization partition split), headline branches, and pure evaluation.
Offline, deterministic.
"""

import copy
import math
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from benchmark.tie_order_share import (  # noqa: E402
    _dict,
    _is_int,
    _is_number,
    _order_stats,
    _slice_summary,
    summarize_tie_order_share,
    tie_order_share_headline,
)

_REQUIRED_KEYS = frozenset({"kind", "total", "tie", "tie_order_share", "partitions"})


def _stats(agree=0, disagree=0, tie=0, single=0, offline=0):
    return {"judge_order_stats": {
        "agree": agree, "disagree": disagree, "tie": tie, "single": single, "offline": offline,
    }}


# --- Input coercion -------------------------------------------------------------------------


@pytest.mark.parametrize("bad", (None, "not a dict", 42, [1, 2], ()))
def test_non_dict_artifact_coerced_to_empty_dict(bad):
    out = summarize_tie_order_share(bad)
    assert out["kind"] == "invalid"
    assert out["total"] is None and out["tie_order_share"] is None
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


# --- Finite numeric semantics (_is_number) --------------------------------------------------


def test_bool_and_non_finite_not_numeric():
    assert _is_number(0.25) and _is_number(3)
    assert not _is_number(True)
    assert not _is_number(math.nan)
    assert not _is_number(math.inf)
    assert not _is_number("0.5")


# --- Order-stats extraction (_order_stats) --------------------------------------------------


def test_order_stats_returns_dict_or_empty():
    stats = {"tie": 1}
    assert _order_stats({"judge_order_stats": stats}) is stats
    assert _order_stats({"judge_order_stats": "nope"}) == {}
    assert _order_stats({}) == {}
    assert _order_stats(None) == {}


# --- Slice summary (_slice_summary) ---------------------------------------------------------


def test_slice_summary_happy_path():
    # tie 2 of total 8 -> 0.25
    out = _slice_summary(_stats(agree=3, disagree=1, tie=2, single=1, offline=1))
    assert out == {"total": 8, "tie": 2, "tie_order_share": 0.25}


def test_slice_summary_zero_total_reports_zero_counts():
    # coherent all-zero counts: no share is defined, but total/tie are reported as 0.
    out = _slice_summary(_stats())
    assert out == {"total": 0, "tie": 0, "tie_order_share": None}


def test_slice_summary_missing_key_withholds():
    # a missing outcome key makes the counts incoherent -> all None.
    out = _slice_summary({"judge_order_stats": {"tie": 1}})
    assert out == {"total": None, "tie": None, "tie_order_share": None}


@pytest.mark.parametrize("stats", [
    {"agree": 0, "disagree": 0, "tie": -1, "single": 0, "offline": 0},   # negative
    {"agree": 0, "disagree": 0, "tie": 1.0, "single": 0, "offline": 0},  # float
    {"agree": 0, "disagree": 0, "tie": True, "single": 0, "offline": 0},  # bool
])
def test_slice_summary_negative_or_non_int_withholds(stats):
    out = _slice_summary({"judge_order_stats": stats})
    assert out == {"total": None, "tie": None, "tie_order_share": None}


# --- Artifact-kind branches (summarize_tie_order_share) --------------------------------------


def test_single_and_multi_kinds():
    single = summarize_tie_order_share(_stats(agree=3, disagree=1, tie=2, single=1, offline=1))
    assert single["kind"] == "single"
    assert single["total"] == 8 and single["tie"] == 2
    assert single["tie_order_share"] == 0.25 and single["partitions"] is None

    multi_art = {"per_repo": [], **_stats(agree=1, disagree=1, tie=2, single=0, offline=0)}
    multi = summarize_tie_order_share(multi_art)
    assert multi["kind"] == "multi" and multi["partitions"] is None
    assert multi["total"] == 4 and multi["tie_order_share"] == 0.5


def test_invalid_kind_returns_none_fields():
    out = summarize_tie_order_share({})
    assert out["kind"] == "invalid"
    assert out["total"] is None and out["tie_order_share"] is None
    assert out["partitions"] is None


def test_summary_always_includes_required_keys():
    for art in ({}, _stats(agree=1, disagree=0, tie=1, single=0, offline=0),
                {"per_repo": [], **_stats()},
                {"generalization_gap": 0.1, "tuned": _stats(agree=1, disagree=0, tie=1),
                 "held_out": _stats(agree=1, disagree=0, tie=1)}):
        assert _REQUIRED_KEYS <= set(summarize_tie_order_share(art))


def test_generalization_partitions_and_overall():
    art = {
        "generalization_gap": 0.1,
        "tuned": _stats(agree=2, disagree=1, tie=1, single=0, offline=0),   # total 4, tie 1
        "held_out": _stats(agree=1, disagree=0, tie=1, single=0, offline=0),  # total 2, tie 1
    }
    out = summarize_tie_order_share(art)
    assert out["kind"] == "generalization"
    assert out["total"] == 6 and out["tie"] == 2                    # summed across partitions
    assert out["tie_order_share"] == round(2 / 6, 3)               # 0.333
    assert out["partitions"]["tuned"]["tie_order_share"] == 0.25
    assert out["partitions"]["held_out"]["tie_order_share"] == 0.5


def test_generalization_partial_partition_withholds_overall():
    # held_out is malformed (missing keys) -> its total is None -> the overall combine withholds,
    # but each partition's own summary is still reported.
    art = {
        "generalization_gap": 0.1,
        "tuned": _stats(agree=2, disagree=1, tie=1, single=0, offline=0),
        "held_out": {"judge_order_stats": {"tie": 1}},
    }
    out = summarize_tie_order_share(art)
    assert out["total"] is None and out["tie"] is None
    assert out["tie_order_share"] is None
    assert out["partitions"]["tuned"]["total"] == 4
    assert out["partitions"]["held_out"]["total"] is None


# --- Tie-order share headline (tie_order_share_headline) -------------------------------------


def test_headline_with_counts_exact_format():
    summary = summarize_tie_order_share(_stats(agree=3, disagree=1, tie=2, single=1, offline=1))
    assert tie_order_share_headline(summary) == "tie-order share: 25.0% (2/8 categorized task(s))"


def test_headline_zero_total_shows_unavailable():
    assert tie_order_share_headline({"total": 0}) == "tie-order share: no judge stats available"
    assert tie_order_share_headline({"total": None}) == "tie-order share: no judge stats available"
    assert tie_order_share_headline({}) == "tie-order share: no judge stats available"


def test_headline_none_share_shows_na():
    # a positive total with an undefined share still renders the counts clause, share as n/a.
    summary = {"total": 5, "tie": 2, "tie_order_share": None}
    assert tie_order_share_headline(summary) == "tie-order share: n/a (2/5 categorized task(s))"


def test_headline_nan_share_shows_na():
    summary = {"total": 5, "tie": 2, "tie_order_share": float("nan")}
    assert tie_order_share_headline(summary) == "tie-order share: n/a (2/5 categorized task(s))"


def test_headline_non_dict_summary_coerced():
    assert tie_order_share_headline("not a dict") == "tie-order share: no judge stats available"


# --- Pure evaluation ------------------------------------------------------------------------


def test_summarize_does_not_mutate_artifact():
    art = {
        "generalization_gap": 0.1,
        "tuned": _stats(agree=2, disagree=1, tie=1, single=0, offline=0),
        "held_out": _stats(agree=1, disagree=0, tie=1, single=0, offline=0),
    }
    snapshot = copy.deepcopy(art)
    summarize_tie_order_share(art)
    assert art == snapshot
