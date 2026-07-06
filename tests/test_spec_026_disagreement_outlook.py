"""Contract tests for specs/026-benchmark-disagreement-outlook — assert
disagreement_outlook.summarize_disagreement_outlook and disagreement_outlook_headline satisfy the
spec's EARS criteria: telemetry extraction, threshold handling, verdict rules, headline
formatting, and pure evaluation. Offline, deterministic.
"""

import copy
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from benchmark.disagreement_outlook import (  # noqa: E402
    DEFAULT_STABLE_THRESHOLD,
    disagreement_outlook_headline,
    summarize_disagreement_outlook,
)

_NON_DICT_ARTIFACTS = [None, 42, 3.14, True, "oops", [], (), b"bytes"]
_NON_FINITE_THRESHOLDS = [float("nan"), float("inf"), float("-inf"), True, "0.2", None]


def _artifact(rate=0.1, dual=4, source="judge_report"):
    return {
        "composite_mean": 0.6,
        source: {"dual_order_tasks": dual, "disagreement_rate": rate},
    }


# --- Input guard --------------------------------------------------------------------------


@pytest.mark.parametrize("bad", _NON_DICT_ARTIFACTS)
def test_non_dict_artifact_kind_invalid(bad):
    out = summarize_disagreement_outlook(bad)
    assert out["kind"] == "invalid"
    assert out["verdict"] is None
    assert out["disagreement_rate"] is None


# --- Telemetry source ---------------------------------------------------------------------


def test_reads_judge_report_telemetry():
    out = summarize_disagreement_outlook(_artifact(0.1, 5))
    assert out["dual_order_tasks"] == 5
    assert out["disagreement_rate"] == 0.1


def test_falls_back_to_judge_order_stats():
    art = {
        "composite_mean": 0.6,
        "judge_order_stats": {"dual_order_tasks": 2, "disagreement_rate": 0.0},
    }
    out = summarize_disagreement_outlook(art)
    assert out["dual_order_tasks"] == 2
    assert out["disagreement_rate"] == 0.0


def test_missing_telemetry_yields_none_fields():
    out = summarize_disagreement_outlook({"composite_mean": 0.5})
    assert out["dual_order_tasks"] is None
    assert out["disagreement_rate"] is None
    assert out["verdict"] is None


def test_judge_report_preferred_over_judge_order_stats():
    art = _artifact(0.2, 3)
    art["judge_order_stats"] = {"dual_order_tasks": 99, "disagreement_rate": 0.9}
    out = summarize_disagreement_outlook(art)
    assert out["dual_order_tasks"] == 3
    assert out["disagreement_rate"] == 0.2


# --- dual_order_tasks ---------------------------------------------------------------------


def test_dual_order_tasks_zero_is_valid():
    out = summarize_disagreement_outlook(_artifact(0.0, 0))
    assert out["dual_order_tasks"] == 0


def test_dual_order_tasks_negative_rejected():
    out = summarize_disagreement_outlook(_artifact(0.1, -1))
    assert out["dual_order_tasks"] is None


def test_dual_order_tasks_float_and_bool_rejected():
    art = _artifact(0.1, 2)
    art["judge_report"]["dual_order_tasks"] = 2.5
    assert summarize_disagreement_outlook(art)["dual_order_tasks"] is None
    art["judge_report"]["dual_order_tasks"] = True
    assert summarize_disagreement_outlook(art)["dual_order_tasks"] is None


# --- disagreement_rate --------------------------------------------------------------------


def test_disagreement_rate_rounded_to_three_decimals():
    art = _artifact(0.123456, 2)
    assert summarize_disagreement_outlook(art)["disagreement_rate"] == 0.123


def test_nan_and_inf_rate_yield_none():
    assert summarize_disagreement_outlook(_artifact(float("nan"), 2))["disagreement_rate"] is None
    assert summarize_disagreement_outlook(_artifact(float("inf"), 2))["disagreement_rate"] is None
    assert summarize_disagreement_outlook(_artifact(float("-inf"), 2))["disagreement_rate"] is None


def test_bool_disagreement_rate_rejected():
    art = _artifact(0.1, 2)
    art["judge_report"]["disagreement_rate"] = True
    assert summarize_disagreement_outlook(art)["disagreement_rate"] is None


# --- Verdict ------------------------------------------------------------------------------


def test_verdict_stable_below_threshold():
    out = summarize_disagreement_outlook(_artifact(0.1, 4))
    assert out["verdict"] == "stable"


def test_verdict_unstable_above_threshold():
    out = summarize_disagreement_outlook(_artifact(0.5, 3))
    assert out["verdict"] == "unstable"


def test_verdict_stable_at_threshold_boundary():
    out = summarize_disagreement_outlook(_artifact(DEFAULT_STABLE_THRESHOLD, 2))
    assert out["verdict"] == "stable"


def test_verdict_none_when_rate_unavailable():
    out = summarize_disagreement_outlook(_artifact(float("nan"), 2))
    assert out["verdict"] is None


# --- Threshold parameter ------------------------------------------------------------------


def test_default_threshold_constant():
    assert DEFAULT_STABLE_THRESHOLD == 0.3
    out = summarize_disagreement_outlook(_artifact(0.1, 2))
    assert out["stable_threshold"] == DEFAULT_STABLE_THRESHOLD


def test_custom_threshold_applied():
    out = summarize_disagreement_outlook(_artifact(0.25, 2), stable_threshold=0.2)
    assert out["stable_threshold"] == 0.2
    assert out["verdict"] == "unstable"


@pytest.mark.parametrize("bad", _NON_FINITE_THRESHOLDS)
def test_non_finite_threshold_falls_back_to_default(bad):
    out = summarize_disagreement_outlook(_artifact(0.1, 2), stable_threshold=bad)
    assert out["stable_threshold"] == DEFAULT_STABLE_THRESHOLD


# --- Artifact kind ------------------------------------------------------------------------


def test_kind_from_artifact_kind():
    assert summarize_disagreement_outlook(_artifact())["kind"] == "single"
    multi = _artifact()
    multi["per_repo"] = []
    assert summarize_disagreement_outlook(multi)["kind"] == "multi"


# --- Headline -----------------------------------------------------------------------------


def test_headline_formats_finite_rate_and_verdict():
    out = summarize_disagreement_outlook(_artifact(0.2, 3))
    line = disagreement_outlook_headline(out)
    assert "stable" in line
    assert "20.0%" in line
    assert "3 dual-order task(s)" in line


def test_headline_shows_na_for_missing_rate():
    out = summarize_disagreement_outlook(_artifact(float("nan"), 2))
    line = disagreement_outlook_headline(out)
    assert "n/a" in line
    assert "unknown" in line


def test_headline_shows_na_for_missing_dual_order_tasks():
    out = summarize_disagreement_outlook(_artifact(0.1, -1))
    line = disagreement_outlook_headline(out)
    assert "n/a dual-order task(s)" in line


def test_headline_non_dict_summary_treated_as_empty():
    line = disagreement_outlook_headline([])
    assert "unknown" in line
    assert "n/a" in line


# --- Pure evaluation ----------------------------------------------------------------------


def test_does_not_mutate_artifact():
    art = _artifact(0.1, 4)
    snapshot = copy.deepcopy(art)
    summarize_disagreement_outlook(art)
    assert art == snapshot


def test_no_io_imports():
    import benchmark.disagreement_outlook as mod

    source = open(mod.__file__, encoding="utf-8").read()
    assert "open(" not in source
    assert "requests" not in source
    assert "urllib" not in source
