"""Contract tests for specs/051-benchmark-blend-weights — assert blend_weights.py satisfies the
spec's EARS criteria: headline partition selection, weight parsing, headline branches, and pure
evaluation. Offline, deterministic.
"""

import copy
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from benchmark.blend_weights import (  # noqa: E402
    _dict,
    _headline_partition,
    _is_number,
    blend_weights_headline,
    summarize_blend_weights,
)

_REQUIRED_KEYS = frozenset({"kind", "judge", "objective", "sum"})


def _run(judge=0.6, objective=0.4):
    return {
        "composite_mean": 0.6,
        "weights": {"judge": judge, "objective": objective},
    }


# --- Input coercion -------------------------------------------------------------------------


@pytest.mark.parametrize("bad", (None, "not a dict", 42, [1, 2], ()))
def test_non_dict_artifact_coerced_to_empty_dict(bad):
    out = summarize_blend_weights(bad)
    assert out["kind"] == "invalid"
    assert out["judge"] is None
    assert out["sum"] is None


def test_dict_helper_returns_dict_or_empty():
    assert _dict({"a": 1}) == {"a": 1}
    assert _dict(None) == {}


# --- Numeric semantics ----------------------------------------------------------------------


def test_is_number_rejects_bool():
    assert not _is_number(True)
    assert not _is_number(False)


def test_is_number_accepts_numeric():
    assert _is_number(0.6)
    assert _is_number(1)


# --- Headline partition ---------------------------------------------------------------------


def test_headline_partition_single_and_generalization():
    single = _run()
    assert _headline_partition(single) is single

    art = {
        "tuned": _run(0.5, 0.5),
        "held_out": _run(0.8, 0.2),
        "generalization_gap": 0.1,
    }
    assert _headline_partition(art) is art["tuned"]


# --- Blend weights summary ------------------------------------------------------------------


def test_summarize_happy_path():
    out = summarize_blend_weights(_run())
    assert out == {
        "kind": "single",
        "judge": 0.6,
        "objective": 0.4,
        "sum": 1.0,
    }


def test_generalization_reads_tuned():
    art = {
        "tuned": _run(0.5, 0.5),
        "held_out": _run(0.8, 0.2),
        "generalization_gap": 0.1,
    }
    out = summarize_blend_weights(art)
    assert out["kind"] == "generalization"
    assert out["judge"] == 0.5
    assert out["objective"] == 0.5
    assert out["sum"] == 1.0


def test_missing_or_malformed_weights():
    missing = summarize_blend_weights({"composite_mean": 0.5})
    assert missing == {
        "kind": "single",
        "judge": None,
        "objective": None,
        "sum": None,
    }

    malformed = summarize_blend_weights({"composite_mean": 0.5, "weights": "bad"})
    assert malformed["judge"] is None
    assert malformed["sum"] is None


def test_summary_always_includes_required_keys():
    for artifact in (_run(), {"composite_mean": 0.5}, None):
        out = summarize_blend_weights(artifact)
        assert _REQUIRED_KEYS <= frozenset(out)


# --- Blend weights headline -----------------------------------------------------------------


def test_headline_exact_format():
    out = summarize_blend_weights(_run())
    assert blend_weights_headline(out) == (
        "blend weights: judge 0.6, objective 0.4 (sum 1.0)"
    )


def test_headline_unavailable_exact():
    out = summarize_blend_weights({"composite_mean": 0.5})
    assert blend_weights_headline(out) == "blend weights: unavailable"


def test_headline_non_dict_summary_coerced():
    assert blend_weights_headline("nope") == "blend weights: unavailable"


# --- Pure evaluation ------------------------------------------------------------------------


def test_summarize_does_not_mutate_artifact():
    art = _run()
    snapshot = copy.deepcopy(art)
    summarize_blend_weights(art)
    assert art == snapshot
