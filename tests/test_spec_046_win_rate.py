"""Contract tests for specs/046-benchmark-win-rate — assert win_rate.py satisfies the spec's
EARS criteria: tally parsing, per-outcome rates, headline branches, and pure evaluation.
Offline, deterministic.
"""

import copy
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from benchmark.win_rate import (  # noqa: E402
    _dict,
    _is_int,
    _is_number,
    _tally_counts,
    summarize_win_rate,
    win_rate_headline,
)

_REQUIRED_KEYS = frozenset({
    "total",
    "challenger",
    "baseline",
    "tie",
    "challenger_rate",
    "baseline_rate",
    "tie_rate",
})


def _run(tally):
    return {"composite_mean": 0.6, "tally": tally}


# --- Input coercion -------------------------------------------------------------------------


@pytest.mark.parametrize("bad", (None, "not a dict", 42, [1, 2], ()))
def test_non_dict_artifact_coerced_to_empty_dict(bad):
    out = summarize_win_rate(bad)
    assert out["total"] is None
    assert out["challenger_rate"] is None


def test_dict_helper_returns_dict_or_empty():
    assert _dict({"a": 1}) == {"a": 1}
    assert _dict(None) == {}


# --- Whole-number count semantics -----------------------------------------------------------


def test_is_int_rejects_bool():
    assert not _is_int(True)
    assert not _is_int(False)
    assert _tally_counts(_run({"challenger": True, "baseline": 0, "tie": 0})) is None


@pytest.mark.parametrize("value", (5.0, 4.0, 0.0))
def test_is_int_rejects_float_whole_numbers(value):
    assert not _is_int(value)
    assert _tally_counts(_run({"challenger": value, "baseline": 0, "tie": 0})) is None


# --- Finite numeric semantics ---------------------------------------------------------------


def test_bool_and_non_finite_not_numeric():
    assert not _is_number(True)
    assert not _is_number(False)
    assert not _is_number(float("nan"))
    assert not _is_number(float("inf"))
    assert _is_number(0.0)
    assert _is_number(1)


# --- Tally parsing --------------------------------------------------------------------------


def test_tally_counts_happy_path():
    assert _tally_counts(_run({"challenger": 6, "baseline": 3, "tie": 1})) == (6, 3, 1)


@pytest.mark.parametrize(
    "artifact",
    (
        {"composite_mean": 0.5},
        _run({"challenger": 1, "baseline": "x", "tie": 0}),
        _run({"challenger": -1, "baseline": 1, "tie": 0}),
        {"tally": "not-a-dict"},
    ),
)
def test_tally_counts_missing_or_malformed(artifact):
    assert _tally_counts(artifact) is None


# --- Win rate summary -----------------------------------------------------------------------


def test_summarize_happy_path():
    out = summarize_win_rate(_run({"challenger": 6, "baseline": 3, "tie": 1}))
    assert out == {
        "total": 10,
        "challenger": 6,
        "baseline": 3,
        "tie": 1,
        "challenger_rate": 0.6,
        "baseline_rate": 0.3,
        "tie_rate": 0.1,
    }


def test_zero_total_none_rates():
    out = summarize_win_rate(_run({"challenger": 0, "baseline": 0, "tie": 0}))
    assert out["total"] == 0
    assert out["challenger"] == 0
    assert out["challenger_rate"] is None
    assert out["baseline_rate"] is None
    assert out["tie_rate"] is None


def test_malformed_tally_all_none():
    out = summarize_win_rate({"composite_mean": 0.5})
    assert out == {
        "total": None,
        "challenger": None,
        "baseline": None,
        "tie": None,
        "challenger_rate": None,
        "baseline_rate": None,
        "tie_rate": None,
    }


def test_summary_always_includes_required_keys():
    for artifact in (
        _run({"challenger": 2, "baseline": 1, "tie": 0}),
        _run({"challenger": 0, "baseline": 0, "tie": 0}),
        {"composite_mean": 0.5},
        None,
    ):
        out = summarize_win_rate(artifact)
        assert _REQUIRED_KEYS <= frozenset(out)


# --- Win rate headline ----------------------------------------------------------------------


def test_headline_happy_path_exact_format():
    out = summarize_win_rate(_run({"challenger": 2, "baseline": 1, "tie": 0}))
    assert win_rate_headline(out) == "win rate: challenger 2/3 (66.7%), baseline 1, tie 0"


def test_headline_zero_total_exact():
    out = summarize_win_rate(_run({"challenger": 0, "baseline": 0, "tie": 0}))
    assert win_rate_headline(out) == "win rate: no tally available"


def test_headline_missing_total():
    assert win_rate_headline({"challenger_rate": 0.5}) == "win rate: no tally available"


def test_headline_nan_rate_shows_na():
    out = {
        "total": 3,
        "challenger": 1,
        "baseline": 1,
        "tie": 1,
        "challenger_rate": float("nan"),
    }
    assert win_rate_headline(out) == "win rate: challenger 1/3 (n/a), baseline 1, tie 1"


def test_headline_non_dict_summary_coerced():
    assert win_rate_headline("nope") == "win rate: no tally available"


# --- Pure evaluation ------------------------------------------------------------------------


def test_summarize_does_not_mutate_artifact():
    art = _run({"challenger": 2, "baseline": 1, "tie": 0})
    snapshot = copy.deepcopy(art)
    summarize_win_rate(art)
    assert art == snapshot
