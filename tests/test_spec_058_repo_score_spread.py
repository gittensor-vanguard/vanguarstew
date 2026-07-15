"""Contract tests for specs/058-benchmark-repo-score-spread — assert repo_score_spread.py
satisfies the spec's EARS criteria: per-repo composite min/max/range, generalization
partitions, headline branches, and pure evaluation. Offline, deterministic.
"""

import copy
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from benchmark.repo_score_spread import (  # noqa: E402
    _dict,
    _is_int,
    _is_number,
    _repo_scores,
    _spread,
    repo_score_spread_headline,
    summarize_repo_score_spread,
)

_REQUIRED_KEYS = frozenset({"kind", "scored_repos", "min", "max", "range", "partitions"})


def _repo(score):
    return {"composite_mean": score, "tasks": 5, "repos": 1, "scored_repos": 1}


def _multi(*scores):
    return {
        "per_repo": [_repo(s) for s in scores],
        "repos": len(scores),
        "scored_repos": len(scores),
    }


# --- Input coercion -------------------------------------------------------------------------


@pytest.mark.parametrize("bad", (None, "not a dict", 42, [1, 2], ()))
def test_non_dict_artifact_coerced_to_empty_dict(bad):
    out = summarize_repo_score_spread(bad)
    assert out["kind"] == "invalid"
    assert out["scored_repos"] == 0
    assert out["partitions"] is None


def test_dict_helper_returns_dict_or_empty():
    assert _dict({"a": 1}) == {"a": 1}
    assert _dict(None) == {}


def test_is_int_semantics():
    assert _is_int(0)
    assert _is_int(2)
    assert not _is_int(True)
    assert not _is_int(1.0)


# --- Numeric semantics ----------------------------------------------------------------------


def test_is_number_rejects_bool_and_non_finite():
    assert _is_number(0.6)
    assert _is_number(1)
    assert not _is_number(True)
    assert not _is_number("0.6")
    assert not _is_number(None)
    assert not _is_number(float("nan"))
    assert not _is_number(float("inf"))


# --- Per-repo scores ------------------------------------------------------------------------


def test_repo_scores_multi_and_single():
    assert _repo_scores(_multi(0.4, 0.8)) == [0.4, 0.8]
    assert _repo_scores({"composite_mean": 0.6}) == [0.6]


def test_repo_scores_skips_non_numeric():
    assert _repo_scores({
        "per_repo": [
            {"composite_mean": "x"},
            {"composite_mean": True},
            {"tasks": 1},
            "nope",
            {"composite_mean": 0.5},
        ],
    }) == [0.5]
    assert _repo_scores({"composite_mean": "x"}) == []
    assert _repo_scores(None) == []


# --- Spread helper --------------------------------------------------------------------------


def test_spread_empty_and_populated():
    assert _spread([]) == {"scored_repos": 0, "min": None, "max": None, "range": None}
    assert _spread([0.4, 0.8, 0.6]) == {
        "scored_repos": 3,
        "min": 0.4,
        "max": 0.8,
        "range": 0.4,
    }


# --- Repo score spread summary --------------------------------------------------------------


def test_multi_artifact_spread():
    out = summarize_repo_score_spread(_multi(0.4, 0.8, 0.6))
    assert out["kind"] == "multi"
    assert out["scored_repos"] == 3
    assert out["min"] == 0.4
    assert out["max"] == 0.8
    assert out["range"] == 0.4
    assert out["partitions"] is None


def test_generalization_partitions():
    out = summarize_repo_score_spread({
        "generalization_gap": 0.05,
        "tuned": _multi(0.7, 0.9),
        "held_out": _multi(0.3, 0.5),
    })
    assert out["kind"] == "generalization"
    assert out["scored_repos"] == 4
    assert out["min"] == 0.3
    assert out["max"] == 0.9
    assert out["partitions"]["tuned"] == {
        "scored_repos": 2,
        "min": 0.7,
        "max": 0.9,
        "range": 0.2,
    }
    assert out["partitions"]["held_out"]["range"] == 0.2


def test_summary_always_includes_required_keys():
    for artifact in (_multi(0.4, 0.8), {"per_repo": []}, None):
        out = summarize_repo_score_spread(artifact)
        assert _REQUIRED_KEYS <= frozenset(out)


# --- Repo score spread headline -------------------------------------------------------------


def test_headline_exact_format():
    out = summarize_repo_score_spread(_multi(0.4, 0.8))
    assert repo_score_spread_headline(out) == (
        "repo score spread: range 0.400 across 2 repo(s) (min 0.4, max 0.8)"
    )


def test_headline_no_scored_repos():
    assert repo_score_spread_headline({"scored_repos": 0}) == "repo score spread: no scored repos"
    assert repo_score_spread_headline({}) == "repo score spread: no scored repos"
    assert repo_score_spread_headline("nope") == "repo score spread: no scored repos"


def test_headline_n_a_range():
    assert "n/a" in repo_score_spread_headline({
        "scored_repos": 2,
        "range": None,
        "min": 1,
        "max": 1,
    })


# --- Pure evaluation ------------------------------------------------------------------------


def test_summarize_does_not_mutate_artifact():
    art = _multi(0.4, 0.8)
    snapshot = copy.deepcopy(art)
    summarize_repo_score_spread(art)
    assert art == snapshot
