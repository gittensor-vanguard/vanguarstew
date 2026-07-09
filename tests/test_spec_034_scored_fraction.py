"""Contract tests for specs/034-benchmark-scored-fraction — assert scored_fraction.py
satisfies the spec's EARS criteria: count parsing, slice/combined fractions, artifact-kind
branches, headline branches, and pure evaluation. Offline, deterministic.
"""

import copy
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from benchmark.scored_fraction import (  # noqa: E402
    _combined,
    _dict,
    _is_int,
    _is_number,
    _scored_fraction,
    _slice_fraction,
    scored_fraction_headline,
    summarize_scored_fraction,
)

_REQUIRED_KEYS = frozenset({"kind", "repos", "scored_repos", "scored_fraction", "partitions"})


# --- Input coercion -------------------------------------------------------------------------


@pytest.mark.parametrize("bad", (None, "not a dict", 42, [1, 2], ()))
def test_non_dict_artifact_coerced_to_empty_dict(bad):
    out = summarize_scored_fraction(bad)
    assert out["kind"] == "invalid"
    assert out["scored_fraction"] is None
    assert out["partitions"] is None


def test_dict_helper_returns_dict_or_empty():
    assert _dict({"a": 1}) == {"a": 1}
    assert _dict(None) == {}


# --- Whole-number count semantics -----------------------------------------------------------


def test_is_int_rejects_bool():
    assert not _is_int(True)
    assert not _is_int(False)
    assert _scored_fraction(True, 1) is None
    assert _scored_fraction(5, False) is None


@pytest.mark.parametrize("value", (5.0, 4.0, 0.0))
def test_is_int_rejects_float_whole_numbers(value):
    assert not _is_int(value)
    assert _scored_fraction(value, 4) is None
    assert _scored_fraction(5, value) is None


# --- Finite numeric semantics ---------------------------------------------------------------


def test_bool_and_non_finite_not_numeric():
    assert not _is_number(True)
    assert not _is_number(False)
    assert not _is_number(float("nan"))
    assert not _is_number(float("inf"))
    assert _is_number(0.0)
    assert _is_number(1)


# --- Scored fraction ------------------------------------------------------------------------


def test_scored_fraction_valid_rates():
    assert _scored_fraction(5, 4) == 0.8
    assert _scored_fraction(4, 4) == 1.0


def test_scored_fraction_zero_scored_is_zero_point_zero():
    assert _scored_fraction(5, 0) == 0.0


def test_scored_fraction_negative_repos():
    assert _scored_fraction(-1, 0) is None
    assert _scored_fraction(0, 0) is None


def test_scored_fraction_negative_scored():
    assert _scored_fraction(5, -1) is None


def test_scored_fraction_scored_exceeds_repos():
    assert _scored_fraction(3, 5) is None


def test_scored_fraction_zero_repos():
    assert _scored_fraction(0, 0) is None


def test_scored_fraction_non_integer_counts():
    assert _scored_fraction(5.0, 4) is None
    assert _scored_fraction(5, 4.0) is None


# --- Slice fraction -------------------------------------------------------------------------


def test_slice_fraction_happy_path():
    assert _slice_fraction({"repos": 5, "scored_repos": 4}) == {
        "repos": 5,
        "scored_repos": 4,
        "scored_fraction": 0.8,
    }


def test_slice_fraction_incoherent_echoes_raw_ints():
    over = _slice_fraction({"repos": 3, "scored_repos": 5})
    assert over == {"repos": 3, "scored_repos": 5, "scored_fraction": None}


def test_slice_fraction_non_int_counts_become_none():
    bad = _slice_fraction({"repos": 5.0, "scored_repos": 4})
    assert bad == {"repos": None, "scored_repos": 4, "scored_fraction": None}


def test_slice_fraction_ignores_skipped_field():
    summary = summarize_scored_fraction({"repos": 5, "scored_repos": 4, "skipped": "bogus"})
    assert summary["scored_fraction"] == 0.8


# --- Combined fraction ----------------------------------------------------------------------


def test_combined_sums_coherent_slices():
    both = _combined(
        _slice_fraction({"repos": 4, "scored_repos": 4}),
        _slice_fraction({"repos": 6, "scored_repos": 3}),
    )
    assert both == {"repos": 10, "scored_repos": 7, "scored_fraction": 0.7}


def test_combined_withholds_when_any_slice_incoherent():
    partial = _combined(
        _slice_fraction({"repos": 4, "scored_repos": 4}),
        _slice_fraction({}),
    )
    assert partial == {"repos": None, "scored_repos": None, "scored_fraction": None}


# --- Artifact-kind branches -----------------------------------------------------------------


def test_single_and_multi_kinds():
    single = summarize_scored_fraction({"repos": 4, "scored_repos": 4})
    assert single["kind"] == "single"
    assert single["scored_fraction"] == 1.0
    assert single["partitions"] is None

    multi = summarize_scored_fraction({"per_repo": [{}, {}], "repos": 10, "scored_repos": 8})
    assert multi["kind"] == "multi"
    assert multi["scored_fraction"] == 0.8
    assert multi["partitions"] is None


def test_generalization_partitions_and_overall():
    summary = summarize_scored_fraction({
        "generalization_gap": 0.05,
        "tuned": {"repos": 4, "scored_repos": 4},
        "held_out": {"repos": 6, "scored_repos": 3},
    })
    assert summary["kind"] == "generalization"
    assert summary["repos"] == 10
    assert summary["scored_repos"] == 7
    assert summary["scored_fraction"] == 0.7
    assert summary["partitions"]["tuned"]["scored_fraction"] == 1.0
    assert summary["partitions"]["held_out"]["scored_fraction"] == 0.5


def test_generalization_partial_partition_withholds_overall():
    summary = summarize_scored_fraction({
        "generalization_gap": 0.0,
        "tuned": {"repos": 4, "scored_repos": 4},
        "held_out": {},
    })
    assert summary["scored_fraction"] is None
    assert summary["repos"] is None
    assert summary["scored_repos"] is None
    assert summary["partitions"]["tuned"]["scored_fraction"] == 1.0
    assert summary["partitions"]["held_out"]["scored_fraction"] is None


def test_invalid_kind_returns_none_fields():
    out = summarize_scored_fraction({})
    assert out["kind"] == "invalid"
    assert out["repos"] is None
    assert out["scored_repos"] is None
    assert out["scored_fraction"] is None
    assert out["partitions"] is None


def test_summary_always_includes_required_keys():
    for artifact in (
        {"repos": 5, "scored_repos": 4},
        {"generalization_gap": 0.0, "tuned": {"repos": 1, "scored_repos": 1}, "held_out": {}},
        {},
        None,
    ):
        out = summarize_scored_fraction(artifact)
        assert _REQUIRED_KEYS <= frozenset(out)


# --- Scored fraction headline ---------------------------------------------------------------


def test_headline_with_counts_exact_format():
    summary = summarize_scored_fraction({"repos": 5, "scored_repos": 4})
    assert scored_fraction_headline(summary) == "scored fraction: 80.0% (4/5 repos scored)"


def test_headline_zero_fraction_exact_format():
    summary = summarize_scored_fraction({"repos": 5, "scored_repos": 0})
    assert scored_fraction_headline(summary) == "scored fraction: 0.0% (0/5 repos scored)"


def test_headline_perfect_coverage_exact_format():
    summary = summarize_scored_fraction({"repos": 4, "scored_repos": 4})
    assert scored_fraction_headline(summary) == "scored fraction: 100.0% (4/4 repos scored)"


def test_headline_no_counts_clause():
    assert scored_fraction_headline({"scored_fraction": 0.8, "repos": None, "scored_repos": 4}) == (
        "scored fraction: 80.0%"
    )
    assert scored_fraction_headline({"scored_fraction": 0.8, "repos": 5, "scored_repos": None}) == (
        "scored fraction: 80.0%"
    )


def test_headline_none_fraction_shows_na():
    assert scored_fraction_headline({"scored_fraction": None}) == "scored fraction: n/a"
    assert scored_fraction_headline({}) == "scored fraction: n/a"
    over = summarize_scored_fraction({"repos": 3, "scored_repos": 5})
    assert scored_fraction_headline(over) == "scored fraction: n/a (5/3 repos scored)"


def test_headline_nan_fraction_shows_na():
    out = {
        "kind": "multi",
        "repos": 5,
        "scored_repos": 4,
        "scored_fraction": float("nan"),
        "partitions": None,
    }
    assert scored_fraction_headline(out) == "scored fraction: n/a (4/5 repos scored)"


def test_headline_non_dict_summary_coerced():
    assert scored_fraction_headline("nope") == "scored fraction: n/a"


# --- Pure evaluation ------------------------------------------------------------------------


def test_summarize_does_not_mutate_artifact():
    art = {"repos": 5, "scored_repos": 4, "skipped": 0}
    snapshot = copy.deepcopy(art)
    summarize_scored_fraction(art)
    assert art == snapshot
