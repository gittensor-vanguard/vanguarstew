"""Contract tests for specs/066-benchmark-trend — assert trend.py satisfies the spec's EARS
criteria, including the tuned-partition rule and unscored placeholder six sibling gates
inherit, the unscored-bridge delta, threshold exclusivity, malformed series/entries, every
headline branch, and pure analysis. Offline, deterministic.

Expectations are pinned literals: no test derives its expected value by calling the function
under test, so a neutered implementation cannot satisfy this file.
"""

import copy
import logging
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from benchmark.trend import (  # noqa: E402
    DEFAULT_REGRESSION_THRESHOLD,
    _is_number,
    _round,
    _trend_point,
    _trend_regressions,
    _trend_series,
    headline_score,
    trend,
    trend_headline,
)

_REQUIRED_KEYS = frozenset({
    "points", "scored", "total", "first", "last", "change", "min", "max",
    "regressions", "regression_threshold",
})


def _pt(label, score):
    return (label, {"composite_mean": score})


# --- Headline score extraction --------------------------------------------------------------
# The contract regression / improvement / gap_outlook / artifact_snapshot / repeatability /
# leaderboard all inherit instead of re-implementing (Spec 016 says so explicitly).


def test_headline_score_non_dict_is_none():
    for artifact in (None, [], "x", 5, 0.5, True, {"a"}):
        assert headline_score(artifact) is None


def test_tuned_source_requires_both_partitions_to_be_dicts():
    both = {"tuned": {"composite_mean": 0.7}, "held_out": {"composite_mean": 0.5},
            "composite_mean": 0.9}
    assert headline_score(both) == 0.7

    # A tuned partition alone, or a non-dict held_out, falls through to the TOP level.
    assert headline_score({"tuned": {"composite_mean": 0.7}, "composite_mean": 0.9}) == 0.9
    assert headline_score(
        {"tuned": {"composite_mean": 0.7}, "held_out": 5, "composite_mean": 0.9}
    ) == 0.9
    assert headline_score(
        {"tuned": 5, "held_out": {"composite_mean": 0.5}, "composite_mean": 0.9}
    ) == 0.9


def test_zero_scored_repos_placeholder_is_unscored():
    for zero in (0, 0.0, -0.0):
        assert headline_score({"composite_mean": 0.5, "scored_repos": zero}) is None
    # The placeholder rule reads the SOURCE partition, not the top level.
    assert headline_score({
        "tuned": {"composite_mean": 0.7, "scored_repos": 0},
        "held_out": {"composite_mean": 0.5},
    }) is None


def test_bool_negative_and_string_scored_repos_keep_the_score():
    # _is_number excludes bool, so False is not "a number that is falsey".
    for kept in (False, True, -1, "0", None):
        assert headline_score({"composite_mean": 0.5, "scored_repos": kept}) == 0.5
    assert headline_score({"composite_mean": 0.5}) == 0.5


def test_composite_mean_rounded_to_three_places():
    assert headline_score({"composite_mean": 0.6666666}) == 0.667
    assert headline_score({"composite_mean": 1}) == 1.0
    for bad in (float("nan"), float("inf"), float("-inf"), True, "0.5", None, [], 2 ** 2000):
        assert headline_score({"composite_mean": bad}) is None


def test_genuine_zero_composite_is_kept():
    # 0.0 with no zero scored_repos is a real score, not "unscored".
    assert headline_score({"composite_mean": 0.0}) == 0.0
    assert headline_score({"composite_mean": 0.0, "scored_repos": 3}) == 0.0


# --- Trend summary --------------------------------------------------------------------------


def test_summary_always_includes_required_keys():
    for series in ([], None, "nonsense", [_pt("a", 0.5)]):
        assert frozenset(trend(series)) == _REQUIRED_KEYS


def test_points_deltas_and_counts():
    summary = trend([_pt("a", 0.500), _pt("b", 0.600), _pt("c", 0.550)])
    assert summary["points"] == [
        {"label": "a", "composite_mean": 0.5, "delta": None},
        {"label": "b", "composite_mean": 0.6, "delta": 0.1},
        {"label": "c", "composite_mean": 0.55, "delta": -0.05},
    ]
    assert (summary["scored"], summary["total"]) == (3, 3)
    assert (summary["first"], summary["last"], summary["change"]) == (0.5, 0.55, 0.05)
    assert (summary["min"], summary["max"]) == (0.5, 0.6)


def test_unscored_point_bridges_the_delta():
    # The middle point has no usable score: it contributes None and the NEXT scored point is
    # measured against 0.6, not against the gap.
    summary = trend([_pt("a", 0.6), ("b", {"composite_mean": "bad"}), _pt("c", 0.5)], 0.05)
    assert [p["composite_mean"] for p in summary["points"]] == [0.6, None, 0.5]
    assert [p["delta"] for p in summary["points"]] == [None, None, -0.1]
    assert (summary["scored"], summary["total"]) == (2, 3)
    assert summary["regressions"] == [{"from_label": "a", "to_label": "c", "drop": 0.1}]


def test_empty_series_summary_is_all_none():
    summary = trend([])
    assert (summary["scored"], summary["total"]) == (0, 0)
    for key in ("first", "last", "change", "min", "max"):
        assert summary[key] is None
    assert summary["points"] == [] and summary["regressions"] == []


def test_non_finite_subtraction_yields_none_delta_and_change():
    # Two FINITE scores can subtract to a non-finite result: -1e308 - 1e308 == -inf. The
    # _round guard keeps an inf out of the summary, so delta/change are None even though both
    # points are scored.
    assert _round(-1e308 - 1e308) is None
    assert _round(0.6666666) == 0.667
    summary = trend([_pt("a", -1e308), _pt("b", 1e308)])
    assert summary["scored"] == 2
    assert [p["delta"] for p in summary["points"]] == [None, None]
    assert summary["change"] is None
    assert (summary["first"], summary["last"]) == (-1e308, 1e308)


def test_single_scored_point_change_is_zero():
    # first and last are the same point, so change is 0.0 — NOT None.
    summary = trend([_pt("only", 0.5)])
    assert summary["change"] == 0.0
    assert (summary["first"], summary["last"]) == (0.5, 0.5)
    assert summary["points"][0]["delta"] is None


def test_regressions_shape_and_drop_sign():
    summary = trend([_pt("a", 0.90), _pt("b", 0.60), _pt("c", 0.80)], 0.05)
    assert summary["regressions"] == [{"from_label": "a", "to_label": "b", "drop": 0.3}]


def test_drop_equal_to_threshold_is_not_a_regression():
    # 0.60 - 0.58 == 0.02000000000000002 in binary float; the round(...,3) before the
    # comparison is what keeps an exactly-at-threshold drop from being flagged.
    series = [_pt("a", 0.60), _pt("b", 0.58)]
    assert trend(series, 0.02)["regressions"] == []
    assert trend(series, 0.019)["regressions"] == [
        {"from_label": "a", "to_label": "b", "drop": 0.02}
    ]


def test_regression_threshold_is_echoed_and_unvalidated():
    assert trend([], 0.5)["regression_threshold"] == 0.5
    assert trend([_pt("a", 0.5)], "not-a-number")["regression_threshold"] == "not-a-number"
    # Two scored points reach the comparison, which is where a bad threshold surfaces.
    try:
        trend([_pt("a", 0.6), _pt("b", 0.5)], None)
    except TypeError:
        pass
    else:
        raise AssertionError("expected TypeError from an unvalidated None threshold")


# --- Series and entry sanitation ------------------------------------------------------------


def test_non_list_series_is_empty_and_none_is_silent(caplog):
    pairs = [_pt("a", 0.5), _pt("b", 0.6)]
    # A list check, not an iterable check: a tuple/generator of well-formed pairs is empty.
    for container in (tuple(pairs), (p for p in pairs), "ab", 5, {"a": 1}):
        assert _trend_series(container) == []
    assert _trend_series(pairs) is pairs

    caplog.clear()
    with caplog.at_level(logging.WARNING, logger="benchmark.trend"):
        assert _trend_series((1, 2)) == []
    assert [r.levelno for r in caplog.records] == [logging.WARNING]
    assert "not a list" in caplog.text and "tuple" in caplog.text

    caplog.clear()
    assert _trend_series(None) == []
    assert caplog.records == []


def test_entry_must_be_a_two_element_sequence(caplog):
    assert _trend_point(("a", {})) == ("a", {})
    assert _trend_point(["a", {}]) == ("a", {})
    # str/bytes of length 2 are iterable and would unpack character-wise — they must be skipped.
    for bad in (("a",), ("a", {}, 1), "ab", b"ab", None, 5, {"a": 1}, {"a", "b"}, []):
        assert _trend_point(bad) is None

    # The warning must render the offending entry with %r so the bad entry can be located:
    # repr distinguishes the string "ab" from a two-element pair, which %s would not.
    caplog.clear()
    with caplog.at_level(logging.WARNING, logger="benchmark.trend"):
        assert _trend_point("ab") is None
    assert [r.levelno for r in caplog.records] == [logging.WARNING]
    assert "'ab'" in caplog.text


def test_malformed_entry_does_not_abort_the_series():
    summary = trend([_pt("a", 0.5), "junk", None, _pt("b", 0.6)])
    assert (summary["scored"], summary["total"]) == (2, 2)
    assert [p["label"] for p in summary["points"]] == ["a", "b"]


# --- Numeric guard and constants ------------------------------------------------------------


def test_is_number_rejects_bool_non_finite_and_non_numeric():
    for good in (0, 1, -1, 0.5, -0.5, 0.0):
        assert _is_number(good) is True
    for bad in (True, False, float("nan"), float("inf"), float("-inf"), "1", None, [], {}):
        assert _is_number(bad) is False


def test_is_number_returns_false_for_oversized_int():
    # math.isfinite raises OverflowError on an int too large for a float; it must be caught.
    assert _is_number(2 ** 2000) is False


def test_default_regression_threshold_value():
    assert DEFAULT_REGRESSION_THRESHOLD == 0.02


# --- Trend headline -------------------------------------------------------------------------


def test_headline_no_scored_artifacts():
    for summary in (None, "x", 5, [], {}, {"scored": 0}, {"scored": None}):
        assert trend_headline(summary) == "trend: no scored artifacts"


def test_headline_arrow_and_change_formatting():
    assert trend_headline({"scored": 2, "change": 0.1, "first": 0.5, "last": 0.6,
                           "regressions": []}) == (
        "trend: 0.5 -> 0.6 (up +0.100) over 2 scored point(s); 0 regression(s)"
    )
    assert trend_headline({"scored": 2, "change": -0.1, "first": 0.6, "last": 0.5,
                           "regressions": [{}]}) == (
        "trend: 0.6 -> 0.5 (down -0.100) over 2 scored point(s); 1 regression(s)"
    )
    assert trend_headline({"scored": 2, "change": 0.0, "first": 0.5, "last": 0.5,
                           "regressions": []}) == (
        "trend: 0.5 -> 0.5 (flat +0.000) over 2 scored point(s); 0 regression(s)"
    )


def test_headline_non_numeric_change_renders_n_a():
    # Non-numeric change keeps the arrow at its "flat" default and renders n/a.
    assert trend_headline({"scored": 1, "change": None, "first": 0.5, "last": 0.5}) == (
        "trend: 0.5 -> 0.5 (flat n/a) over 1 scored point(s); 0 regression(s)"
    )


def test_headline_tolerates_non_list_regressions(caplog):
    assert _trend_regressions([{"drop": 0.1}]) == [{"drop": 0.1}]
    for bad in ("x", 5, {"a": 1}):
        assert _trend_regressions(bad) == []

    caplog.clear()
    with caplog.at_level(logging.WARNING, logger="benchmark.trend"):
        assert _trend_regressions("x") == []
    assert [r.levelno for r in caplog.records] == [logging.WARNING]
    assert "not a list" in caplog.text and "str" in caplog.text

    caplog.clear()
    assert _trend_regressions(None) == []
    assert caplog.records == []
    assert trend_headline({"scored": 1, "change": 0.0, "first": 0.5, "last": 0.5,
                           "regressions": "x"}).endswith("0 regression(s)")


# --- Pure analysis --------------------------------------------------------------------------


def test_trend_does_not_mutate_or_copy_its_inputs():
    artifact = {"composite_mean": 0.5, "tuned": {"composite_mean": 0.7},
                "held_out": {"composite_mean": 0.4}}
    series = [("a", artifact)]
    before = copy.deepcopy(artifact)
    tuned_identity = artifact["tuned"]

    trend(series)

    assert artifact == before
    assert len(series) == 1
    # Read in place: the caller's nested partition object keeps its identity.
    assert artifact["tuned"] is tuned_identity
