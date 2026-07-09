"""Tests for the PR benchmark-delta scorer (anti-Goodhart label-eligibility policy)."""

import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from scripts.score_pr_delta import (  # noqa: E402
    DEFAULT_BREAKTHROUGH_MULTIPLE,
    _improved,
    _regressed,
    headline,
    score_pr_delta,
)


def _artifact(composite_mean, judge_mean, objective_mean):
    return {
        "composite_mean": composite_mean,
        "composite_parts": {"judge_mean": judge_mean, "objective_mean": objective_mean},
    }


def test_regressed_and_improved_respect_the_noise_floor():
    assert _regressed(-0.02, 0.01) is True
    assert _regressed(-0.005, 0.01) is False  # within noise, not a real regression
    assert _regressed(None, 0.01) is False
    assert _improved(0.02, 0.01) is True
    assert _improved(0.005, 0.01) is False
    assert _improved(None, 0.01) is False


def test_real_improvement_with_no_regression_is_eligible():
    """A modest, real improvement on both axes — past the noise floor but below the
    breakthrough floor — lands at plain "eligible", not the ceiling tier."""
    baseline = _artifact(0.60, 0.55, 0.65)
    candidate = _artifact(0.63, 0.57, 0.68)
    report = score_pr_delta(baseline, candidate)
    assert report["eligible_for_high_tier"] is True
    assert report["tier"] == "eligible"
    assert report["blocks_merge"] is False
    assert "improved" in report["reason"]


def test_large_improvement_on_both_axes_is_breakthrough():
    """Composite improves by well past the breakthrough floor (>= 5x noise floor) AND
    both judge and objective individually improve — the ceiling tier."""
    baseline = _artifact(0.60, 0.55, 0.65)
    candidate = _artifact(0.68, 0.60, 0.72)
    report = score_pr_delta(baseline, candidate)
    assert report["eligible_for_high_tier"] is True
    assert report["tier"] == "breakthrough"
    assert report["blocks_merge"] is False
    assert "breakthrough" not in report["reason"]  # reason describes the measurement, not the label name
    assert "both judge and objective" in report["reason"]


def test_breakthrough_requires_both_axes_to_improve_not_just_composite():
    """A large composite jump driven by only ONE axis improving (the other flat within
    noise) must NOT reach breakthrough — that's still a single-axis win, not a genuine
    win on every measured dimension."""
    baseline = _artifact(0.60, 0.55, 0.65)
    # objective_mean barely moves (within noise); judge_mean carries the whole composite rise.
    candidate = _artifact(0.68, 0.75, 0.652)
    report = score_pr_delta(baseline, candidate)
    assert report["composite_deltas"]["composite_mean"] >= report["breakthrough_floor"]
    assert report["tier"] == "eligible"  # not "breakthrough" — objective_mean didn't really move


def test_goodhart_trade_off_is_rejected_even_though_composite_rose():
    """The Pareto-floor case: composite_mean goes UP only because objective_mean was
    quietly sacrificed for a higher judge_mean. A naive composite-only check would call
    this eligible; the floor must catch it."""
    baseline = _artifact(0.60, 0.55, 0.65)
    candidate = _artifact(0.63, 0.85, 0.30)
    report = score_pr_delta(baseline, candidate)
    assert report["composite_deltas"]["composite_mean"] > 0  # composite really did rise
    assert report["eligible_for_high_tier"] is False
    assert report["tier"] == "blocked"
    assert report["blocks_merge"] is True
    assert "regressed" in report["reason"]


def test_within_noise_floor_is_not_eligible():
    baseline = _artifact(0.60, 0.55, 0.65)
    candidate = _artifact(0.605, 0.552, 0.651)
    report = score_pr_delta(baseline, candidate)
    assert report["eligible_for_high_tier"] is False
    assert report["tier"] == "neutral"
    assert report["blocks_merge"] is False
    assert "no measurable improvement" in report["reason"]


def test_outright_regression_is_not_eligible():
    baseline = _artifact(0.60, 0.55, 0.65)
    candidate = _artifact(0.40, 0.35, 0.45)
    report = score_pr_delta(baseline, candidate)
    assert report["eligible_for_high_tier"] is False
    assert report["tier"] == "blocked"
    assert report["blocks_merge"] is True


def test_generalization_shaped_artifacts_are_scored_per_partition():
    baseline = {
        "repo_set": "curated", "generalization_gap": 0.1,
        "tuned": {"composite_mean": 0.6, "scored_repos": 3},
        "held_out": {"composite_mean": 0.5, "scored_repos": 2},
    }
    candidate = {
        "repo_set": "curated", "generalization_gap": 0.05,
        "tuned": {"composite_mean": 0.68, "scored_repos": 3},
        "held_out": {"composite_mean": 0.60, "scored_repos": 2},
    }
    report = score_pr_delta(baseline, candidate)
    assert report["eligible_for_high_tier"] is True
    assert report["tier"] == "eligible"  # breakthrough is never reached at this shape
    assert report["pareto_axes"] == {}  # no judge/objective split at this shape


def test_generalization_shaped_artifact_catches_a_held_out_regression():
    """Even if the tuned partition improves, a held-out regression must block eligibility —
    otherwise a PR could overfit the tuned set and still qualify."""
    baseline = {
        "repo_set": "curated", "generalization_gap": 0.1,
        "tuned": {"composite_mean": 0.6, "scored_repos": 3},
        "held_out": {"composite_mean": 0.5, "scored_repos": 2},
    }
    candidate = {
        "repo_set": "curated", "generalization_gap": 0.3,
        "tuned": {"composite_mean": 0.75, "scored_repos": 3},
        "held_out": {"composite_mean": 0.30, "scored_repos": 2},
    }
    report = score_pr_delta(baseline, candidate)
    assert report["eligible_for_high_tier"] is False
    assert report["tier"] == "blocked"
    assert report["blocks_merge"] is True


def test_missing_composite_parts_excludes_pareto_axis_rather_than_failing_open_or_closed():
    """An artifact with no composite_parts (e.g. a bare single-repo run) can't be judged on
    a per-axis floor it never reported — the axis is excluded, not treated as pass or fail."""
    baseline = {"composite_mean": 0.5}
    candidate = {"composite_mean": 0.6}
    report = score_pr_delta(baseline, candidate)
    assert report["pareto_axes"] == {"judge_mean": None, "objective_mean": None}
    assert report["eligible_for_high_tier"] is True  # composite improved, no axis data to fail on
    assert report["tier"] == "eligible"  # can't confirm both axes improved -> never breakthrough


def test_custom_noise_floor_is_honored():
    baseline = _artifact(0.60, 0.55, 0.65)
    candidate = _artifact(0.62, 0.57, 0.67)
    default_report = score_pr_delta(baseline, candidate)
    assert default_report["eligible_for_high_tier"] is True  # 0.02 > default 0.01 floor

    strict_report = score_pr_delta(baseline, candidate, noise_floor=0.05)
    assert strict_report["eligible_for_high_tier"] is False  # 0.02 < 0.05 floor


def test_custom_breakthrough_multiple_is_honored():
    baseline = _artifact(0.60, 0.55, 0.65)
    candidate = _artifact(0.63, 0.57, 0.68)  # composite +0.03, both axes improve past noise floor
    default_report = score_pr_delta(baseline, candidate)
    assert default_report["tier"] == "eligible"  # 0.03 < default breakthrough floor (5x0.01=0.05)

    lenient_report = score_pr_delta(baseline, candidate, breakthrough_multiple=2.0)
    assert lenient_report["breakthrough_floor"] == 0.02
    assert lenient_report["tier"] == "breakthrough"  # 0.03 >= 2x0.01=0.02, both axes improve


def test_default_breakthrough_multiple_constant_is_five():
    assert DEFAULT_BREAKTHROUGH_MULTIPLE == 5.0


def test_headline_reports_eligibility_verdict():
    eligible = {"tier": "eligible", "eligible_for_high_tier": True, "reason": "composite_mean improved"}
    not_eligible = {"tier": "neutral", "eligible_for_high_tier": False, "reason": "no measurable improvement"}
    blocked = {"tier": "blocked", "eligible_for_high_tier": False, "reason": "a scored dimension regressed"}
    breakthrough = {"tier": "breakthrough", "eligible_for_high_tier": True, "reason": "large real improvement"}
    assert "ELIGIBLE" in headline(eligible)
    assert "not eligible" in headline(not_eligible)
    assert "BLOCKED" in headline(blocked)
    assert "BREAKTHROUGH" in headline(breakthrough)


def test_cli_end_to_end_writes_a_report(tmp_path):
    baseline_path = tmp_path / "baseline.json"
    candidate_path = tmp_path / "candidate.json"
    out_path = tmp_path / "report.json"
    baseline_path.write_text(json.dumps(_artifact(0.60, 0.55, 0.65)))
    candidate_path.write_text(json.dumps(_artifact(0.68, 0.60, 0.72)))

    result = subprocess.run(
        [sys.executable, "-m", "scripts.score_pr_delta",
         str(baseline_path), str(candidate_path), "--out", str(out_path)],
        cwd=ROOT, capture_output=True, text=True,
    )
    assert result.returncode == 0
    report = json.loads(out_path.read_text())
    assert report["eligible_for_high_tier"] is True
    assert report["tier"] == "breakthrough"
    assert "score_pr_delta: BREAKTHROUGH" in result.stderr
