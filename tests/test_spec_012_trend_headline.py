"""Contract tests for specs/012-benchmark-trend-headline — assert benchmark/trend.py satisfies
the spec's EARS criteria: number validity, headline_score across single / multi / generalization
artifacts and the ``scored_repos: 0`` placeholder, the rounding mode (round-half-to-even), series /
entry coercion, the trend summary (points, deltas, first/last, min/max, regressions, and the
endpoint-only-scored bridging path), the one-line headline, and pure evaluation — deep non-mutation
across every input shape plus a no-I/O assertion. Offline, deterministic; every assertion is pinned
against the as-built module's live output.
"""

import copy
import os
import socket
import sys
from unittest import mock

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
    "points",
    "scored",
    "total",
    "first",
    "last",
    "change",
    "min",
    "max",
    "regressions",
    "regression_threshold",
})


def _single(score):
    return {"composite_mean": score}


def _multi(score, scored_repos=2):
    return {"per_repo": [], "scored_repos": scored_repos, "composite_mean": score}


def _gen(tuned_score, held=0.5):
    return {
        "tuned": {"composite_mean": tuned_score, "scored_repos": 3},
        "held_out": {"composite_mean": held, "scored_repos": 2},
        "generalization_gap": 0.1,
    }


# --- Number validity (_is_number) -----------------------------------------------------------


def test_is_number_accepts_only_finite_non_bool_numbers():
    assert _is_number(0.6) is True
    assert _is_number(0) is True
    assert _is_number(-1.5) is True
    assert _is_number(True) is False
    assert _is_number(False) is False
    assert _is_number("0.6") is False
    assert _is_number(None) is False
    assert _is_number([1]) is False
    assert _is_number(float("nan")) is False
    assert _is_number(float("inf")) is False
    assert _is_number(float("-inf")) is False


def test_is_number_rejects_oversized_int_without_raising():
    # math.isfinite raises OverflowError for an int too large for a float; it is rejected, not raised.
    assert _is_number(10 ** 400) is False


# --- Headline score -------------------------------------------------------------------------


def test_headline_single_and_multi_read_top_level():
    assert headline_score(_single(0.62)) == 0.62
    assert headline_score({"per_repo": [], "composite_mean": 0.4}) == 0.4


def test_headline_generalization_uses_tuned():
    # tuned = 0.71, held_out = 0.5: the headline is the tuned partition's score.
    assert headline_score(_gen(0.71)) == 0.71


def test_headline_non_dict_is_none():
    for bad in ("not a dict", 42, None, [1, 2], 0.5):
        assert headline_score(bad) is None, bad


def test_headline_missing_or_non_numeric_is_none():
    assert headline_score({}) is None
    assert headline_score({"error": "no tasks"}) is None
    assert headline_score({"composite_mean": "bad"}) is None
    assert headline_score({"composite_mean": None}) is None


def test_headline_rounds_to_three_decimals():
    assert headline_score(_single(2 / 3)) == 0.667
    assert headline_score(_single(-0.25)) == -0.25


def test_headline_scored_repos_zero_placeholder_is_unscored():
    # An aggregate run that scored no repos carries a placeholder composite_mean of 0.0; it is
    # unscored, not a real zero — top level and the tuned partition alike.
    assert headline_score(_multi(0.0, scored_repos=0)) is None
    unscored_gen = {
        "tuned": {"scored_repos": 0, "composite_mean": 0.0},
        "held_out": {"composite_mean": 0.5},
        "generalization_gap": 0.1,
    }
    assert headline_score(unscored_gen) is None
    # A scored aggregate is unaffected.
    assert headline_score(_multi(0.62, scored_repos=2)) == 0.62


def test_headline_genuine_zero_is_preserved():
    # A single-repo artifact has no scored_repos key: a genuine 0.0 stays 0.0.
    assert headline_score(_single(0.0)) == 0.0


def test_headline_non_finite_composite_is_unscored():
    for bad in (float("nan"), float("inf"), float("-inf")):
        assert headline_score(_single(bad)) is None, bad
        assert headline_score(_gen(bad)) is None, bad


# --- Rounding mode (round-half-to-even / banker's rounding, per Python built-in round) -------


def test_rounding_mode_is_round_half_to_even():
    # The mode headline_score / _round / the regression drop all use is the Python built-in
    # round(), documented as round-half-to-even ("banker's rounding"). On an EXACT binary
    # half-tie it resolves to the even last digit — this is the defining, unambiguous property
    # of the mode. Halves are exactly representable, so these are true ties:
    assert round(0.5, 0) == 0.0    # -> 0 (even), not 1
    assert round(1.5, 0) == 2.0    # -> 2 (even)
    assert round(2.5, 0) == 2.0    # -> 2 (even), NOT 3 — the banker's-rounding tell
    assert round(3.5, 0) == 4.0    # -> 4 (even)


def test_headline_score_rounding_ties_pinned():
    # headline_score(composite_mean) == round(float(composite_mean), 3). At 3-decimal precision a
    # decimal "...5" literal is almost never an exact binary tie (it can't be stored exactly as a
    # float), so it rounds toward whichever 3-decimal neighbour it is actually nearer rather than
    # by the even-digit rule. Each output below is pinned against the LIVE as-built function, so
    # the tie behavior is fixed and reproducible — no ambiguity on values like 0.0005.
    ties = {
        0.0005: 0.001,    # positive tie: 0.0005 stored just above the midpoint -> rounds up
        0.0015: 0.002,
        0.6125: 0.613,
        0.6135: 0.614,
        0.1235: 0.123,    # tie: 0.1235 stored just below the midpoint -> rounds down
        0.1245: 0.124,
        0.2405: 0.24,
        0.2415: 0.241,
        -0.0005: -0.001,  # negative tie: rounds away from zero, to -0.001
        -0.1235: -0.123,
        -0.1245: -0.124,
    }
    for value, expected in ties.items():
        got = headline_score({"composite_mean": value})
        assert got == expected, (value, expected, got)
        # And headline_score IS exactly Python's round to 3 places — the as-built contract.
        assert got == round(float(value), 3), (value, got)


def test_round_helper_ties_pinned():
    # The same rounding governs _round, which produces the delta / change / per-point values.
    assert _round(0.1235) == 0.123
    assert _round(0.1245) == 0.124
    assert _round(-0.1245) == -0.124
    assert _round(0.0005) == 0.001
    assert _round(-0.0005) == -0.001


# --- Series coercion ------------------------------------------------------------------------

_MALFORMED_SERIES = [42, 3.14, True, {"label": "run1"}, "not a list"]


def test_trend_series_accepts_only_lists():
    rows = [("run1", _single(0.5))]
    assert _trend_series(rows) == rows
    assert _trend_series(None) == []            # None -> empty, no warning
    for bad in _MALFORMED_SERIES:
        assert _trend_series(bad) == [], bad


class _Weird:
    """A custom object that is not a (label, artifact) pair."""


_MALFORMED_ENTRIES = [
    42, 3.14, True, None,
    "ab",                     # str: iterable, would unpack char-wise
    b"ab",                    # bytes: iterable, would unpack byte-wise
    (),                       # empty tuple
    ("only-one",),            # 1-element
    ("a", "b", "c"),          # 3-element
    ["a", "b", "c"],
    {"label": "run1"},        # dict (not a pair)
    _Weird(),
]


def test_trend_point_accepts_only_two_element_pairs():
    assert _trend_point(("r1", _single(0.5))) == ("r1", {"composite_mean": 0.5})
    assert _trend_point(["r1", _single(0.5)]) == ("r1", {"composite_mean": 0.5})
    for bad in _MALFORMED_ENTRIES:
        assert _trend_point(bad) is None, bad


def test_non_list_series_yields_empty_summary():
    for bad in _MALFORMED_SERIES:
        out = trend(bad)
        assert out["points"] == [] and out["scored"] == 0 and out["total"] == 0, bad
        assert out["regressions"] == []


def test_malformed_entries_are_skipped_not_unpacked():
    # A well-formed point on each side of every malformed entry; only the two real points count,
    # and a 2-char string is never unpacked into a bogus (label, artifact) pair.
    series = [("a", _single(0.5))] + _MALFORMED_ENTRIES + [("b", _single(0.6))]
    out = trend(series)
    assert out["total"] == 2 and out["scored"] == 2
    assert [p["label"] for p in out["points"]] == ["a", "b"]
    assert out["first"] == 0.5 and out["last"] == 0.6 and out["change"] == 0.1


# --- Trend summary --------------------------------------------------------------------------


def test_result_always_includes_required_keys():
    for series in ([("r1", _single(0.5))], [], 42, [("a", {"error": "x"})]):
        assert _REQUIRED_KEYS == frozenset(trend(series))


def test_points_deltas_and_overall_change():
    out = trend([("r1", _single(0.50)), ("r2", _single(0.55)), ("r3", _single(0.53))])
    assert [p["composite_mean"] for p in out["points"]] == [0.50, 0.55, 0.53]
    assert out["points"][0]["delta"] is None            # first scored point has no delta
    assert out["points"][1]["delta"] == 0.05
    assert out["points"][2]["delta"] == -0.02
    assert out["first"] == 0.50 and out["last"] == 0.53
    assert out["change"] == 0.03                         # signed last - first
    assert out["min"] == 0.50 and out["max"] == 0.55     # range is independent of change
    assert out["scored"] == 3 and out["total"] == 3


def test_delta_bridges_across_unscored_points():
    # The middle artifact has no score: its own delta is None and it is skipped, so the next
    # scored point's delta bridges to the previous scored point (0.60 -> 0.50 = -0.10).
    out = trend([("a", _single(0.60)), ("b", {"error": "x"}), ("c", _single(0.50))])
    assert out["points"][1]["composite_mean"] is None
    assert out["points"][1]["delta"] is None
    assert out["points"][2]["delta"] == -0.10
    assert out["scored"] == 2 and out["total"] == 3
    assert [r["from_label"] for r in out["regressions"]] == ["a"]   # a -> c drop 0.10


def test_first_last_use_scored_values_only():
    # Leading and trailing unscored points do not become first/last; the scored values do.
    out = trend([("lead", {"error": "x"}), ("a", _single(0.5)), ("b", _single(0.6)),
                 ("trail", {"error": "y"})])
    assert out["first"] == 0.5 and out["last"] == 0.6
    assert out["scored"] == 2 and out["total"] == 4
    assert out["change"] == 0.1


def test_min_max_range_independent_of_endpoints():
    # min/max span ALL scored points, not just the endpoints: a mid-series spike (0.70) and dip
    # (0.30) are captured even though neither is first (0.50) nor last (0.55). change stays the
    # signed last - first (0.05), independent of the range. Pinned against live output.
    out = trend([("a", _single(0.50)), ("b", _single(0.70)), ("c", _single(0.30)),
                 ("d", _single(0.55))])
    assert [p["delta"] for p in out["points"]] == [None, 0.20, -0.40, 0.25]
    assert out["first"] == 0.50 and out["last"] == 0.55
    assert out["min"] == 0.30 and out["max"] == 0.70   # both mid-series, not endpoints
    assert out["change"] == 0.05                        # signed, independent of min/max
    assert out["regressions"] == [{"from_label": "b", "to_label": "c", "drop": 0.40}]


def test_empty_series_summary():
    out = trend([])
    assert out["points"] == [] and out["scored"] == 0 and out["total"] == 0
    assert out["first"] is None and out["last"] is None and out["change"] is None
    assert out["min"] is None and out["max"] is None and out["regressions"] == []
    assert out["regression_threshold"] == DEFAULT_REGRESSION_THRESHOLD


def test_single_scored_point_has_no_delta():
    out = trend([("only", _single(0.5))])
    assert out["scored"] == 1
    assert out["points"][0]["delta"] is None
    assert out["change"] == 0.0            # first == last
    assert out["regressions"] == []


def test_regression_only_beyond_threshold():
    # 0.60 -> 0.61 (up) -> 0.50 (drop 0.11 > 0.02, regression) -> 0.495 (drop 0.005, no regression).
    out = trend([("a", _single(0.60)), ("b", _single(0.61)), ("c", _single(0.50)),
                 ("d", _single(0.495))])
    assert out["regressions"] == [{"from_label": "b", "to_label": "c", "drop": 0.11}]
    assert out["change"] == -0.105


def test_regression_drop_exactly_at_threshold_is_not_flagged():
    # The threshold is strict (> not >=): a drop equal to it is noise, not a slide.
    out = trend([("a", _single(0.60)), ("b", _single(0.58))], regression_threshold=0.02)
    assert out["regressions"] == []


def test_regression_threshold_is_configurable_and_echoed():
    series = [("a", _single(0.60)), ("b", _single(0.57))]      # drop 0.03
    flagged = trend(series, regression_threshold=0.02)
    assert flagged["regressions"] == [{"from_label": "a", "to_label": "b", "drop": 0.03}]
    assert flagged["regression_threshold"] == 0.02
    relaxed = trend(series, regression_threshold=0.05)
    assert relaxed["regressions"] == [] and relaxed["regression_threshold"] == 0.05


def test_round_helper():
    assert _round(0.12345) == 0.123
    assert _round(1) == 1.0
    assert _round("bad") is None
    assert _round(float("nan")) is None


# --- Trend summary: endpoint-only-scored series (regression bridging) ------------------------


def test_regression_detected_across_endpoint_only_scored_series():
    # Only the FIRST and LAST points carry a score; every intermediate point is an unscored error
    # artifact. The delta/regression math must bridge the unscored middle as a single step: the
    # last point's delta is last - first, and the drop is reported ONCE, labelled with the two
    # SCORED endpoints (a -> d), not the unscored neighbours. Pinned against live output.
    series = [("a", _single(0.60)), ("b", {"error": "x"}),
              ("c", {"error": "y"}), ("d", _single(0.50))]
    out = trend(series)
    assert [p["composite_mean"] for p in out["points"]] == [0.60, None, None, 0.50]
    assert [p["delta"] for p in out["points"]] == [None, None, None, -0.10]
    assert out["scored"] == 2 and out["total"] == 4
    assert out["first"] == 0.60 and out["last"] == 0.50
    assert out["change"] == -0.10
    assert out["min"] == 0.50 and out["max"] == 0.60
    assert out["regressions"] == [{"from_label": "a", "to_label": "d", "drop": 0.10}]
    assert trend_headline(out) == (
        "trend: 0.6 -> 0.5 (down -0.100) over 2 scored point(s); 1 regression(s)"
    )


def test_endpoint_only_scored_rise_has_no_regression():
    # Same endpoint-only shape (three unscored points in the middle) but the last point RISES:
    # the bridged delta is positive, so no regression is flagged. Pinned against live output.
    series = [("a", _single(0.50)), ("b", {"error": "x"}), ("c", {"error": "y"}),
              ("d", {"error": "z"}), ("e", _single(0.60))]
    out = trend(series)
    assert [p["composite_mean"] for p in out["points"]] == [0.50, None, None, None, 0.60]
    assert out["points"][-1]["delta"] == 0.10
    assert out["scored"] == 2 and out["total"] == 5
    assert out["first"] == 0.50 and out["last"] == 0.60 and out["change"] == 0.10
    assert out["min"] == 0.50 and out["max"] == 0.60
    assert out["regressions"] == []


def test_two_scored_endpoints_minimal():
    # [scored, scored]: the minimal endpoint-scored series — a direct a -> b regression.
    out = trend([("a", _single(0.60)), ("b", _single(0.50))])
    assert out["scored"] == 2 and out["total"] == 2
    assert out["points"][0]["delta"] is None
    assert out["points"][1]["delta"] == -0.10
    assert out["first"] == 0.60 and out["last"] == 0.50 and out["change"] == -0.10
    assert out["min"] == 0.50 and out["max"] == 0.60
    assert out["regressions"] == [{"from_label": "a", "to_label": "b", "drop": 0.10}]


def test_scored_then_unscored_endpoint():
    # [scored, unscored]: a trailing unscored point contributes a None point but does not change
    # first/last/change or add a regression; only the single scored point counts.
    out = trend([("a", _single(0.60)), ("b", {"error": "x"})])
    assert out["scored"] == 1 and out["total"] == 2
    assert out["points"][1]["composite_mean"] is None and out["points"][1]["delta"] is None
    assert out["first"] == 0.60 and out["last"] == 0.60 and out["change"] == 0.0
    assert out["min"] == 0.60 and out["max"] == 0.60
    assert out["regressions"] == []


def test_unscored_then_scored_endpoint():
    # [unscored, scored]: a leading unscored point is bridged; the single scored point is both
    # first and last, with no delta and no regression.
    out = trend([("a", {"error": "x"}), ("b", _single(0.60))])
    assert out["scored"] == 1 and out["total"] == 2
    assert out["points"][0]["composite_mean"] is None and out["points"][0]["delta"] is None
    assert out["points"][1]["delta"] is None
    assert out["first"] == 0.60 and out["last"] == 0.60 and out["change"] == 0.0
    assert out["min"] == 0.60 and out["max"] == 0.60
    assert out["regressions"] == []


# --- Trend headline -------------------------------------------------------------------------


def test_headline_line_up_down_flat():
    up = trend_headline(trend([("a", _single(0.50)), ("b", _single(0.60))]))
    assert up == "trend: 0.5 -> 0.6 (up +0.100) over 2 scored point(s); 0 regression(s)"
    down = trend_headline(trend([("a", _single(0.60)), ("b", _single(0.50))]))
    assert down == "trend: 0.6 -> 0.5 (down -0.100) over 2 scored point(s); 1 regression(s)"
    flat = trend_headline(trend([("a", _single(0.50)), ("b", _single(0.50))]))
    assert flat == "trend: 0.5 -> 0.5 (flat +0.000) over 2 scored point(s); 0 regression(s)"


def test_headline_line_no_scored_artifacts():
    assert trend_headline(trend([])) == "trend: no scored artifacts"
    assert trend_headline({}) == "trend: no scored artifacts"
    assert trend_headline({"scored": 0}) == "trend: no scored artifacts"


def test_headline_line_non_dict_summary():
    for bad in ("nope", 42, None, [1, 2]):
        assert trend_headline(bad) == "trend: no scored artifacts", bad


def test_headline_line_non_numeric_change_is_na():
    # A summary whose change is non-numeric renders change as n/a and the arrow as flat.
    line = trend_headline({"scored": 1, "first": None, "last": None, "change": "bad",
                           "regressions": []})
    assert line == "trend: None -> None (flat n/a) over 1 scored point(s); 0 regression(s)"


def test_headline_line_non_list_regressions_counts_zero():
    base = {"scored": 2, "first": 0.5, "last": 0.6, "change": 0.1}
    assert _trend_regressions(None) == []
    for bad in (42, 3.14, True, {"from_label": "a"}, "not a list"):
        line = trend_headline({**base, "regressions": bad})
        assert line == "trend: 0.5 -> 0.6 (up +0.100) over 2 scored point(s); 0 regression(s)", bad


# --- Pure evaluation ------------------------------------------------------------------------

# Value-comparable malformed entries (drop the identity-only _Weird so deepcopy == holds; the
# _Weird skip path is covered by test_trend_point_accepts_only_two_element_pairs).
_MALFORMED_ENTRIES_VALUE = [e for e in _MALFORMED_ENTRIES if not isinstance(e, _Weird)]

_EVERY_SHAPE = [
    [("r1", _single(0.50)), ("r2", _single(0.55)), ("r3", _single(0.53))],   # well-formed
    [("a", _single(0.60)), ("b", {"error": "x"}), ("c", _single(0.50))],      # unscored middle
    [("a", _single(0.60)), ("b", {"error": "x"}), ("c", {"error": "y"}),      # endpoint-only-scored
     ("d", _single(0.50))],
    [("a", _single(float("nan"))), ("b", _multi(0.0, scored_repos=0)), ("c", _gen(0.6))],
    [("a", _single(0.5))] + _MALFORMED_ENTRIES_VALUE + [("b", _single(0.6))],  # malformed entries
    [],                                                                        # empty
    42,                                                                        # non-list series
]


def test_trend_does_not_mutate_input_for_every_shape():
    for series in _EVERY_SHAPE:
        snapshot = copy.deepcopy(series)
        trend(series)
        trend_headline(trend(series))
        assert series == snapshot, series
    # headline_score also leaves individual artifacts untouched.
    for artifact in (_single(0.5), _multi(0.0, scored_repos=0), _gen(0.6), {"error": "x"}):
        snap = copy.deepcopy(artifact)
        headline_score(artifact)
        assert artifact == snap, artifact


def test_trend_performs_no_io():
    # A pure-analysis contract: no file or socket is opened by headline_score / trend / trend_headline.
    series = [("a", _single(0.5)), ("b", _gen(0.6)), ("c", {"error": "x"})]
    with mock.patch("builtins.open", side_effect=AssertionError("open() called")), \
            mock.patch.object(socket, "socket", side_effect=AssertionError("socket() called")):
        for label, artifact in series:
            headline_score(artifact)
        summary = trend(series)
        trend_headline(summary)
