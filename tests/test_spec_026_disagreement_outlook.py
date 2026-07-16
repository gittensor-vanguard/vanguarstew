"""Contract tests for specs/026-benchmark-disagreement-outlook — assert
benchmark/disagreement_outlook.py satisfies the spec's EARS criteria: input coercion and number
validity, the count-derivation rules, the slice summary's source preference (judge_order_stats over
a stale judge_report), the overall summary shape across single / multi / generalization / invalid
artifacts, the combined-partition outlook and its zero-dual edge, the verdict boundary and threshold
coercion, the one-line headline, and pure evaluation — deep non-mutation across every input shape
plus a no-I/O assertion. Offline, deterministic; every assertion is pinned against the as-built
module's live output.
"""

import copy
import os
import socket
import sys
from unittest import mock

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

_EMPTY_SLICE = {"dual_order_tasks": None, "disagreements": None, "disagreement_rate": None}


def _run(rate=0.1, dual=4, source="judge_report"):
    return {"composite_mean": 0.6, source: {"dual_order_tasks": dual, "disagreement_rate": rate}}


def _stats(dual, disagree, agree=0, tie=0):
    return {"dual_order_tasks": dual, "disagree": disagree, "agree": agree, "tie": tie}


def _partition_report(disagreements, dual):
    return {"judge_report": {
        "dual_order_tasks": dual,
        "disagreements": disagreements,
        "disagreement_rate": round(disagreements / dual, 3) if dual else None,
    }}


# --- Input coercion & number validity -------------------------------------------------------


def test_dict_helper_returns_dict_or_empty():
    assert _dict({"a": 1}) == {"a": 1}
    assert _dict(None) == {}
    assert _dict("nope") == {}
    assert _dict([1, 2]) == {}


def test_is_int_semantics():
    assert _is_int(3) is True
    assert _is_int(0) is True
    assert _is_int(True) is False       # bool is not an int here
    assert _is_int(2.5) is False
    assert _is_int(None) is False


def test_is_number_semantics():
    assert _is_number(0.6) is True
    assert _is_number(0) is True
    assert _is_number(True) is False
    assert _is_number(float("nan")) is False
    assert _is_number(float("inf")) is False
    assert _is_number("0.3") is False
    assert _is_number(10 ** 400) is False   # OverflowError inside isfinite -> rejected, not raised


# --- Disagreement counts --------------------------------------------------------------------


def test_counts_from_dual_and_disagree():
    assert _disagreement_counts({"dual_order_tasks": 10, "disagree": 8}) == (8, 10)
    # 'disagreements' (plural) is a fallback for 'disagree'.
    assert _disagreement_counts({"dual_order_tasks": 10, "disagreements": 3}) == (3, 10)


def test_counts_derive_dual_from_agree_disagree_tie():
    assert _disagreement_counts(_stats(dual=None, disagree=1, agree=3, tie=0)) == (1, 4)


def test_counts_derive_disagreements_from_rate():
    # Neither disagree nor disagreements present: derive round(rate * dual).
    assert _disagreement_counts({"dual_order_tasks": 4, "disagreement_rate": 0.5}) == (2, 4)


def test_counts_reject_invalid_or_negative():
    assert _disagreement_counts({"foo": 1}) is None            # nothing usable
    assert _disagreement_counts({"dual_order_tasks": 2.5, "disagree": 1}) is None   # non-int dual
    assert _disagreement_counts({"dual_order_tasks": -1, "disagree": 0}) is None    # negative dual
    assert _disagreement_counts({"dual_order_tasks": True, "disagree": 0}) is None  # bool dual
    assert _disagreement_counts("nope") is None                # non-dict coerced to {}


# --- Slice summary --------------------------------------------------------------------------


def test_slice_prefers_stats_over_stale_report():
    slice_ = {
        "judge_order_stats": _stats(dual=10, disagree=8, agree=2, tie=0),
        "judge_report": {"disagreement_rate": 0.05, "dual_order_tasks": 10},   # stale
    }
    assert _slice_summary(slice_) == {"dual_order_tasks": 10, "disagreements": 8,
                                      "disagreement_rate": 0.8}


def test_slice_falls_back_to_report_when_stats_absent_or_empty():
    report_only = {"judge_report": {"disagreement_rate": 0.25, "dual_order_tasks": 4}}
    expected = {"dual_order_tasks": 4, "disagreements": 1, "disagreement_rate": 0.25}
    assert _slice_summary(report_only) == expected
    assert _slice_summary({"judge_order_stats": {}, **report_only}) == expected


def test_slice_empty_when_no_usable_source():
    assert _slice_summary({}) == _EMPTY_SLICE
    assert _slice_summary({"judge_report": {"foo": 1}}) == _EMPTY_SLICE


def test_slice_non_dict_coerced():
    assert _slice_summary("nope") == _EMPTY_SLICE
    # A non-dict judge_order_stats is coerced to {} and skipped; the report is used.
    art = {"judge_order_stats": "nope", "judge_report": {"disagreement_rate": 0.1, "dual_order_tasks": 4}}
    assert _slice_summary(art) == {"dual_order_tasks": 4, "disagreements": 0, "disagreement_rate": 0.1}


# --- Overall summary: shape & kinds ---------------------------------------------------------


def test_result_always_includes_required_keys():
    for art in (_run(0.1, 5), [], {}, {"composite_mean": 0.5},
                {"generalization_gap": 0.0, "tuned": _partition_report(1, 4),
                 "held_out": _partition_report(2, 4)}):
        assert _REQUIRED_KEYS == frozenset(summarize_disagreement_outlook(art))


def test_single_and_multi_top_level_slice():
    single = summarize_disagreement_outlook(_run(0.1, 5))
    assert single["kind"] == "single"
    assert single["dual_order_tasks"] == 5
    assert single["disagreements"] == 0        # round(0.1 * 5) == 0
    assert single["disagreement_rate"] == 0.1
    assert single["verdict"] == "stable"
    assert single["partitions"] is None
    multi = summarize_disagreement_outlook(
        {"per_repo": [], "judge_report": {"dual_order_tasks": 4, "disagreement_rate": 0.1}})
    assert multi["kind"] == "multi"
    assert multi["partitions"] is None
    assert multi["dual_order_tasks"] == 4 and multi["disagreement_rate"] == 0.1


def test_non_dict_and_empty_artifact_are_invalid():
    for art in ([], "nope", 42, None, {}):
        out = summarize_disagreement_outlook(art)
        assert out["kind"] == "invalid"
        assert out["dual_order_tasks"] is None and out["disagreement_rate"] is None
        assert out["verdict"] is None and out["partitions"] is None
        assert out["stable_threshold"] == DEFAULT_STABLE_THRESHOLD


def test_missing_telemetry_yields_none_fields():
    out = summarize_disagreement_outlook({"composite_mean": 0.5})
    assert out["kind"] == "single"
    assert out["dual_order_tasks"] is None
    assert out["disagreements"] is None
    assert out["disagreement_rate"] is None
    assert out["verdict"] is None


# --- Overall summary: stats over stale report -----------------------------------------------


def test_summary_recomputes_stale_report_rate_from_stats():
    art = {
        "judge_report": {"disagreement_rate": 0.05, "dual_order_tasks": 10},   # stale
        "judge_order_stats": _stats(dual=10, disagree=8, agree=2, tie=0),
    }
    out = summarize_disagreement_outlook(art)
    assert out["disagreement_rate"] == 0.8
    assert out["disagreements"] == 8
    assert out["dual_order_tasks"] == 10
    assert out["verdict"] == "unstable"


# --- Overall summary: verdict & threshold ---------------------------------------------------


def test_verdict_stable_unstable_and_boundary():
    assert summarize_disagreement_outlook(_run(0.1, 5))["verdict"] == "stable"
    assert summarize_disagreement_outlook(_run(0.5, 3))["verdict"] == "unstable"
    # The boundary is inclusive: a rate equal to the default threshold (0.3) is stable.
    boundary = summarize_disagreement_outlook(_run(DEFAULT_STABLE_THRESHOLD, 2))
    assert boundary["disagreement_rate"] == 0.3
    assert boundary["verdict"] == "stable"


def test_custom_and_non_number_threshold_coercion():
    custom = summarize_disagreement_outlook(_run(0.25, 2), stable_threshold=0.2)
    assert custom["stable_threshold"] == 0.2
    assert custom["verdict"] == "unstable"        # 0.25 > 0.2
    # A non-number / non-finite threshold coerces to the default 0.3.
    for bad in ("x", float("nan"), None, float("inf")):
        out = summarize_disagreement_outlook(_run(0.1, 5), stable_threshold=bad)
        assert out["stable_threshold"] == DEFAULT_STABLE_THRESHOLD, bad
        assert out["verdict"] == "stable"


def test_non_finite_rate_yields_none_verdict():
    for bad in (float("nan"), float("inf"), float("-inf")):
        out = summarize_disagreement_outlook(_run(bad, 2))
        assert out["disagreement_rate"] is None, bad
        assert out["verdict"] is None, bad


# --- Combined outlook across partitions -----------------------------------------------------


def test_generalization_combined_sums_partitions():
    art = {"generalization_gap": 0.0, "tuned": _partition_report(1, 4),
           "held_out": _partition_report(2, 4)}
    out = summarize_disagreement_outlook(art)
    assert out["kind"] == "generalization"
    assert out["dual_order_tasks"] == 8
    assert out["disagreements"] == 3
    assert out["disagreement_rate"] == 0.375        # round(3 / 8, 3)
    assert out["verdict"] == "unstable"
    assert out["partitions"]["tuned"] == {"dual_order_tasks": 4, "disagreements": 1,
                                          "disagreement_rate": 0.25}
    assert out["partitions"]["held_out"] == {"dual_order_tasks": 4, "disagreements": 2,
                                             "disagreement_rate": 0.5}


def test_generalization_missing_partition_yields_none_overall():
    art = {"generalization_gap": None, "tuned": _partition_report(1, 4), "held_out": {}}
    out = summarize_disagreement_outlook(art)
    assert out["kind"] == "generalization"
    assert out["dual_order_tasks"] is None
    assert out["disagreement_rate"] is None
    assert out["verdict"] is None
    assert out["partitions"]["tuned"]["disagreement_rate"] == 0.25
    assert out["partitions"]["held_out"] == _EMPTY_SLICE


def test_generalization_zero_dual_partitions_yield_none():
    # A partition with dual_order_tasks == 0 has no derivable rate, so its slice is empty and the
    # overall outlook is all-None — not the _combined zero-dual branch (see the helper test below).
    zero = {"judge_report": {"dual_order_tasks": 0, "disagreements": 0, "disagreement_rate": None}}
    out = summarize_disagreement_outlook(
        {"generalization_gap": 0.0, "tuned": zero, "held_out": zero})
    assert out["kind"] == "generalization"
    assert out["dual_order_tasks"] is None
    assert out["partitions"]["tuned"] == _EMPTY_SLICE
    assert out["partitions"]["held_out"] == _EMPTY_SLICE


def test_combined_helper_zero_dual_branch():
    # Called directly (both partitions carry int counts summing to zero dual): division-by-zero is
    # avoided — dual 0, disagreements 0, rate None.
    combined = _combined({"dual_order_tasks": 0, "disagreements": 0},
                         {"dual_order_tasks": 0, "disagreements": 0})
    assert combined == {"dual_order_tasks": 0, "disagreements": 0, "disagreement_rate": None}


def test_combined_helper_incomplete_is_empty():
    assert _combined({"dual_order_tasks": None, "disagreements": None},
                     {"dual_order_tasks": 4, "disagreements": 2}) == _EMPTY_SLICE
    assert _combined({"dual_order_tasks": 4, "disagreements": 1},
                     {"dual_order_tasks": 4, "disagreements": 2}) == {
        "dual_order_tasks": 8, "disagreements": 3, "disagreement_rate": 0.375}


# --- Verdict helper -------------------------------------------------------------------------


def test_verdict_helper_direct():
    assert _verdict(None, 0.3) is None
    assert _verdict(float("nan"), 0.3) is None
    assert _verdict(0.2, 0.3) == "stable"
    assert _verdict(0.3, 0.3) == "stable"      # inclusive boundary
    assert _verdict(0.4, 0.3) == "unstable"


# --- Headline -------------------------------------------------------------------------------


def test_headline_single_line():
    line = disagreement_outlook_headline(summarize_disagreement_outlook(_run(0.2, 3)))
    assert line == "disagreement outlook: stable (rate 20.0%, 3 dual-order task(s))"


def test_headline_generalization_appends_partition_rates():
    art = {"generalization_gap": 0.0, "tuned": _partition_report(1, 4),
           "held_out": _partition_report(0, 4)}
    line = disagreement_outlook_headline(summarize_disagreement_outlook(art))
    assert line == ("disagreement outlook: stable (rate 12.5%, 8 dual-order task(s)) "
                    "[tuned 25.0%, held-out 0.0%]")


def test_headline_non_numeric_rate_and_non_dict():
    nan_line = disagreement_outlook_headline(summarize_disagreement_outlook(_run(float("nan"), 2)))
    assert nan_line == "disagreement outlook: unknown (rate n/a, n/a dual-order task(s))"
    # A non-dict summary is coerced to {} and renders the same all-unknown line, never raises.
    assert disagreement_outlook_headline("nope") == (
        "disagreement outlook: unknown (rate n/a, n/a dual-order task(s))")


# --- Pure evaluation ------------------------------------------------------------------------

_EVERY_SHAPE = [
    _run(0.1, 5),                                                              # single, well-formed
    {"per_repo": [], "judge_report": {"dual_order_tasks": 4, "disagreement_rate": 0.1}},   # multi
    {"generalization_gap": 0.0, "tuned": _partition_report(1, 4), "held_out": _partition_report(2, 4)},
    {"generalization_gap": None, "tuned": _partition_report(1, 4), "held_out": {}},
    {"composite_mean": 0.5},                                                   # missing telemetry
    _run(float("nan"), 2),                                                     # non-finite rate
    _run(0.1, -1),                                                             # negative dual
    {},                                                                        # empty / invalid
]


def test_summary_does_not_mutate_input_for_every_shape():
    for art in _EVERY_SHAPE:
        snapshot = copy.deepcopy(art)
        out = summarize_disagreement_outlook(art)
        disagreement_outlook_headline(out)
        assert art == snapshot, art
    # A non-dict artifact is untouched too.
    for art in ([1, 2, 3], "nope"):
        snap = copy.deepcopy(art)
        summarize_disagreement_outlook(art)
        assert art == snap, art


def test_summary_performs_no_io():
    # A pure-analysis contract: no file or socket is opened by summarize / headline.
    with mock.patch("builtins.open", side_effect=AssertionError("open() called")), \
            mock.patch.object(socket, "socket", side_effect=AssertionError("socket() called")):
        for art in _EVERY_SHAPE:
            disagreement_outlook_headline(summarize_disagreement_outlook(art))
