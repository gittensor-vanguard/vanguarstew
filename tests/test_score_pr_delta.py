"""Tests for the PR benchmark-delta scorer (measured perf:xs..xl bands + Pareto merge-block)."""

import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from scripts.score_pr_delta import (  # noqa: E402
    BAND_MULTIPLIERS,
    BAND_THRESHOLDS,
    _band_for_delta,
    _regressed,
    combine_dual_target,
    headline,
    score_pr_delta,
)


def _artifact(composite_mean, judge_mean, objective_mean):
    return {
        "composite_mean": composite_mean,
        "composite_parts": {"judge_mean": judge_mean, "objective_mean": objective_mean},
    }


def test_regressed_respects_the_noise_floor():
    assert _regressed(-0.02, 0.01) is True
    assert _regressed(-0.005, 0.01) is False  # within noise, not a real regression
    assert _regressed(None, 0.01) is False


def test_band_for_delta_buckets_by_threshold():
    assert _band_for_delta(None, 0.01) == "none"
    assert _band_for_delta(0.005, 0.01) == "none"          # within noise
    assert _band_for_delta(0.01, 0.01) == "none"            # at the floor, not past it
    assert _band_for_delta(0.015, 0.01) == "xs"
    assert _band_for_delta(0.02, 0.01) == "s"
    assert _band_for_delta(0.04, 0.01) == "m"
    assert _band_for_delta(0.08, 0.01) == "l"
    assert _band_for_delta(0.15, 0.01) == "xl"
    assert _band_for_delta(0.50, 0.01) == "xl"               # anything past xl's floor is still xl


def test_band_thresholds_and_multipliers_are_ordered_and_complete():
    names = [n for n, _ in BAND_THRESHOLDS]
    assert names == ["xs", "s", "m", "l", "xl"]
    floors = [f for _, f in BAND_THRESHOLDS]
    assert floors == sorted(floors)  # strictly ascending
    assert set(BAND_MULTIPLIERS) == set(names)
    # multipliers rise with band
    ordered_mults = [BAND_MULTIPLIERS[n] for n in names]
    assert ordered_mults == sorted(ordered_mults)


def test_small_real_improvement_earns_the_xs_band():
    baseline = _artifact(0.60, 0.55, 0.65)
    candidate = _artifact(0.615, 0.56, 0.67)  # composite +0.015
    report = score_pr_delta(baseline, candidate)
    assert report["band"] == "xs"
    assert report["label"] == "perf:xs"
    assert report["multiplier"] == BAND_MULTIPLIERS["xs"]
    assert report["blocks_merge"] is False


def test_large_improvement_earns_the_xl_band():
    baseline = _artifact(0.60, 0.55, 0.65)
    candidate = _artifact(0.80, 0.75, 0.85)  # composite +0.20
    report = score_pr_delta(baseline, candidate)
    assert report["band"] == "xl"
    assert report["label"] == "perf:xl"
    assert report["multiplier"] == BAND_MULTIPLIERS["xl"]


def test_goodhart_trade_off_is_blocked_even_though_composite_rose():
    """The Pareto-floor case: composite_mean goes UP only because objective_mean was
    quietly sacrificed for a higher judge_mean. A naive composite-only check would band
    this; the floor must block it instead."""
    baseline = _artifact(0.60, 0.55, 0.65)
    candidate = _artifact(0.63, 0.85, 0.30)
    report = score_pr_delta(baseline, candidate)
    assert report["composite_deltas"]["composite_mean"] > 0  # composite really did rise
    assert report["band"] == "blocked"
    assert report["blocks_merge"] is True
    assert report["label"] is None
    assert report["multiplier"] is None
    assert "regressed" in report["reason"]


def test_within_noise_floor_earns_no_band_but_still_mergeable():
    baseline = _artifact(0.60, 0.55, 0.65)
    candidate = _artifact(0.605, 0.552, 0.651)
    report = score_pr_delta(baseline, candidate)
    assert report["band"] == "none"
    assert report["label"] is None
    assert report["multiplier"] is None
    assert report["blocks_merge"] is False
    assert "no measurable improvement" in report["reason"]


def test_outright_regression_is_blocked():
    baseline = _artifact(0.60, 0.55, 0.65)
    candidate = _artifact(0.40, 0.35, 0.45)
    report = score_pr_delta(baseline, candidate)
    assert report["band"] == "blocked"
    assert report["blocks_merge"] is True


def test_generalization_shaped_artifacts_use_the_minimum_partition_delta():
    baseline = {
        "repo_set": "curated", "generalization_gap": 0.1,
        "tuned": {"composite_mean": 0.6, "scored_repos": 3},
        "held_out": {"composite_mean": 0.5, "scored_repos": 2},
    }
    candidate = {
        "repo_set": "curated", "generalization_gap": 0.05,
        "tuned": {"composite_mean": 0.68, "scored_repos": 3},   # +0.08 -> l on its own
        "held_out": {"composite_mean": 0.53, "scored_repos": 2},  # +0.03 -> s on its own
    }
    report = score_pr_delta(baseline, candidate)
    assert report["band"] == "s"  # gated by the WORSE (held_out) partition, not the better one
    assert report["pareto_axes"] == {}  # no judge/objective split at this shape


def test_generalization_shaped_artifact_catches_a_held_out_regression():
    """Even if the tuned partition improves, a held-out regression must block — otherwise
    a PR could overfit the tuned set and still earn a band."""
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
    assert report["band"] == "blocked"
    assert report["blocks_merge"] is True


def test_missing_composite_parts_excludes_pareto_axis_rather_than_failing_open_or_closed():
    """An artifact with no composite_parts (e.g. a bare single-repo run) can't be judged on
    a per-axis floor it never reported — the axis is excluded, not treated as pass or fail."""
    baseline = {"composite_mean": 0.5}
    candidate = {"composite_mean": 0.6}  # +0.10 -> l band
    report = score_pr_delta(baseline, candidate)
    assert report["pareto_axes"] == {"judge_mean": None, "objective_mean": None}
    assert report["band"] == "l"  # composite improved into a band, no axis data to block on


def test_custom_noise_floor_is_honored():
    baseline = _artifact(0.60, 0.55, 0.65)
    candidate = _artifact(0.62, 0.57, 0.67)
    default_report = score_pr_delta(baseline, candidate)
    assert default_report["band"] != "none"  # 0.02 > default 0.01 floor

    strict_report = score_pr_delta(baseline, candidate, noise_floor=0.05)
    assert strict_report["band"] == "none"  # 0.02 < 0.05 floor


def test_headline_reports_the_band():
    banded = {"band": "l", "reason": "composite_mean improved into the perf:l band"}
    none_band = {"band": "none", "reason": "no measurable improvement"}
    blocked = {"band": "blocked", "reason": "a scored dimension regressed"}
    assert "perf:l" in headline(banded)
    assert "no band" in headline(none_band)
    assert "BLOCKED" in headline(blocked)


def test_combine_dual_target_takes_the_minimum_band():
    public_report = score_pr_delta(_artifact(0.60, 0.55, 0.65), _artifact(0.80, 0.75, 0.85))  # xl
    private_report = score_pr_delta(_artifact(0.60, 0.55, 0.65), _artifact(0.615, 0.56, 0.67))  # xs
    combined = combine_dual_target(public_report, private_report)
    assert combined["band"] == "xs"
    assert combined["label"] == "perf:xs"
    assert combined["multiplier"] == BAND_MULTIPLIERS["xs"]
    assert combined["blocks_merge"] is False
    assert combined["public"] is public_report
    assert combined["private"] is private_report


def test_combine_dual_target_blocks_if_either_target_regresses():
    """A PR that looks great on the public set but regresses on the private hidden set
    must not merge — the private target exists precisely to catch this."""
    public_report = score_pr_delta(_artifact(0.60, 0.55, 0.65), _artifact(0.80, 0.75, 0.85))  # xl
    private_report = score_pr_delta(_artifact(0.60, 0.55, 0.65), _artifact(0.63, 0.85, 0.30))  # blocked
    combined = combine_dual_target(public_report, private_report)
    assert combined["band"] == "blocked"
    assert combined["blocks_merge"] is True
    assert combined["label"] is None
    assert "private" in combined["reason"]


def test_combine_dual_target_no_band_if_either_target_shows_nothing():
    public_report = score_pr_delta(_artifact(0.60, 0.55, 0.65), _artifact(0.80, 0.75, 0.85))  # xl
    private_report = score_pr_delta(_artifact(0.60, 0.55, 0.65), _artifact(0.605, 0.552, 0.651))  # none
    combined = combine_dual_target(public_report, private_report)
    assert combined["band"] == "none"
    assert combined["label"] is None
    assert combined["blocks_merge"] is False


def test_cli_end_to_end_writes_a_report(tmp_path):
    baseline_path = tmp_path / "baseline.json"
    candidate_path = tmp_path / "candidate.json"
    out_path = tmp_path / "report.json"
    baseline_path.write_text(json.dumps(_artifact(0.60, 0.55, 0.65)))
    candidate_path.write_text(json.dumps(_artifact(0.80, 0.75, 0.85)))

    result = subprocess.run(
        [sys.executable, "-m", "scripts.score_pr_delta",
         str(baseline_path), str(candidate_path), "--out", str(out_path)],
        cwd=ROOT, capture_output=True, text=True,
    )
    assert result.returncode == 0
    report = json.loads(out_path.read_text())
    assert report["band"] == "xl"
    assert report["label"] == "perf:xl"
    assert "score_pr_delta: perf:xl" in result.stderr
