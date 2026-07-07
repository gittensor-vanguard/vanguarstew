"""Contract tests for specs/044-benchmark-order-agree-rate — assert order_agree_rate.py
satisfies the spec's EARS criteria: dual-order count parsing, slice/combined rates,
artifact-kind branches, headline branches, and pure evaluation. Offline, deterministic.
"""

import copy
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from benchmark.order_agree_rate import (  # noqa: E402
    _combined,
    _dict,
    _is_int,
    _is_number,
    _slice_summary,
    order_agree_rate_headline,
    summarize_order_agree_rate,
)

_REQUIRED_KEYS = frozenset({
    "kind", "agree", "disagree", "tie", "total", "agree_rate", "partitions",
})


def _stats(agree=3, disagree=1, tie=1):
    return {
        "composite_mean": 0.6,
        "judge_order_stats": {
            "agree": agree,
            "disagree": disagree,
            "tie": tie,
        },
    }


# --- Input coercion -------------------------------------------------------------------------


@pytest.mark.parametrize("bad", (None, "not a dict", 42, [1, 2], ()))
def test_non_dict_artifact_coerced_to_empty_dict(bad):
    out = summarize_order_agree_rate(bad)
    assert out["kind"] == "invalid"
    assert out["agree_rate"] is None
    assert out["partitions"] is None


def test_dict_helper_returns_dict_or_empty():
    assert _dict({"a": 1}) == {"a": 1}
    assert _dict(None) == {}


# --- Whole-number count semantics -----------------------------------------------------------


def test_is_int_rejects_bool():
    assert not _is_int(True)
    assert not _is_int(False)
    assert _slice_summary(_stats(agree=True, disagree=0, tie=0))["agree_rate"] is None


@pytest.mark.parametrize("value", (5.0, 4.0, 0.0))
def test_is_int_rejects_float_whole_numbers(value):
    assert not _is_int(value)
    art = {"judge_order_stats": {"agree": value, "disagree": 0, "tie": 0}}
    assert _slice_summary(art)["agree_rate"] is None


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
    out = _slice_summary(_stats(agree=6, disagree=2, tie=2))
    assert out == {
        "agree": 6,
        "disagree": 2,
        "tie": 2,
        "total": 10,
        "agree_rate": 0.6,
    }


def test_slice_summary_zero_total_rate_none():
    out = _slice_summary(_stats(0, 0, 0))
    assert out["total"] == 0
    assert out["agree"] == 0
    assert out["agree_rate"] is None


def test_slice_summary_malformed_stats():
    art = {"judge_order_stats": {"agree": 1, "disagree": "x", "tie": 0}}
    out = _slice_summary(art)
    assert out["agree_rate"] is None
    assert out["total"] is None


# --- Combined summary -----------------------------------------------------------------------


def test_combined_sums_coherent_slices():
    both = _combined(
        _slice_summary(_stats(agree=3, disagree=1, tie=0)),
        _slice_summary(_stats(agree=1, disagree=2, tie=1)),
    )
    assert both == {
        "agree": 4,
        "disagree": 3,
        "tie": 1,
        "total": 8,
        "agree_rate": 0.5,
    }


def test_combined_withholds_when_any_slice_incoherent():
    partial = _combined(
        _slice_summary(_stats(agree=2, disagree=0, tie=0)),
        _slice_summary({}),
    )
    assert partial == {
        "agree": None,
        "disagree": None,
        "tie": None,
        "total": None,
        "agree_rate": None,
    }


# --- Artifact-kind branches -----------------------------------------------------------------


def test_single_and_multi_kinds():
    single = summarize_order_agree_rate(_stats(agree=2, disagree=1, tie=0))
    assert single["kind"] == "single"
    assert single["agree_rate"] == round(2 / 3, 3)
    assert single["partitions"] is None

    multi = summarize_order_agree_rate({
        "per_repo": [{"repo": "a"}],
        "judge_order_stats": {"agree": 3, "disagree": 0, "tie": 0},
    })
    assert multi["kind"] == "multi"
    assert multi["agree_rate"] == 1.0
    assert multi["partitions"] is None


def test_generalization_partitions_and_overall():
    summary = summarize_order_agree_rate({
        "generalization_gap": 0.0,
        "tuned": _stats(agree=3, disagree=1, tie=0),
        "held_out": _stats(agree=1, disagree=2, tie=1),
    })
    assert summary["kind"] == "generalization"
    assert summary["agree"] == 4
    assert summary["total"] == 8
    assert summary["agree_rate"] == 0.5
    assert summary["partitions"]["tuned"]["agree_rate"] == 0.75
    assert summary["partitions"]["held_out"]["agree_rate"] == 0.25


def test_generalization_partial_partition_withholds_overall():
    summary = summarize_order_agree_rate({
        "generalization_gap": 0.0,
        "tuned": _stats(agree=2, disagree=0, tie=0),
        "held_out": {},
    })
    assert summary["agree_rate"] is None
    assert summary["total"] is None
    assert summary["partitions"]["tuned"]["agree_rate"] == 1.0
    assert summary["partitions"]["held_out"]["agree_rate"] is None


def test_invalid_kind_returns_none_fields():
    out = summarize_order_agree_rate({})
    assert out["kind"] == "invalid"
    assert out["agree_rate"] is None
    assert out["partitions"] is None


def test_summary_always_includes_required_keys():
    for artifact in (
        _stats(agree=2, disagree=1, tie=0),
        {"generalization_gap": 0.0, "tuned": _stats(), "held_out": {}},
        {},
        None,
    ):
        out = summarize_order_agree_rate(artifact)
        assert _REQUIRED_KEYS <= frozenset(out)


# --- Order agree rate headline ----------------------------------------------------------------


def test_headline_happy_path_exact_format():
    summary = summarize_order_agree_rate(_stats(agree=3, disagree=1, tie=1))
    assert order_agree_rate_headline(summary) == "order agree rate: 60.0% (3/5)"


def test_headline_zero_total_unavailable():
    out = summarize_order_agree_rate(_stats(0, 0, 0))
    assert order_agree_rate_headline(out) == "order agree rate: no dual-order stats available"
    assert order_agree_rate_headline({}) == "order agree rate: no dual-order stats available"


def test_headline_generalization_includes_partitions():
    summary = summarize_order_agree_rate({
        "generalization_gap": 0.1,
        "tuned": _stats(agree=4, disagree=0, tie=0),
        "held_out": _stats(agree=1, disagree=1, tie=0),
    })
    headline = order_agree_rate_headline(summary)
    assert "tuned 100.0%" in headline
    assert "held-out 50.0%" in headline


def test_headline_nan_rate_shows_na():
    out = {
        "kind": "single",
        "agree": 1,
        "total": 2,
        "agree_rate": float("nan"),
        "partitions": None,
    }
    assert order_agree_rate_headline(out) == "order agree rate: n/a (1/2)"


def test_headline_non_dict_summary_coerced():
    assert order_agree_rate_headline("nope") == "order agree rate: no dual-order stats available"


# --- Pure evaluation ------------------------------------------------------------------------


def test_summarize_does_not_mutate_artifact():
    art = _stats(agree=2, disagree=1, tie=0)
    snapshot = copy.deepcopy(art)
    summarize_order_agree_rate(art)
    assert art == snapshot
