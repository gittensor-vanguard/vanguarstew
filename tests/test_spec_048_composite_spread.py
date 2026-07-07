"""Contract tests for specs/048-benchmark-composite-spread — assert composite_spread.py
satisfies the spec's EARS criteria: headline partition selection, parts parsing, spread
computation, headline branches, and pure evaluation. Offline, deterministic.
"""

import copy
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from benchmark.composite_spread import (  # noqa: E402
    _dict,
    _headline_partition,
    _headline_parts,
    _is_number,
    _round3,
    composite_spread_headline,
    summarize_composite_spread,
)

_REQUIRED_KEYS = frozenset({"kind", "judge_mean", "objective_mean", "spread"})


def _single(judge, objective):
    return {
        "composite_mean": 0.6,
        "composite_parts": {"judge_mean": judge, "objective_mean": objective},
    }


# --- Input coercion -------------------------------------------------------------------------


@pytest.mark.parametrize("bad", (None, "not a dict", 42, [1, 2], ()))
def test_non_dict_artifact_coerced_to_empty_dict(bad):
    out = summarize_composite_spread(bad)
    assert out["kind"] == "invalid"
    assert out["spread"] is None


def test_dict_helper_returns_dict_or_empty():
    assert _dict({"a": 1}) == {"a": 1}
    assert _dict(None) == {}


# --- Numeric semantics ----------------------------------------------------------------------


def test_is_number_rejects_bool():
    assert not _is_number(True)
    assert not _is_number(False)
    assert _is_number(0.5)
    assert _is_number(1)


def test_round3_happy_path_and_invalid():
    assert _round3(0.123456) == 0.123
    assert _round3(True) is None
    assert _round3("x") is None


# --- Headline partition ---------------------------------------------------------------------


def test_headline_partition_single_and_generalization():
    single = _single(0.7, 0.5)
    assert _headline_partition(single) is single

    art = {
        "tuned": _single(0.8, 0.4),
        "held_out": _single(0.5, 0.5),
        "generalization_gap": 0.1,
    }
    assert _headline_partition(art) is art["tuned"]


# --- Composite parts ------------------------------------------------------------------------


def test_headline_parts_happy_path():
    assert _headline_parts(_single(0.7, 0.5)) == {
        "judge_mean": 0.7,
        "objective_mean": 0.5,
    }


def test_headline_parts_missing_or_malformed():
    assert _headline_parts({"composite_mean": 0.5}) == {
        "judge_mean": None,
        "objective_mean": None,
    }
    assert _headline_parts({"composite_parts": 42}) == {
        "judge_mean": None,
        "objective_mean": None,
    }


# --- Composite spread summary ---------------------------------------------------------------


def test_summarize_happy_path():
    out = summarize_composite_spread(_single(0.7, 0.5))
    assert out == {
        "kind": "single",
        "judge_mean": 0.7,
        "objective_mean": 0.5,
        "spread": 0.2,
    }


def test_generalization_reads_tuned():
    art = {
        "tuned": _single(0.8, 0.4),
        "held_out": _single(0.5, 0.5),
        "generalization_gap": 0.1,
    }
    out = summarize_composite_spread(art)
    assert out["kind"] == "generalization"
    assert out["spread"] == 0.4


def test_missing_parts_none_spread():
    out = summarize_composite_spread({"composite_mean": 0.5})
    assert out["spread"] is None
    assert out["judge_mean"] is None


def test_summary_always_includes_required_keys():
    for artifact in (
        _single(0.6, 0.4),
        {"composite_mean": 0.5},
        None,
    ):
        out = summarize_composite_spread(artifact)
        assert _REQUIRED_KEYS <= frozenset(out)


# --- Composite spread headline --------------------------------------------------------------


def test_headline_exact_format():
    out = summarize_composite_spread(_single(0.6, 0.4))
    assert composite_spread_headline(out) == (
        "composite spread: judge 0.6 vs objective 0.4 (delta +0.200)"
    )


def test_headline_none_spread_shows_na():
    out = summarize_composite_spread({"composite_mean": 0.5})
    assert composite_spread_headline(out) == (
        "composite spread: judge None vs objective None (delta n/a)"
    )


def test_headline_non_dict_summary_coerced():
    assert composite_spread_headline("nope") == (
        "composite spread: judge None vs objective None (delta n/a)"
    )


# --- Pure evaluation ------------------------------------------------------------------------


def test_summarize_does_not_mutate_artifact():
    art = _single(0.6, 0.4)
    snapshot = copy.deepcopy(art)
    summarize_composite_spread(art)
    assert art == snapshot
