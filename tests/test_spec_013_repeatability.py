"""Contract tests for specs/013-benchmark-repeatability — assert repeatability.py satisfies
the spec's EARS criteria: input coercion, score extraction, statistics and CV semantics,
headline branches, and pure evaluation. Offline, deterministic.
"""

import copy
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from benchmark.repeatability import (  # noqa: E402
    _repeatability_artifacts,
    _round,
    assess_repeatability,
    repeatability_headline,
)

_REQUIRED_KEYS = frozenset({
    "stable",
    "runs",
    "scores",
    "mean",
    "stddev",
    "cv",
    "min",
    "max",
    "range",
    "max_cv",
    "min_runs",
    "reason",
})


def _run(score):
    return {"composite_mean": score, "tasks": 4}


def _gen(tuned_score, held_out_score):
    return {
        "tuned": {"composite_mean": tuned_score, "scored_repos": 2},
        "held_out": {"composite_mean": held_out_score, "scored_repos": 2},
        "generalization_gap": tuned_score - held_out_score,
    }


# --- Input coercion -------------------------------------------------------------------------


def test_artifacts_helper_accepts_only_real_lists():
    runs = [_run(0.8)]
    assert _repeatability_artifacts(runs) is runs
    assert _repeatability_artifacts([]) == []
    assert _repeatability_artifacts(None) == []
    assert _repeatability_artifacts({"composite_mean": 0.8}) == []
    assert _repeatability_artifacts("not a list") == []


def test_artifacts_helper_warns_on_non_list(caplog):
    import logging

    with caplog.at_level(logging.WARNING, logger="benchmark.repeatability"):
        assert _repeatability_artifacts(42) == []
        assert _repeatability_artifacts(None) == []
    messages = [r.message for r in caplog.records]
    assert any("artifacts is int, not a list" in m for m in messages)
    assert not any("NoneType" in m for m in messages)


def test_round_helper_semantics():
    assert _round(1.23456) == 1.235
    assert _round(2) == 2.0
    assert _round(True) is None
    assert _round("0.8") is None
    assert _round(None) is None


# --- Score extraction -----------------------------------------------------------------------


def test_unscored_artifacts_are_skipped_not_counted():
    artifacts = [
        _run(0.8),
        {},                                            # no composite_mean
        {"composite_mean": "n/a"},                     # non-numeric score
        "not a dict",                                  # malformed entry
        {"scored_repos": 0, "composite_mean": 0.0},    # aggregate placeholder
        _run(0.9),
    ]
    result = assess_repeatability(artifacts)
    assert result["runs"] == 2
    assert result["scores"] == [0.8, 0.9]


def test_generalization_artifacts_score_from_tuned_partition():
    result = assess_repeatability([_gen(0.7, 0.6), _gen(0.7, 0.5)])
    assert result["runs"] == 2
    assert result["scores"] == [0.7, 0.7]
    assert result["stable"] is True


# --- Repeatability assessment ---------------------------------------------------------------


def test_result_always_includes_required_keys():
    for artifacts in ([], [_run(0.8), _run(0.9)], [_run(0.5), _run(-0.5)], None):
        result = assess_repeatability(artifacts)
        assert _REQUIRED_KEYS <= frozenset(result)


def test_insufficient_runs_reason_exact():
    result = assess_repeatability([])
    assert result["stable"] is False
    assert result["reason"] == "insufficient runs: 0 scored < min_runs 2"
    for key in ("mean", "stddev", "cv", "min", "max", "range"):
        assert result[key] is None
    single = assess_repeatability([_run(0.8)])
    assert single["reason"] == "insufficient runs: 1 scored < min_runs 2"


def test_statistics_are_rounded_to_three_decimals():
    result = assess_repeatability([_run(0.8), _run(0.9)])
    assert result["mean"] == 0.85
    assert result["stddev"] == 0.071
    assert result["cv"] == 0.084
    assert result["min"] == 0.8
    assert result["max"] == 0.9
    assert result["range"] == 0.1


def test_stddev_is_sample_not_population():
    # Population stddev of [0.8, 0.9] is 0.05; the sample (Bessel-corrected) value is ~0.0707.
    result = assess_repeatability([_run(0.8), _run(0.9)])
    assert result["stddev"] == 0.071


def test_identical_runs_have_zero_cv_even_at_zero_mean():
    result = assess_repeatability([_run(0.0), _run(0.0)])
    assert result["cv"] == 0.0
    assert result["stable"] is True
    assert result["reason"] == ""


def test_zero_mean_with_spread_yields_cv_none_reason_exact():
    result = assess_repeatability([_run(0.5), _run(-0.5)])
    assert result["mean"] == 0.0
    assert result["stddev"] == 0.707
    assert result["cv"] is None
    assert result["stable"] is False
    assert result["reason"] == "coefficient of variation undefined (zero mean with nonzero spread)"


def test_cv_boundary_is_inclusive():
    result = assess_repeatability([_run(1.0), _run(1.05), _run(0.95)])
    assert result["cv"] == 0.05
    assert result["stable"] is True
    assert result["reason"] == ""


def test_cv_exceeds_reason_exact():
    result = assess_repeatability([_run(0.8), _run(0.9)])
    assert result["stable"] is False
    assert result["reason"] == "cv 0.084 exceeds max_cv 0.05"


def test_thresholds_are_configurable():
    loose = assess_repeatability([_run(0.8), _run(0.9)], max_cv=0.09)
    assert loose["stable"] is True
    assert loose["max_cv"] == 0.09
    solo = assess_repeatability([_run(0.8)], min_runs=1)
    assert solo["runs"] == 1
    assert solo["stddev"] == 0.0
    assert solo["cv"] == 0.0
    assert solo["stable"] is True


# --- Repeatability headline -----------------------------------------------------------------


def test_headline_no_scored_runs_exact():
    assert repeatability_headline({}) == "repeatability: no scored runs"
    assert repeatability_headline("nope") == "repeatability: no scored runs"
    assert repeatability_headline(assess_repeatability([])) == "repeatability: no scored runs"


def test_headline_inconclusive_exact():
    result = assess_repeatability([_run(0.8)])
    assert repeatability_headline(result) == "repeatability: inconclusive (1 run(s))"


def test_headline_stable_exact():
    result = assess_repeatability([_run(0.8), _run(0.81)])
    assert result["stable"] is True
    assert repeatability_headline(result) == (
        "repeatability: STABLE over 2 runs (mean 0.805, cv 0.9%)"
    )


def test_headline_unstable_formats_cv_as_percentage():
    result = assess_repeatability([_run(0.8), _run(0.9)])
    assert repeatability_headline(result) == (
        "repeatability: UNSTABLE over 2 runs (mean 0.85, cv 8.4%)"
    )


def test_headline_renders_na_for_undefined_cv():
    result = assess_repeatability([_run(0.5), _run(-0.5)])
    assert repeatability_headline(result) == (
        "repeatability: UNSTABLE over 2 runs (mean 0.0, cv n/a)"
    )


# --- Pure evaluation ------------------------------------------------------------------------


def test_assess_does_not_mutate_input():
    artifacts = [_run(0.8), _gen(0.7, 0.6), {"composite_mean": "n/a"}]
    snapshot = copy.deepcopy(artifacts)
    assess_repeatability(artifacts)
    assert artifacts == snapshot
