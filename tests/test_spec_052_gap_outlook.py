"""Contract tests for specs/052-benchmark-gap-outlook — assert gap_outlook.py satisfies the spec's
EARS criteria: partition scores, gap verdict, headline branches, and pure evaluation. Offline,
deterministic.
"""

import copy
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from benchmark.gap_outlook import (  # noqa: E402
    _dict,
    _is_number,
    _partition_score,
    gap_outlook_headline,
    summarize_gap_outlook,
)

_REQUIRED_KEYS = frozenset({
    "kind",
    "generalization_gap",
    "tuned_score",
    "held_out_score",
    "verdict",
})


def _part(score, scored=2):
    return {"composite_mean": score, "scored_repos": scored, "repos": scored}


def _gen(tuned, held, gap):
    return {
        "tuned": _part(tuned),
        "held_out": _part(held),
        "generalization_gap": gap,
    }


# --- Input coercion -------------------------------------------------------------------------


@pytest.mark.parametrize("bad", (None, "not a dict", 42, [1, 2], ()))
def test_non_dict_artifact_coerced_to_empty_dict(bad):
    out = summarize_gap_outlook(bad)
    assert out["kind"] == "invalid"
    assert out["verdict"] is None
    assert out["generalization_gap"] is None


def test_dict_helper_returns_dict_or_empty():
    assert _dict({"a": 1}) == {"a": 1}
    assert _dict(None) == {}


# --- Numeric semantics ----------------------------------------------------------------------


def test_is_number_rejects_bool():
    assert not _is_number(True)
    assert not _is_number(False)


def test_is_number_accepts_numeric():
    assert _is_number(0.1)
    assert _is_number(1)


# --- Partition score ------------------------------------------------------------------------


def test_partition_score_happy_path():
    assert _partition_score(_part(0.65)) == 0.65


def test_partition_score_zero_scored_repos():
    assert _partition_score(_part(0.0, scored=0)) is None
    assert _partition_score({"composite_mean": 0.0, "scored_repos": 0.0}) is None


# --- Gap outlook summary --------------------------------------------------------------------


def test_generalization_favorable_and_unfavorable():
    # gap = tuned - held_out; a positive gap (held-out dropped) is unfavorable, a zero/negative
    # gap (held-out held up) is favorable — matching the acceptance/runner/gap_integrity sign.
    unfavorable = summarize_gap_outlook(_gen(0.7, 0.6, 0.1))
    assert unfavorable == {
        "kind": "generalization",
        "generalization_gap": 0.1,
        "tuned_score": 0.7,
        "held_out_score": 0.6,
        "verdict": "unfavorable",
    }

    favorable = summarize_gap_outlook(_gen(0.5, 0.6, -0.1))
    assert favorable["verdict"] == "favorable"
    assert favorable["generalization_gap"] == -0.1


def test_non_generalization_none_fields():
    out = summarize_gap_outlook({"composite_mean": 0.6, "tasks": 5})
    assert out["kind"] == "single"
    assert out["verdict"] is None
    assert out["generalization_gap"] is None
    assert out["tuned_score"] is None


def test_summary_always_includes_required_keys():
    for artifact in (_gen(0.7, 0.6, 0.1), {"composite_mean": 0.6}, None):
        out = summarize_gap_outlook(artifact)
        assert _REQUIRED_KEYS <= frozenset(out)


# --- Gap outlook headline -------------------------------------------------------------------


def test_headline_generalization_exact_format():
    out = summarize_gap_outlook(_gen(0.65, 0.60, 0.05))   # gap +0.05: held-out dropped
    assert gap_outlook_headline(out) == (
        "gap outlook: unfavorable (gap +0.050, tuned 0.65 vs held-out 0.6)"
    )


def test_headline_non_generalization_exact():
    out = summarize_gap_outlook({"composite_mean": 0.6})
    assert gap_outlook_headline(out) == "gap outlook: not a generalization artifact"


def test_headline_non_dict_summary_coerced():
    assert gap_outlook_headline("nope") == "gap outlook: not a generalization artifact"


# --- Pure evaluation ------------------------------------------------------------------------


def test_summarize_does_not_mutate_artifact():
    art = _gen(0.7, 0.6, 0.1)
    snapshot = copy.deepcopy(art)
    summarize_gap_outlook(art)
    assert art == snapshot
