"""Contract tests for specs/054-benchmark-component-mix — assert component_mix.py satisfies the
spec's EARS criteria: composite_parts parsing, blend fractions, artifact-kind branches, headline
branches, and pure evaluation. Offline, deterministic.
"""

import copy
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from benchmark.component_mix import (  # noqa: E402
    _dict,
    _is_number,
    _mix_from_parts,
    _round3,
    component_mix_headline,
    summarize_component_mix,
)

_REQUIRED_KEYS = frozenset({
    "kind",
    "judge_mean",
    "objective_mean",
    "judge_fraction",
    "objective_fraction",
    "partitions",
})


def _single(judge, objective):
    return {
        "composite_mean": 0.6,
        "composite_parts": {"judge_mean": judge, "objective_mean": objective},
    }


# --- Input coercion -------------------------------------------------------------------------


@pytest.mark.parametrize("bad", (None, "not a dict", 42, [1, 2], ()))
def test_non_dict_artifact_coerced_to_empty_dict(bad):
    out = summarize_component_mix(bad)
    assert out["kind"] == "invalid"
    assert out["judge_fraction"] is None
    assert out["partitions"] is None


def test_dict_helper_returns_dict_or_empty():
    assert _dict({"a": 1}) == {"a": 1}
    assert _dict(None) == {}


# --- Numeric semantics ----------------------------------------------------------------------


def test_is_number_rejects_bool_and_nan():
    assert not _is_number(True)
    assert not _is_number(float("nan"))
    assert _is_number(0.6)


def test_round3_happy_path():
    assert _round3(0.123456) == 0.123
    assert _round3("x") is None


# --- Mix from parts -------------------------------------------------------------------------


def test_mix_from_parts_happy_path():
    assert _mix_from_parts({"judge_mean": 0.6, "objective_mean": 0.4}) == {
        "judge_mean": 0.6,
        "objective_mean": 0.4,
        "judge_fraction": 0.6,
        "objective_fraction": 0.4,
    }


def test_mix_from_parts_zero_sum_and_malformed():
    zero = _mix_from_parts({"judge_mean": 0.0, "objective_mean": 0.0})
    assert zero["judge_fraction"] is None

    malformed = _mix_from_parts(42)
    assert malformed["judge_fraction"] is None
    assert malformed["judge_mean"] is None


# --- Artifact-kind branches -----------------------------------------------------------------


def test_single_kind():
    out = summarize_component_mix(_single(0.6, 0.4))
    assert out == {
        "kind": "single",
        "judge_mean": 0.6,
        "objective_mean": 0.4,
        "judge_fraction": 0.6,
        "objective_fraction": 0.4,
        "partitions": None,
    }


def test_generalization_partitions():
    art = {
        "tuned": _single(0.8, 0.2),
        "held_out": _single(0.4, 0.6),
        "generalization_gap": 0.1,
    }
    out = summarize_component_mix(art)
    assert out["kind"] == "generalization"
    assert out["judge_fraction"] == 0.8
    assert out["partitions"]["tuned"]["judge_fraction"] == 0.8
    assert out["partitions"]["held_out"]["judge_fraction"] == 0.4


def test_summary_always_includes_required_keys():
    for artifact in (
        _single(0.6, 0.4),
        {"tuned": _single(0.7, 0.3), "held_out": _single(0.5, 0.5), "generalization_gap": 0.0},
        None,
    ):
        out = summarize_component_mix(artifact)
        assert _REQUIRED_KEYS <= frozenset(out)


# --- Component mix headline -----------------------------------------------------------------


def test_headline_single_exact_format():
    out = summarize_component_mix(_single(0.6, 0.4))
    assert component_mix_headline(out) == "component mix: judge 60.0%"


def test_headline_generalization_exact_format():
    art = {
        "tuned": _single(0.8, 0.2),
        "held_out": _single(0.5, 0.5),
        "generalization_gap": 0.1,
    }
    out = summarize_component_mix(art)
    assert component_mix_headline(out) == (
        "component mix: judge 80.0% [tuned 80.0%, held-out 50.0%]"
    )


def test_headline_nan_fraction_shows_na():
    out = {"kind": "single", "judge_fraction": float("nan"), "partitions": None}
    assert component_mix_headline(out) == "component mix: judge n/a"


# --- Pure evaluation ------------------------------------------------------------------------


def test_summarize_does_not_mutate_artifact():
    art = _single(0.6, 0.4)
    snapshot = copy.deepcopy(art)
    summarize_component_mix(art)
    assert art == snapshot
