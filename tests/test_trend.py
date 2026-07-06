"""Tests for the N-way score trend / regression analysis (deterministic, offline)."""

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from benchmark.trend import (  # noqa: E402
    _trend_regressions,
    _trend_series,
    headline_score,
    trend,
    trend_headline,
)


def _single(score):
    return {"composite_mean": score, "composite_parts": {"judge_mean": score}}


def _gen(tuned_score):
    return {
        "tuned": {"composite_mean": tuned_score, "scored_repos": 3},
        "held_out": {"composite_mean": 0.5, "scored_repos": 2},
        "generalization_gap": 0.1,
    }


def test_headline_score_reads_top_level_and_generalization_tuned():
    assert headline_score(_single(0.62)) == 0.62
    assert headline_score({"per_repo": [], "composite_mean": 0.4}) == 0.4   # multi-repo
    assert headline_score(_gen(0.71)) == 0.71                               # tuned partition
    assert headline_score({"error": "no tasks"}) is None                    # no score
    assert headline_score("not a dict") is None                            # non-dict, no crash
    assert headline_score({"composite_mean": "bad"}) is None                # non-numeric


def test_headline_score_treats_unscored_tuned_partition_as_unscored():
    # A tuned partition that scored nothing (scored_repos: 0) reports a placeholder
    # composite_mean of 0.0 — a transient/infra outcome, not a real zero. It must read as None,
    # so --fail-on-regression doesn't raise a false alarm on an infra hiccup.
    unscored = {
        "tuned": {"error": "no tuned repos to replay", "scored_repos": 0, "composite_mean": 0.0},
        "held_out": {"composite_mean": 0.56, "scored_repos": 2},
        "generalization_gap": None,
    }
    assert headline_score(unscored) is None
    # The infra hiccup is skipped, so a healthy run before and after is NOT a 0.62 -> 0.0 -> 0.63
    # crash-and-recover; the two real scores compare directly with no spurious regression.
    out = trend([("run1", _gen(0.62)), ("run2", unscored), ("run3", _gen(0.63))])
    assert [p["composite_mean"] for p in out["points"]] == [0.62, None, 0.63]
    assert out["regressions"] == []


def test_trend_computes_points_deltas_and_overall_change():
    series = [("r1", _single(0.50)), ("r2", _single(0.55)), ("r3", _single(0.53))]
    out = trend(series)
    assert [p["composite_mean"] for p in out["points"]] == [0.50, 0.55, 0.53]
    assert out["points"][0]["delta"] is None            # first scored point has no delta
    assert out["points"][1]["delta"] == 0.05
    assert out["points"][2]["delta"] == -0.02
    assert out["first"] == 0.50 and out["last"] == 0.53
    assert out["change"] == 0.03
    assert out["min"] == 0.50 and out["max"] == 0.55
    assert out["scored"] == 3 and out["total"] == 3


def test_trend_flags_only_drops_beyond_the_threshold():
    # 0.60 -> 0.61 (up, no reg) -> 0.50 (drop 0.11 > 0.02, reg) -> 0.495 (drop 0.005 < 0.02, no reg)
    series = [("a", _single(0.60)), ("b", _single(0.61)), ("c", _single(0.50)), ("d", _single(0.495))]
    out = trend(series)
    assert [r["from_label"] for r in out["regressions"]] == ["b"]
    assert out["regressions"][0] == {"from_label": "b", "to_label": "c", "drop": 0.11}


def test_trend_threshold_is_configurable():
    series = [("a", _single(0.60)), ("b", _single(0.57))]   # drop 0.03
    assert trend(series, regression_threshold=0.02)["regressions"]      # 0.03 > 0.02 -> flagged
    assert not trend(series, regression_threshold=0.05)["regressions"]  # 0.03 < 0.05 -> not


def test_trend_skips_unscored_points_in_delta_and_regression_math():
    # The middle artifact has no score; deltas bridge the surrounding scored points, and its own
    # delta is None. 0.60 -> (skip) -> 0.50 is still a regression of 0.10.
    series = [("a", _single(0.60)), ("b", {"error": "no tasks"}), ("c", _single(0.50))]
    out = trend(series)
    assert out["points"][1]["composite_mean"] is None
    assert out["points"][1]["delta"] is None
    assert out["points"][2]["delta"] == -0.10          # bridges to the last scored point
    assert out["scored"] == 2 and out["total"] == 3
    assert [r["from_label"] for r in out["regressions"]] == ["a"]   # a -> c drop 0.10


def test_trend_empty_and_all_unscored_series():
    empty = trend([])
    assert empty["scored"] == 0 and empty["first"] is None and empty["regressions"] == []
    allbad = trend([("a", {"error": "x"}), ("b", "not-a-dict")])
    assert allbad["scored"] == 0 and allbad["change"] is None


# --- #528: a non-list series must not abort trend ------------------------------------

_MALFORMED_SERIES = [42, 3.14, True, {"label": "run1"}, "not a list"]


def test_trend_series_accepts_only_real_lists():
    rows = [("run1", {"composite_mean": 0.5})]
    for bad in _MALFORMED_SERIES:
        assert _trend_series(bad) == [], bad
    assert _trend_series(rows) == rows
    assert _trend_series(None) == []


def test_trend_survives_non_list_series():
    for bad in _MALFORMED_SERIES:
        out = trend(bad)
        assert out["scored"] == 0 and out["total"] == 0 and out["regressions"] == [], bad


def test_trend_logs_warning_for_non_list_series(caplog):
    import logging

    with caplog.at_level(logging.WARNING, logger="benchmark.trend"):
        out = trend(42)
    assert out["scored"] == 0
    assert any("series is int" in r.message for r in caplog.records)


def test_trend_headline_summarizes_direction_and_regressions():
    up = trend([("a", _single(0.50)), ("b", _single(0.60))])
    assert "up +0.100" in trend_headline(up) and "0 regression" in trend_headline(up)
    down = trend([("a", _single(0.60)), ("b", _single(0.50))])
    assert "down -0.100" in trend_headline(down) and "1 regression" in trend_headline(down)
    assert trend_headline({}) == "trend: no scored artifacts"


# --- #569: non-list regressions must not abort trend_headline ----------------------

_MALFORMED_REGRESSION_LISTS = [42, 3.14, True, {"from_label": "a"}, "not a list"]


def test_trend_regressions_accepts_only_real_lists():
    rows = [{"from_label": "a", "to_label": "b", "drop": 0.1}]
    for bad in _MALFORMED_REGRESSION_LISTS:
        assert _trend_regressions(bad) == [], bad
    assert _trend_regressions(rows) == rows
    assert _trend_regressions(None) == []


def test_trend_headline_survives_non_list_regressions():
    base = {"scored": 2, "first": 0.5, "last": 0.6, "change": 0.1}
    for bad in _MALFORMED_REGRESSION_LISTS:
        line = trend_headline({**base, "regressions": bad})
        assert "0 regression" in line, bad


def test_trend_headline_logs_warning_for_non_list_regressions(caplog):
    import logging

    summary = {"scored": 2, "first": 0.5, "last": 0.6, "change": 0.1, "regressions": 42}
    with caplog.at_level(logging.WARNING, logger="benchmark.trend"):
        line = trend_headline(summary)
    assert "0 regression" in line
    assert any("regressions is int" in r.message for r in caplog.records)


def test_trend_does_not_mutate_inputs():
    import copy
    series = [("a", _single(0.5)), ("b", _gen(0.6))]
    snapshot = copy.deepcopy(series)
    trend(series)
    assert series == snapshot


def test_trend_over_a_generalization_series_uses_tuned_score():
    # A series of --generalization artifacts trends on each one's tuned composite_mean.
    out = trend([("q1", _gen(0.60)), ("q2", _gen(0.64)), ("q3", _gen(0.58))])
    assert [p["composite_mean"] for p in out["points"]] == [0.60, 0.64, 0.58]
    assert out["change"] == -0.02
    assert [r["from_label"] for r in out["regressions"]] == ["q2"]     # 0.64 -> 0.58 drop 0.06


def test_trend_drop_exactly_at_threshold_is_not_a_regression():
    # The threshold is strict (> not >=): a drop equal to it is treated as noise, not a slide.
    out = trend([("a", _single(0.60)), ("b", _single(0.58))], regression_threshold=0.02)
    assert out["regressions"] == []


def test_trend_single_scored_point_has_no_delta_or_regression():
    out = trend([("only", _single(0.5))])
    assert out["scored"] == 1
    assert out["points"][0]["delta"] is None
    assert out["change"] == 0.0            # first == last
    assert out["regressions"] == []


def test_trend_mixes_single_multi_and_generalization_artifacts():
    series = [
        ("single", _single(0.50)),
        ("multi", {"per_repo": [], "composite_mean": 0.55}),
        ("gen", _gen(0.40)),
    ]
    out = trend(series)
    assert [p["composite_mean"] for p in out["points"]] == [0.50, 0.55, 0.40]
    assert out["min"] == 0.40 and out["max"] == 0.55
    assert [r["to_label"] for r in out["regressions"]] == ["gen"]      # 0.55 -> 0.40
