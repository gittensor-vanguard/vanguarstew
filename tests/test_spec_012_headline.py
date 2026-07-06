"""Contract tests for specs/012-benchmark-trend-headline — assert headline_score satisfies the
spec's EARS criteria: input tolerance, single/multi-repo extraction, generalization tuned
partition, and unscored-placeholder handling. Deterministic, offline.
"""

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from benchmark.trend import headline_score  # noqa: E402


def _single(score):
    return {"composite_mean": score}


def _multi(score, scored_repos=2):
    return {"composite_mean": score, "scored_repos": scored_repos, "repos": scored_repos}


def _gen(tuned_score, tuned_scored=3, held_score=0.5):
    return {
        "tuned": {"composite_mean": tuned_score, "scored_repos": tuned_scored},
        "held_out": {"composite_mean": held_score, "scored_repos": 2},
        "generalization_gap": 0.1,
    }


# --- Input tolerance --------------------------------------------------------------------------

def test_headline_score_rejects_non_dict_and_non_numeric_composite():
    assert headline_score("not a dict") is None
    assert headline_score([]) is None
    assert headline_score({"error": "no tasks"}) is None
    assert headline_score({"composite_mean": "bad"}) is None
    assert headline_score({"composite_mean": True}) is None


# --- Single-repo and multi-repo ---------------------------------------------------------------

def test_headline_score_reads_numeric_top_level_composite_mean():
    assert headline_score(_single(0.62)) == 0.62
    assert headline_score(_multi(0.4)) == 0.4
    assert headline_score(_single(0.123456)) == 0.123


def test_headline_score_treats_scored_repos_zero_as_unscored_placeholder():
    unscored = _multi(0.0, scored_repos=0)
    assert headline_score(unscored) is None
    # A single-repo artifact without scored_repos keeps a legitimate zero.
    assert headline_score(_single(0.0)) == 0.0


# --- Generalization ---------------------------------------------------------------------------

def test_headline_score_reads_tuned_partition_not_held_out():
    assert headline_score(_gen(0.71)) == 0.71
    # held_out differs; headline must follow tuned only.
    art = _gen(0.71, held_score=0.99)
    assert headline_score(art) == 0.71


def test_headline_score_treats_unscored_tuned_partition_as_unscored():
    unscored = {
        "tuned": {"error": "no tuned repos", "scored_repos": 0, "composite_mean": 0.0},
        "held_out": {"composite_mean": 0.56, "scored_repos": 2},
        "generalization_gap": None,
    }
    assert headline_score(unscored) is None
