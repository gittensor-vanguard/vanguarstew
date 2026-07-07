"""Contract tests for specs/050-benchmark-margin-outlook — assert margin_outlook.py satisfies
the spec's EARS criteria: margin resolution, outlook branches, headline branches, and pure
evaluation. Offline, deterministic.
"""

import copy
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from benchmark.margin_outlook import (  # noqa: E402
    _dict,
    _is_int,
    _margin,
    _margin_from_tally,
    _outlook,
    margin_outlook_headline,
    summarize_margin_outlook,
)

_REQUIRED_KEYS = frozenset({"kind", "decisive_margin", "outlook"})


# --- Input coercion -------------------------------------------------------------------------


@pytest.mark.parametrize("bad", (None, "not a dict", 42, [1, 2], ()))
def test_non_dict_artifact_coerced_to_empty_dict(bad):
    out = summarize_margin_outlook(bad)
    assert out["kind"] == "invalid"
    assert out["decisive_margin"] is None
    assert out["outlook"] is None


def test_dict_helper_returns_dict_or_empty():
    assert _dict({"a": 1}) == {"a": 1}
    assert _dict(None) == {}


# --- Whole-number count semantics -----------------------------------------------------------


def test_is_int_rejects_bool():
    assert not _is_int(True)
    assert not _is_int(False)
    assert _margin_from_tally({"challenger": True, "baseline": 1}) is None


@pytest.mark.parametrize("value", (5.0, 4.0, 0.0))
def test_is_int_rejects_float_whole_numbers(value):
    assert not _is_int(value)
    assert _margin_from_tally({"challenger": value, "baseline": 1}) is None


# --- Tally margin ---------------------------------------------------------------------------


def test_margin_from_tally_happy_path():
    assert _margin_from_tally({"challenger": 5, "baseline": 2, "tie": 1}) == 3


def test_margin_from_tally_malformed():
    assert _margin_from_tally({"challenger": 1, "baseline": "x"}) is None
    assert _margin_from_tally({}) is None


# --- Margin resolution ----------------------------------------------------------------------


def test_margin_prefers_decisive_margin():
    art = {
        "decisive_margin": 4,
        "tally": {"challenger": 1, "baseline": 9, "tie": 0},
        "judge_report": {"wins": 0, "losses": 5, "ties": 0},
    }
    assert _margin(art) == 4


def test_margin_falls_back_to_tally():
    art = {"tally": {"challenger": 5, "baseline": 2, "tie": 1}}
    assert _margin(art) == 3


def test_margin_falls_back_to_judge_report():
    art = {"judge_report": {"wins": 9, "losses": 2, "ties": 1}}
    assert _margin(art) == 7


# --- Outlook --------------------------------------------------------------------------------


def test_outlook_ahead_behind_tied():
    assert _outlook(3) == "ahead"
    assert _outlook(-2) == "behind"
    assert _outlook(0) == "tied"


def test_outlook_none_for_invalid_margin():
    assert _outlook(None) is None
    assert _outlook(1.5) is None


# --- Margin outlook summary -----------------------------------------------------------------


def test_summarize_happy_path():
    out = summarize_margin_outlook({"decisive_margin": 3, "composite_mean": 0.6})
    assert out == {
        "kind": "single",
        "decisive_margin": 3,
        "outlook": "ahead",
    }


def test_missing_data_none_outlook():
    out = summarize_margin_outlook({"composite_mean": 0.5})
    assert out["decisive_margin"] is None
    assert out["outlook"] is None


def test_summary_always_includes_required_keys():
    for artifact in (
        {"decisive_margin": 1},
        {"tally": {"challenger": 2, "baseline": 2, "tie": 0}},
        None,
    ):
        out = summarize_margin_outlook(artifact)
        assert _REQUIRED_KEYS <= frozenset(out)


# --- Margin outlook headline ----------------------------------------------------------------


def test_headline_exact_format():
    out = summarize_margin_outlook({
        "composite_mean": 0.72,
        "judge_report": {"wins": 9, "losses": 2, "ties": 1},
    })
    assert margin_outlook_headline(out) == "margin outlook: ahead (decisive_margin 7)"


def test_headline_unavailable_exact():
    out = summarize_margin_outlook({"composite_mean": 0.5})
    assert margin_outlook_headline(out) == "margin outlook: unavailable"


def test_headline_non_dict_summary_coerced():
    assert margin_outlook_headline("nope") == "margin outlook: unavailable"


# --- Pure evaluation ------------------------------------------------------------------------


def test_summarize_does_not_mutate_artifact():
    art = {"decisive_margin": 2, "composite_mean": 0.6}
    snapshot = copy.deepcopy(art)
    summarize_margin_outlook(art)
    assert art == snapshot
