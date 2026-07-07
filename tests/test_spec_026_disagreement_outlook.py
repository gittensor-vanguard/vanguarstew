"""Contract tests for specs/026-benchmark-disagreement-outlook — assert disagreement_outlook.py
satisfies the spec's EARS criteria: telemetry parsing, partition aggregation, verdict branches,
headline branches, and pure evaluation. Offline, deterministic.
"""

import copy
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from benchmark.disagreement_outlook import (  # noqa: E402
    DEFAULT_STABLE_THRESHOLD,
    _combined,
    _dict,
    _disagreement_counts,
    _is_int,
    _is_number,
    _judge_telemetry,
    _slice_summary,
    _verdict,
    disagreement_outlook_headline,
    summarize_disagreement_outlook,
)

_REQUIRED_KEYS = frozenset({
    "kind",
    "dual_order_tasks",
    "disagreements",
    "disagreement_rate",
    "verdict",
    "stable_threshold",
    "partitions",
})


def _run(rate=0.1, dual=4, source="judge_report"):
    return {
        "composite_mean": 0.6,
        source: {
            "dual_order_tasks": dual,
            "disagreement_rate": rate,
            "wins": 3,
            "losses": 1,
            "ties": 0,
        },
    }


def _partition_report(disagreements, dual):
    return {
        "judge_report": {
            "dual_order_tasks": dual,
            "disagreements": disagreements,
            "disagreement_rate": round(disagreements / dual, 3) if dual else None,
        }
    }


# --- Input coercion -------------------------------------------------------------------------


@pytest.mark.parametrize("bad", (None, "not a dict", 42, [1, 2], ()))
def test_non_dict_artifact_coerced_to_empty_dict(bad):
    out = summarize_disagreement_outlook(bad)
    assert out["kind"] == "invalid"
    assert out["disagreement_rate"] is None
    assert out["verdict"] is None
    assert out["partitions"] is None


def test_dict_helper_returns_dict_or_empty():
    assert _dict({"a": 1}) == {"a": 1}
    assert _dict(None) == {}


# --- Whole-number count semantics -----------------------------------------------------------


def test_is_int_rejects_bool():
    assert not _is_int(True)
    assert not _is_int(False)
    assert _disagreement_counts({"dual_order_tasks": True}) is None


@pytest.mark.parametrize("value", (5.0, 4.0, 0.0))
def test_is_int_rejects_float_whole_numbers(value):
    assert not _is_int(value)
    assert _disagreement_counts({"dual_order_tasks": value}) is None


# --- Finite numeric semantics ---------------------------------------------------------------


def test_bool_and_non_finite_not_numeric():
    assert not _is_number(True)
    assert not _is_number(False)
    assert not _is_number(float("nan"))
    assert not _is_number(float("inf"))
    assert _is_number(0.0)
    assert _is_number(0.3)


# --- Judge telemetry selection --------------------------------------------------------------


def test_judge_telemetry_prefers_report_over_stats():
    slice_ = {
        "judge_report": {"dual_order_tasks": 3, "disagreement_rate": 0.1},
        "judge_order_stats": {"dual_order_tasks": 99, "disagreement_rate": 0.9},
    }
    assert _judge_telemetry(slice_)["dual_order_tasks"] == 3


def test_judge_telemetry_empty_when_missing():
    assert _judge_telemetry({}) == {}
    assert _judge_telemetry({"judge_report": "bad", "judge_order_stats": None}) == {}


# --- Disagreement counts ----------------------------------------------------------------------


def test_disagreement_counts_from_dual_and_rate():
    assert _disagreement_counts({"dual_order_tasks": 4, "disagreement_rate": 0.25}) == (1, 4)


def test_disagreement_counts_from_agree_disagree_tie():
    assert _disagreement_counts({"agree": 2, "disagree": 1, "tie": 1}) == (1, 4)


def test_disagreement_counts_malformed_returns_none():
    assert _disagreement_counts({"dual_order_tasks": -1}) is None
    assert _disagreement_counts({"agree": "many", "disagree": 0, "tie": 0}) is None


# --- Slice summary --------------------------------------------------------------------------


def test_slice_summary_computes_rate_from_counts():
    out = _slice_summary(_run(0.2, 5))
    assert out == {
        "dual_order_tasks": 5,
        "disagreements": 1,
        "disagreement_rate": 0.2,
    }


def test_slice_summary_missing_counts_returns_none():
    assert _slice_summary({"composite_mean": 0.5}) == {
        "dual_order_tasks": None,
        "disagreements": None,
        "disagreement_rate": None,
    }


# --- Partition combination ------------------------------------------------------------------


def test_combined_sums_partitions():
    tuned = {"dual_order_tasks": 4, "disagreements": 1, "disagreement_rate": 0.25}
    held = {"dual_order_tasks": 4, "disagreements": 2, "disagreement_rate": 0.5}
    assert _combined(tuned, held) == {
        "dual_order_tasks": 8,
        "disagreements": 3,
        "disagreement_rate": 0.375,
    }


def test_combined_zero_dual_none_rate():
    tuned = {"dual_order_tasks": 0, "disagreements": 0, "disagreement_rate": None}
    held = {"dual_order_tasks": 0, "disagreements": 0, "disagreement_rate": None}
    assert _combined(tuned, held) == {
        "dual_order_tasks": 0,
        "disagreements": 0,
        "disagreement_rate": None,
    }


def test_combined_partial_partition_returns_none():
    tuned = {"dual_order_tasks": 4, "disagreements": 1, "disagreement_rate": 0.25}
    held = {"dual_order_tasks": None, "disagreements": None, "disagreement_rate": None}
    assert _combined(tuned, held) == {
        "dual_order_tasks": None,
        "disagreements": None,
        "disagreement_rate": None,
    }


# --- Verdict --------------------------------------------------------------------------------


def test_verdict_stable_at_threshold():
    assert _verdict(DEFAULT_STABLE_THRESHOLD, DEFAULT_STABLE_THRESHOLD) == "stable"
    assert _verdict(0.1, DEFAULT_STABLE_THRESHOLD) == "stable"


def test_verdict_unstable_above_threshold():
    assert _verdict(0.5, DEFAULT_STABLE_THRESHOLD) == "unstable"


def test_verdict_none_for_non_numeric_rate():
    assert _verdict(None, DEFAULT_STABLE_THRESHOLD) is None
    assert _verdict(float("nan"), DEFAULT_STABLE_THRESHOLD) is None


# --- Artifact-kind branches -----------------------------------------------------------------


def test_single_and_multi_kinds():
    single = summarize_disagreement_outlook(_run(0.1, 5))
    assert single["kind"] == "single"
    assert single["verdict"] == "stable"
    assert single["partitions"] is None

    multi = summarize_disagreement_outlook({"per_repo": [{}, {}], **_run(0.5, 3)})
    assert multi["kind"] == "multi"
    assert multi["verdict"] == "unstable"
    assert multi["partitions"] is None


def test_generalization_partitions():
    art = {
        "generalization_gap": 0.0,
        "tuned": _partition_report(disagreements=1, dual=4),
        "held_out": _partition_report(disagreements=2, dual=4),
    }
    out = summarize_disagreement_outlook(art)
    assert out["kind"] == "generalization"
    assert out["dual_order_tasks"] == 8
    assert out["disagreements"] == 3
    assert out["disagreement_rate"] == 0.375
    assert out["verdict"] == "unstable"
    assert out["partitions"]["tuned"]["disagreement_rate"] == 0.25
    assert out["partitions"]["held_out"]["disagreement_rate"] == 0.5


def test_generalization_partial_partition_withholds_overall():
    art = {
        "generalization_gap": None,
        "tuned": _partition_report(disagreements=1, dual=4),
        "held_out": {},
    }
    out = summarize_disagreement_outlook(art)
    assert out["disagreement_rate"] is None
    assert out["verdict"] is None
    assert out["partitions"]["tuned"]["disagreement_rate"] == 0.25
    assert out["partitions"]["held_out"]["disagreement_rate"] is None


def test_invalid_kind():
    out = summarize_disagreement_outlook({})
    assert out["kind"] == "invalid"
    assert out["disagreement_rate"] is None
    assert out["verdict"] is None
    assert out["partitions"] is None


def test_custom_threshold():
    out = summarize_disagreement_outlook(_run(0.25, 2), stable_threshold=0.2)
    assert out["verdict"] == "unstable"
    assert out["stable_threshold"] == 0.2


def test_summary_always_includes_required_keys():
    for artifact in (
        _run(0.1, 4),
        {"generalization_gap": 0.0, "tuned": _partition_report(1, 4), "held_out": {}},
        {},
        None,
    ):
        out = summarize_disagreement_outlook(artifact)
        assert _REQUIRED_KEYS <= frozenset(out)


# --- Disagreement outlook headline ----------------------------------------------------------


def test_headline_exact_format():
    out = summarize_disagreement_outlook(_run(0.2, 3))
    assert disagreement_outlook_headline(out) == (
        "disagreement outlook: stable (rate 20.0%, 3 dual-order task(s))"
    )


def test_headline_generalization_exact_format():
    art = {
        "generalization_gap": 0.0,
        "tuned": _partition_report(disagreements=1, dual=4),
        "held_out": _partition_report(disagreements=0, dual=4),
    }
    line = disagreement_outlook_headline(summarize_disagreement_outlook(art))
    assert line == (
        "disagreement outlook: stable (rate 12.5%, 8 dual-order task(s)) "
        "[tuned 25.0%, held-out 0.0%]"
    )


def test_headline_unavailable_dual_order_tasks_shows_na():
    line = disagreement_outlook_headline({
        "kind": "single",
        "verdict": "stable",
        "disagreement_rate": 0.2,
        "dual_order_tasks": None,
    })
    assert line == "disagreement outlook: stable (rate 20.0%, n/a dual-order task(s))"


def test_headline_missing_verdict_shows_unknown():
    line = disagreement_outlook_headline({
        "kind": "single",
        "verdict": None,
        "disagreement_rate": 0.2,
        "dual_order_tasks": 3,
    })
    assert line == "disagreement outlook: unknown (rate 20.0%, 3 dual-order task(s))"


def test_headline_missing_rate_shows_na():
    line = disagreement_outlook_headline({
        "kind": "single",
        "verdict": "stable",
        "disagreement_rate": None,
        "dual_order_tasks": 3,
    })
    assert line == "disagreement outlook: stable (rate n/a, 3 dual-order task(s))"


def test_headline_unstable_verdict():
    out = summarize_disagreement_outlook(_run(0.5, 3))
    assert disagreement_outlook_headline(out) == (
        "disagreement outlook: unstable (rate 50.0%, 3 dual-order task(s))"
    )


def test_headline_nan_rate_shows_na():
    out = summarize_disagreement_outlook(_run(float("nan"), 2))
    assert disagreement_outlook_headline(out) == (
        "disagreement outlook: unknown (rate n/a, n/a dual-order task(s))"
    )


def test_headline_non_dict_summary_coerced():
    assert disagreement_outlook_headline("nope") == (
        "disagreement outlook: unknown (rate n/a, n/a dual-order task(s))"
    )


# --- Pure evaluation ------------------------------------------------------------------------


def test_summarize_does_not_mutate_artifact():
    art = _run(0.1, 4)
    snapshot = copy.deepcopy(art)
    summarize_disagreement_outlook(art)
    assert art == snapshot
