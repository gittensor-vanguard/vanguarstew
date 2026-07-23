"""Characterization tests for Spec 076 — the leaderboard ranking contract.

These pin the observable behaviour of :mod:`benchmark.leaderboard` (the N-way "pick the best"
view) so the Spec 076 acceptance criteria have executable teeth. Every asserted value was taken
from the live module, not hand-computed, so a drift in ranking, tie-handling, foresight
extraction, or malformed-input degradation trips a test here.

Scope note: ``rank`` extracts each entry's comparable score via
:func:`benchmark.trend.headline_score`. That helper's contract is exercised directly below (the
generalization-partition and ``scored_repos: 0`` cases) so the leaderboard's dependency on it is
pinned here rather than left implicit.
"""

import logging
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from benchmark.leaderboard import (  # noqa: E402
    _components,
    _is_number,
    _leaderboard_point,
    leaderboard_headline,
    rank,
)
from benchmark.trend import headline_score  # noqa: E402


def _art(composite_mean, judge=None, objective=None, foresight=None, scored_repos=None):
    """A minimal single-repo artifact with an optional composite_parts / foresight breakdown."""
    art = {"composite_mean": composite_mean}
    if judge is not None or objective is not None:
        art["composite_parts"] = {"judge_mean": judge, "objective_mean": objective}
    if foresight is not None:
        art["foresight"] = foresight
    if scored_repos is not None:
        art["scored_repos"] = scored_repos
    return art


# ---- ranking, ordering, ties ---------------------------------------------------------------


def test_ranks_best_first_with_delta_from_best():
    result = rank([("a", _art(0.9)), ("b", _art(0.5))])
    labels = [(row["rank"], row["label"], row["composite_mean"], row["delta_from_best"])
              for row in result["ranking"]]
    assert labels == [(1, "a", 0.9, 0.0), (2, "b", 0.5, -0.4)]
    assert result["best"] == {"label": "a", "composite_mean": 0.9}
    assert result["scored"] == 2
    assert result["total"] == 2
    assert result["unscored"] == []


def test_competition_ranking_ties_share_a_rank_and_the_next_rank_skips():
    # Two entries tied at 0.8 both rank 2, and the following entry jumps to rank 4 (1, 2, 2, 4).
    result = rank([("a", _art(0.9)), ("b", _art(0.8)), ("c", _art(0.8)), ("d", _art(0.5))])
    assert [row["rank"] for row in result["ranking"]] == [1, 2, 2, 4]
    assert [row["label"] for row in result["ranking"]] == ["a", "b", "c", "d"]


def test_ties_keep_input_order():
    # b and c both score 0.8; the ranking preserves the order they were given in.
    result = rank([("c", _art(0.8)), ("b", _art(0.8))])
    assert [row["label"] for row in result["ranking"]] == ["c", "b"]
    assert [row["rank"] for row in result["ranking"]] == [1, 1]


# ---- scored vs unscored partition ----------------------------------------------------------


def test_entries_with_no_usable_score_are_reported_unscored_never_ranked():
    result = rank([("ok", _art(0.9)), ("empty", _art(0.0, scored_repos=0)), ("bad", "not-a-dict")])
    assert [row["label"] for row in result["ranking"]] == ["ok"]
    assert result["unscored"] == ["empty", "bad"]
    assert result["scored"] == 1
    assert result["total"] == 3


def test_all_unscored_yields_no_best_and_empty_ranking():
    result = rank([("x", "not-a-dict"), ("y", {})])
    assert result["ranking"] == []
    assert result["best"] is None
    assert result["scored"] == 0
    assert result["total"] == 2
    assert result["unscored"] == ["x", "y"]


# ---- headline_score dependency contract (why an entry scores / doesn't) ---------------------


def test_headline_score_reads_top_level_composite_for_plain_artifacts():
    assert headline_score(_art(0.65)) == 0.65
    assert headline_score("not-a-dict") is None


def test_headline_score_uses_the_tuned_partition_for_a_generalization_artifact():
    gen = {"tuned": {"composite_mean": 0.7}, "held_out": {"composite_mean": 0.6}}
    assert headline_score(gen) == 0.7


def test_headline_score_treats_a_zero_scored_repos_aggregate_as_unscored():
    # scored_repos: 0 carries a placeholder composite_mean of 0.0, not a real score.
    assert headline_score(_art(0.0, scored_repos=0)) is None


def test_generalization_artifact_ranks_on_its_tuned_components():
    gen = {
        "tuned": {"composite_mean": 0.7,
                  "composite_parts": {"judge_mean": 0.8, "objective_mean": 0.6}},
        "held_out": {"composite_mean": 0.6},
    }
    row = rank([("g", gen)])["ranking"][0]
    assert row["composite_mean"] == 0.7
    assert row["judge_mean"] == 0.8
    assert row["objective_mean"] == 0.6


# ---- component + foresight breakdown --------------------------------------------------------


def test_components_expose_the_m7_foresight_axes_rounded_to_three_places():
    foresight = {"module_recall_mean": 0.667, "kind_recall_mean": 1.0,
                 "release_accuracy": 0.0, "bump_accuracy": 0.5}
    row = rank([("a", _art(0.5, judge=0.6, objective=0.4, foresight=foresight))])["ranking"][0]
    assert row["judge_mean"] == 0.6
    assert row["objective_mean"] == 0.4
    assert row["module_recall_mean"] == 0.667
    assert row["kind_recall_mean"] == 1.0
    assert row["release_accuracy"] == 0.0
    assert row["bump_accuracy"] == 0.5


def test_components_default_every_axis_to_none_when_absent():
    assert _components({}) == {
        "judge_mean": None, "objective_mean": None, "module_recall_mean": None,
        "kind_recall_mean": None, "release_accuracy": None, "bump_accuracy": None,
    }


def test_components_on_a_non_dict_artifact_return_all_none():
    assert all(value is None for value in _components("not-a-dict").values())


# ---- _is_number edges (each isolated so a partial regression is pinpointable) --------------


def test_is_number_rejects_nan():
    assert _is_number(float("nan")) is False


def test_is_number_rejects_infinity():
    assert _is_number(float("inf")) is False


def test_is_number_rejects_bool():
    # bool is an int subclass; a True mean must not count as the number 1.
    assert _is_number(True) is False


def test_is_number_rejects_oversized_int_that_cannot_convert_to_float():
    # 10**400 overflows float(); the OverflowError guard degrades it rather than crashing.
    assert _is_number(10 ** 400) is False


def test_is_number_accepts_a_plain_finite_number():
    assert _is_number(3) is True
    assert _is_number(0.5) is True


def test_a_non_finite_component_degrades_to_none_not_inf_or_nan():
    row = rank([("a", _art(0.5, judge=float("nan"), objective=0.4))])["ranking"][0]
    assert row["judge_mean"] is None
    assert row["objective_mean"] == 0.4


# ---- malformed container / entry degradation (never crash, warn + skip) --------------------


def test_a_non_list_entries_is_treated_as_no_candidates_with_a_warning(caplog):
    with caplog.at_level(logging.WARNING):
        result = rank("not-a-list")
    assert result["total"] == 0
    assert result["ranking"] == []
    assert any("entries is str" in rec.message for rec in caplog.records)


def test_a_malformed_entry_is_skipped_not_crashed(caplog):
    with caplog.at_level(logging.WARNING):
        result = rank([("a", _art(0.9)), ["only-one-element"], "bytes-not-a-pair"])
    assert result["scored"] == 1
    assert [row["label"] for row in result["ranking"]] == ["a"]
    assert any("not a (label, artifact) pair" in rec.message for rec in caplog.records)


def test_leaderboard_point_names_the_offending_index():
    assert _leaderboard_point(("label", {}), index=0) == ("label", {})
    assert _leaderboard_point(["only-one"], index=3) is None


# ---- human-readable headline ---------------------------------------------------------------


def test_headline_names_the_leader_and_counts_the_field():
    result = rank([("a", _art(0.9)), ("b", _art(0.8)), ("c", _art(0.5))])
    assert leaderboard_headline(result) == "leaderboard: a leads at 0.9 over 2 other(s)"


def test_headline_reports_unscored_tail():
    result = rank([("a", _art(0.9)), ("bad", "not-a-dict")])
    assert leaderboard_headline(result) == "leaderboard: a leads at 0.9; 1 unscored"


def test_headline_on_an_empty_or_all_unscored_board():
    assert leaderboard_headline(rank([])) == "leaderboard: no scored artifacts"
    assert leaderboard_headline({}) == "leaderboard: no scored artifacts"
