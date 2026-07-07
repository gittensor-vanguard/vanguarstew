"""Contract tests for specs/045-benchmark-decisive-rate — assert decisive_rate.py satisfies
the spec's EARS criteria: tally parsing, decisive/tie shares, headline branches, and pure
evaluation. Offline, deterministic.
"""

import copy
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from benchmark.decisive_rate import (  # noqa: E402
    _dict,
    _is_int,
    _is_number,
    _tally_counts,
    decisive_rate_headline,
    summarize_decisive_rate,
)

_REQUIRED_KEYS = frozenset({"total", "decisive", "tie", "decisive_rate", "tie_share"})


def _run(tally):
    return {"composite_mean": 0.6, "tally": tally}


# --- Input coercion -------------------------------------------------------------------------


@pytest.mark.parametrize("bad", (None, "not a dict", 42, [1, 2], ()))
def test_non_dict_artifact_coerced_to_empty_dict(bad):
    out = summarize_decisive_rate(bad)
    assert out["total"] is None
    assert out["decisive_rate"] is None


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


# --- Decisive rate summary ------------------------------------------------------------------


def test_summarize_happy_path():
    out = summarize_decisive_rate(_run({"challenger": 6, "baseline": 3, "tie": 1}))
    assert out == {
        "total": 10,
        "decisive": 9,
        "tie": 1,
        "decisive_rate": 0.9,
        "tie_share": 0.1,
    }


def test_all_ties_zero_decisive_rate():
    out = summarize_decisive_rate(_run({"challenger": 0, "baseline": 0, "tie": 5}))
    assert out["decisive"] == 0
    assert out["decisive_rate"] == 0.0
    assert out["tie_share"] == 1.0


def test_zero_total_none_rates():
    out = summarize_decisive_rate(_run({"challenger": 0, "baseline": 0, "tie": 0}))
    assert out["total"] == 0
    assert out["decisive_rate"] is None
    assert out["tie_share"] is None


def test_malformed_tally_all_none():
    out = summarize_decisive_rate({"composite_mean": 0.5})
    assert out == {
        "total": None,
        "decisive": None,
        "tie": None,
        "decisive_rate": None,
        "tie_share": None,
    }


def test_summary_always_includes_required_keys():
    for artifact in (
        _run({"challenger": 2, "baseline": 1, "tie": 0}),
        _run({"challenger": 0, "baseline": 0, "tie": 0}),
        {"composite_mean": 0.5},
        None,
    ):
        out = summarize_decisive_rate(artifact)
        assert _REQUIRED_KEYS <= frozenset(out)


# --- Decisive rate headline -----------------------------------------------------------------


def test_headline_happy_path_exact_format():
    out = summarize_decisive_rate(_run({"challenger": 2, "baseline": 1, "tie": 0}))
    assert decisive_rate_headline(out) == "decisive rate: 3/3 (100.0%), tie 0 (0.0%)"


def test_headline_zero_total_exact():
    out = summarize_decisive_rate(_run({"challenger": 0, "baseline": 0, "tie": 0}))
    assert decisive_rate_headline(out) == "decisive rate: no tally available"


def test_headline_missing_total():
    assert decisive_rate_headline({"decisive_rate": 0.5}) == "decisive rate: no tally available"


def test_headline_nan_rates_show_na():
    out = {
        "total": 3,
        "decisive": 2,
        "tie": 1,
        "decisive_rate": float("nan"),
        "tie_share": float("inf"),
    }
    headline = decisive_rate_headline(out)
    assert headline == "decisive rate: 2/3 (n/a), tie 1 (n/a)"


def test_headline_non_dict_summary_coerced():
    assert decisive_rate_headline("nope") == "decisive rate: no tally available"


# --- Pure evaluation ------------------------------------------------------------------------


def test_summarize_does_not_mutate_artifact():
    art = _run({"challenger": 2, "baseline": 1, "tie": 0})
    snapshot = copy.deepcopy(art)
    summarize_decisive_rate(art)
    assert art == snapshot
