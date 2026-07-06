"""Contract tests for specs/033-benchmark-decisive-rate — assert decisive_rate.py
satisfies the spec's EARS criteria: input coercion, tally parsing, summarize branches,
headline branches, and pure evaluation. Offline, deterministic.
"""

import copy
import logging
import math
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from benchmark.decisive_rate import (  # noqa: E402
    _dict,
    _is_number,
    _tally_counts,
    decisive_rate_headline,
    summarize_decisive_rate,
)

_NONE_SUMMARY = {
    "total": None,
    "decisive": None,
    "tie": None,
    "decisive_rate": None,
    "tie_share": None,
}


def _run(tally):
    return {"composite_mean": 0.6, "tally": tally}


# --- Input coercion -------------------------------------------------------------------------


@pytest.mark.parametrize("bad", (None, "not a dict", 42, [1, 2], ()))
def test_non_dict_result_coerced_to_empty_dict(bad):
    out = summarize_decisive_rate(bad)
    assert out == _NONE_SUMMARY


def test_dict_helper_returns_dict_or_empty():
    assert _dict({"a": 1}) == {"a": 1}
    assert _dict(None) == {}


# --- Tally parsing --------------------------------------------------------------------------


def test_tally_not_dict_returns_none():
    assert _tally_counts({}) is None
    assert _tally_counts({"tally": []}) is None
    assert _tally_counts({"tally": "bad"}) is None


@pytest.mark.parametrize(
    "tally",
    (
        {"challenger": 1, "baseline": "x", "tie": 0},
        {"challenger": -1, "baseline": 1, "tie": 0},
        {"challenger": 1.5, "baseline": 1, "tie": 0},
        {"challenger": True, "baseline": 1, "tie": 0},
        {"challenger": 1, "baseline": 1},
    ),
)
def test_malformed_counts_rejected(tally):
    assert _tally_counts({"tally": tally}) is None
    out = summarize_decisive_rate(_run(tally))
    assert out["total"] is None


def test_valid_tally_counts_tuple():
    assert _tally_counts({"tally": {"challenger": 2, "baseline": 1, "tie": 3}}) == (2, 1, 3)


# --- Summarize — malformed tally ------------------------------------------------------------


def test_missing_tally_yields_all_none():
    out = summarize_decisive_rate({"composite_mean": 0.5})
    assert out == _NONE_SUMMARY


# --- Summarize — zero total -----------------------------------------------------------------


def test_zero_total_yields_none_rates():
    out = summarize_decisive_rate(_run({"challenger": 0, "baseline": 0, "tie": 0}))
    assert out["total"] == 0
    assert out["decisive"] == 0
    assert out["tie"] == 0
    assert out["decisive_rate"] is None
    assert out["tie_share"] is None


# --- Summarize — positive total -------------------------------------------------------------


def test_decisive_and_tie_shares_from_complete_tally():
    out = summarize_decisive_rate(_run({"challenger": 6, "baseline": 3, "tie": 1}))
    assert out["total"] == 10
    assert out["decisive"] == 9
    assert out["tie"] == 1
    assert out["decisive_rate"] == 0.9
    assert out["tie_share"] == 0.1


# --- Summarize — all ties (0.0 vs missing) --------------------------------------------------


def test_all_ties_yields_zero_decisive_rate():
    out = summarize_decisive_rate(_run({"challenger": 0, "baseline": 0, "tie": 5}))
    assert out["total"] == 5
    assert out["decisive"] == 0
    assert out["tie"] == 5
    assert out["decisive_rate"] == 0.0
    assert out["tie_share"] == 1.0


# --- Finite numeric semantics ---------------------------------------------------------------


def test_bool_and_non_finite_not_numeric():
    assert not _is_number(True)
    assert not _is_number(False)
    assert not _is_number(float("nan"))
    assert not _is_number(float("inf"))
    assert _is_number(0.0)
    assert _is_number(1)


# --- Decisive rate headline -----------------------------------------------------------------


def test_headline_no_tally_when_zero_or_invalid_total():
    zero = summarize_decisive_rate(_run({"challenger": 0, "baseline": 0, "tie": 0}))
    assert decisive_rate_headline(zero) == "decisive rate: no tally available"
    assert decisive_rate_headline(_NONE_SUMMARY) == "decisive rate: no tally available"
    assert decisive_rate_headline({"total": "three", "decisive": 2, "tie": 1}) == (
        "decisive rate: no tally available"
    )


def test_headline_happy_path():
    out = summarize_decisive_rate(_run({"challenger": 2, "baseline": 1, "tie": 0}))
    headline = decisive_rate_headline(out)
    assert "3/3" in headline
    assert "100.0%" in headline
    assert "tie 0 (0.0%)" in headline


def test_headline_nan_rate_shows_na():
    out = {
        "total": 3,
        "decisive": 2,
        "tie": 1,
        "decisive_rate": float("nan"),
        "tie_share": float("inf"),
    }
    headline = decisive_rate_headline(out)
    assert "n/a" in headline
    assert math.isnan(out["decisive_rate"])


# --- Logging (N/A — document absence) -------------------------------------------------------


def test_module_emits_no_logs(caplog):
    with caplog.at_level(logging.DEBUG, logger="benchmark.decisive_rate"):
        summarize_decisive_rate(_run({"challenger": 1, "baseline": 0, "tie": 0}))
        decisive_rate_headline({"total": 0})
    assert caplog.records == []


# --- Pure evaluation ------------------------------------------------------------------------


def test_summarize_does_not_mutate_result():
    result = _run({"challenger": 2, "baseline": 1, "tie": 1})
    snapshot = copy.deepcopy(result)
    summarize_decisive_rate(result)
    assert result == snapshot
