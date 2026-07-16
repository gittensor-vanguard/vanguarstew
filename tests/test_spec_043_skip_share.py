"""Contract tests for specs/043-benchmark-skip-share — assert skip_share.py satisfies the
spec's EARS criteria: count parsing, slice/combined shares, artifact-kind branches, headline
branches, and pure evaluation. Offline, deterministic.
"""

import copy
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from benchmark.skip_share import (  # noqa: E402
    _combined,
    _dict,
    _is_int,
    _is_number,
    _skip_share,
    _slice_summary,
    skip_share_headline,
    summarize_skip_share,
)

_REQUIRED_KEYS = frozenset({"kind", "repos", "scored_repos", "skipped", "skip_share", "partitions"})


# --- Input coercion -------------------------------------------------------------------------


@pytest.mark.parametrize("bad", (None, "not a dict", 42, [1, 2], ()))
def test_non_dict_artifact_coerced_to_empty_dict(bad):
    out = summarize_skip_share(bad)
    assert out["kind"] == "invalid"
    assert out["skip_share"] is None
    assert out["partitions"] is None


def test_dict_helper_returns_dict_or_empty():
    assert _dict({"a": 1}) == {"a": 1}
    assert _dict(None) == {}


# --- Whole-number count semantics -----------------------------------------------------------


def test_is_int_rejects_bool():
    assert not _is_int(True)
    assert not _is_int(False)
    assert _skip_share(True, 1) is None
    assert _skip_share(5, False) is None


@pytest.mark.parametrize("value", (5.0, 4.0, 0.0))
def test_is_int_rejects_float_whole_numbers(value):
    assert not _is_int(value)
    assert _skip_share(value, 4) is None
    assert _skip_share(5, value) is None


# --- Finite numeric semantics ---------------------------------------------------------------


def test_bool_and_non_finite_not_numeric():
    assert not _is_number(True)
    assert not _is_number(False)
    assert not _is_number(float("nan"))
    assert not _is_number(float("inf"))
    assert _is_number(0.0)
    assert _is_number(1)


# --- Skip share -----------------------------------------------------------------------------


def test_skip_share_valid_rates():
    assert _skip_share(5, 4) == 0.2
    assert _skip_share(4, 4) == 0.0
    assert _skip_share(4, 0) == 1.0


def test_skip_share_incoherent_counts():
    assert _skip_share(0, 0) is None
    assert _skip_share(-1, 0) is None
    assert _skip_share(3, 5) is None
    assert _skip_share(5, -1) is None
    assert _skip_share(5.0, 4) is None


# --- Slice summary --------------------------------------------------------------------------


def test_slice_summary_happy_path():
    assert _slice_summary({"repos": 5, "scored_repos": 4}) == {
        "repos": 5,
        "scored_repos": 4,
        "skipped": 1,
        "skip_share": 0.2,
    }


def test_slice_summary_incoherent_echoes_raw_ints():
    over = _slice_summary({"repos": 3, "scored_repos": 5})
    assert over == {"repos": 3, "scored_repos": 5, "skipped": None, "skip_share": None}


# --- Combined summary -----------------------------------------------------------------------


def test_combined_sums_coherent_slices():
    both = _combined(
        _slice_summary({"repos": 4, "scored_repos": 4}),
        _slice_summary({"repos": 4, "scored_repos": 2}),
    )
    assert both == {"repos": 8, "scored_repos": 6, "skipped": 2, "skip_share": 0.25}


def test_combined_withholds_when_any_slice_incoherent():
    partial = _combined(
        _slice_summary({"repos": 4, "scored_repos": 4}),
        _slice_summary({}),
    )
    assert partial == {
        "repos": None,
        "scored_repos": None,
        "skipped": None,
        "skip_share": None,
    }


# --- Artifact-kind branches -----------------------------------------------------------------


def test_single_and_multi_kinds():
    single = summarize_skip_share({"repos": 5, "scored_repos": 4})
    assert single["kind"] == "single"
    assert single["skip_share"] == 0.2
    assert single["skipped"] == 1
    assert single["partitions"] is None

    multi = summarize_skip_share({"per_repo": [{}, {}], "repos": 10, "scored_repos": 8})
    assert multi["kind"] == "multi"
    assert multi["skip_share"] == 0.2
    assert multi["partitions"] is None


def test_generalization_partitions_and_overall():
    summary = summarize_skip_share({
        "generalization_gap": 0.05,
        "tuned": {"repos": 4, "scored_repos": 4},
        "held_out": {"repos": 4, "scored_repos": 2},
    })
    assert summary["kind"] == "generalization"
    assert summary["repos"] == 8
    assert summary["scored_repos"] == 6
    assert summary["skipped"] == 2
    assert summary["skip_share"] == 0.25
    assert summary["partitions"]["tuned"]["skip_share"] == 0.0
    assert summary["partitions"]["held_out"]["skip_share"] == 0.5


def test_generalization_partial_partition_withholds_overall():
    summary = summarize_skip_share({
        "generalization_gap": 0.0,
        "tuned": {"repos": 4, "scored_repos": 4},
        "held_out": {},
    })
    assert summary["skip_share"] is None
    assert summary["repos"] is None
    assert summary["partitions"]["tuned"]["skip_share"] == 0.0
    assert summary["partitions"]["held_out"]["skip_share"] is None


def test_invalid_kind_returns_none_fields():
    out = summarize_skip_share({})
    assert out["kind"] == "invalid"
    assert out["repos"] is None
    assert out["scored_repos"] is None
    assert out["skipped"] is None
    assert out["skip_share"] is None
    assert out["partitions"] is None


def test_summary_always_includes_required_keys():
    for artifact in (
        {"repos": 5, "scored_repos": 4},
        {"generalization_gap": 0.0, "tuned": {"repos": 4, "scored_repos": 4}, "held_out": {}},
        {},
        None,
    ):
        out = summarize_skip_share(artifact)
        assert _REQUIRED_KEYS <= frozenset(out)


# --- Skip share headline --------------------------------------------------------------------


def test_headline_with_counts_exact_format():
    summary = summarize_skip_share({"repos": 5, "scored_repos": 4})
    assert skip_share_headline(summary) == "skip share: 20.0% (1 of 5 repos skipped)"


def test_headline_no_counts_clause():
    assert skip_share_headline({"skip_share": 0.2, "skipped": None, "repos": 5}) == (
        "skip share: 20.0%"
    )
    assert skip_share_headline({"skip_share": 0.2, "skipped": 1, "repos": None}) == (
        "skip share: 20.0%"
    )


def test_headline_none_share_shows_na():
    assert skip_share_headline({"skip_share": None}) == "skip share: n/a"
    assert skip_share_headline({}) == "skip share: n/a"


def test_headline_nan_share_shows_na():
    out = {"skip_share": float("nan"), "skipped": 1, "repos": 5}
    assert skip_share_headline(out) == "skip share: n/a (1 of 5 repos skipped)"


def test_headline_non_dict_summary_coerced():
    assert skip_share_headline("nope") == "skip share: n/a"


# --- Pure evaluation ------------------------------------------------------------------------


def test_summarize_does_not_mutate_artifact():
    art = {"repos": 5, "scored_repos": 4}
    snapshot = copy.deepcopy(art)
    summarize_skip_share(art)
    assert art == snapshot
