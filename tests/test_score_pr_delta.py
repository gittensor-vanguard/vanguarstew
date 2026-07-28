"""Tests for the PR benchmark-delta scorer (measured perf:xs..xl bands + Pareto merge-block)."""

import json
import os
import subprocess
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from scripts.score_pr_delta import (  # noqa: E402
    BAND_MULTIPLIERS,
    BAND_THRESHOLDS,
    PARETO_AXES,
    _band_for_delta,
    _corrupt_pareto_axes,
    _foresight_of,
    _regressed,
    combine_dual_target,
    headline,
    run,
    score_pr_delta,
)

NAN = float("nan")
INF = float("inf")
OVERSIZED_INT = 10 ** 400  # json-parseable, but float() raises OverflowError


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
    # Neither partition reported composite_parts here, so there's no per-axis data to split on
    # (same "unavailable" shape the non-generalization path reports for the same reason).
    assert report["pareto_axes"] == {"judge_mean": None, "objective_mean": None}


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


def _gen_part(judge_mean, objective_mean, scored_repos=3):
    return {
        "scored_repos": scored_repos,
        "composite_mean": round((judge_mean + objective_mean) / 2, 3),
        "composite_parts": {"judge_mean": judge_mean, "objective_mean": objective_mean},
    }


def test_generalization_pareto_floor_catches_an_axis_regression_behind_a_net_gain():
    """#1821: a generalization artifact that games judge_mean up while objective_mean craters
    must be blocked, even though the net composite_mean move is positive in both partitions —
    exactly the case the Pareto floor exists to catch, and previously slipped through because
    the generalization diff never carried composite_parts at all."""
    baseline = {
        "repo_set": "curated", "generalization_gap": 0.0,
        "tuned": _gen_part(0.55, 0.60), "held_out": _gen_part(0.55, 0.60),
    }
    candidate = {
        "repo_set": "curated", "generalization_gap": 0.0,
        "tuned": _gen_part(1.0, 0.20), "held_out": _gen_part(1.0, 0.20),
    }
    report = score_pr_delta(baseline, candidate)
    assert report["composite_deltas"]["tuned"] > 0  # net composite move looks like an improvement
    assert report["pareto_axes"]["objective_mean"]["delta"] == -0.4
    assert report["band"] == "blocked"
    assert report["blocks_merge"] is True


def test_generalization_pareto_axes_report_the_worse_partition_per_axis():
    """The reported axis triplet is the worse of the two partitions, mirroring how the
    composite banding already uses the worse partition's delta."""
    baseline = {
        "repo_set": "curated", "generalization_gap": 0.0,
        "tuned": _gen_part(0.60, 0.60), "held_out": _gen_part(0.60, 0.60),
    }
    candidate = {
        "repo_set": "curated", "generalization_gap": 0.0,
        "tuned": _gen_part(0.60, 0.55),       # objective_mean -0.05 (mild)
        "held_out": _gen_part(0.60, 0.30),    # objective_mean -0.30 (severe) -- must win
    }
    report = score_pr_delta(baseline, candidate)
    assert report["pareto_axes"]["objective_mean"]["delta"] == -0.3
    assert report["band"] == "blocked"


def test_missing_composite_parts_excludes_pareto_axis_rather_than_failing_open_or_closed():
    """An artifact with no composite_parts (e.g. a bare single-repo run) can't be judged on
    a per-axis floor it never reported — the axis is excluded, not treated as pass or fail."""
    baseline = {"composite_mean": 0.5}
    candidate = {"composite_mean": 0.6}  # +0.10 -> l band
    report = score_pr_delta(baseline, candidate)
    assert report["pareto_axes"] == {"judge_mean": None, "objective_mean": None}
    assert report["band"] == "l"  # composite improved into a band, no axis data to block on


# --- #1867: a REPORTED but non-finite Pareto axis must fail closed, not read as unavailable ---

def test_pareto_axes_constant_covers_both_scored_components():
    assert PARETO_AXES == ("judge_mean", "objective_mean")


@pytest.mark.parametrize("bad", [NAN, INF, -INF, OVERSIZED_INT, "0.9", None, [], {}])
def test_corrupt_pareto_axes_flags_a_reported_but_unusable_value(bad):
    """Every value compare_eval._numeric refuses to convert is corrupt when REPORTED."""
    assert _corrupt_pareto_axes({"composite_parts": {"judge_mean": bad}}) == ["judge_mean"]


@pytest.mark.parametrize("good", [0.0, 0.5, 1, -0.25])
def test_corrupt_pareto_axes_accepts_a_finite_number(good):
    assert _corrupt_pareto_axes({"composite_parts": {"judge_mean": good}}) == []


def test_corrupt_pareto_axes_ignores_an_axis_that_was_never_reported():
    """An axis absent from composite_parts is *unavailable*, not corrupt — it stays excluded
    from the floor rather than blocking (the pre-existing contract)."""
    assert _corrupt_pareto_axes({"composite_parts": {"judge_mean": 0.5}}) == []
    assert _corrupt_pareto_axes({"composite_mean": 0.5}) == []
    assert _corrupt_pareto_axes({}) == []


def test_corrupt_pareto_axes_masks_an_unscored_runs_placeholder_parts():
    """A run that scored nothing reports 0.0 placeholders, which compare_eval already masks.
    Unavailable is not corrupt: such a run must keep its existing non-blocking behaviour."""
    unscored = {"composite_parts": {"judge_mean": NAN, "objective_mean": NAN}, "scored_repos": 0}
    assert _corrupt_pareto_axes(unscored) == []


def test_corrupt_pareto_axes_reports_each_axis_once_sorted_across_artifacts():
    a = {"composite_parts": {"judge_mean": NAN, "objective_mean": INF}}
    b = {"composite_parts": {"judge_mean": NAN}}
    assert _corrupt_pareto_axes(a, b) == ["judge_mean", "objective_mean"]


def test_corrupt_pareto_axes_tolerates_a_non_dict_artifact_or_parts():
    assert _corrupt_pareto_axes(None, "nope", 3, {"composite_parts": "nope"}) == []


def test_non_finite_judge_mean_blocks_instead_of_minting_a_perf_label():
    """#1867 headline case: a NaN judge_mean is nulled by compare_eval, so the floor used to
    read the axis as unavailable — the composite rose on the other axis and still earned
    perf:xl. It must fail closed instead."""
    baseline = _artifact(0.5, 0.5, 0.5)
    candidate = _artifact(0.7, NAN, 0.7)
    report = score_pr_delta(baseline, candidate)
    assert report["band"] == "blocked"
    assert report["blocks_merge"] is True
    assert report["label"] is None            # no perf:* label can be minted
    assert report["multiplier"] is None       # and therefore no gittensor multiplier
    assert report["corrupt_axes"] == ["judge_mean"]
    assert "non-finite" in report["reason"] and "judge_mean" in report["reason"]
    # the composite genuinely rose — this is blocked on the corrupt axis, not on a regression
    assert report["composite_deltas"]["composite_mean"] > 0


@pytest.mark.parametrize("axis", ["judge_mean", "objective_mean"])
@pytest.mark.parametrize("bad", [NAN, INF, -INF, OVERSIZED_INT])
def test_either_axis_corrupt_on_either_side_blocks(axis, bad):
    """Both axes and both sides are guarded: a corrupt baseline reading leaves the delta just
    as uncertifiable as a corrupt candidate one."""
    for side in ("baseline", "candidate"):
        parts = {"judge_mean": 0.5, "objective_mean": 0.5}
        parts[axis] = bad
        corrupt, clean = _artifact(0.5, **parts), _artifact(0.7, 0.7, 0.7)
        report = score_pr_delta(*(corrupt, clean) if side == "baseline" else (clean, corrupt))
        assert report["band"] == "blocked", (axis, bad, side)
        assert report["corrupt_axes"] == [axis]


def test_an_outright_regression_is_still_reported_as_a_regression():
    """Precedence: a real measured regression keeps its own reason — the corrupt-axis branch
    must not swallow the more actionable message."""
    report = score_pr_delta(_artifact(0.60, 0.55, 0.65), _artifact(0.63, 0.85, 0.30))
    assert report["band"] == "blocked"
    assert "regressed" in report["reason"]
    assert report["corrupt_axes"] == []


def test_clean_artifacts_report_no_corrupt_axes_and_keep_their_band():
    report = score_pr_delta(_artifact(0.5, 0.5, 0.5), _artifact(0.7, 0.7, 0.7))
    assert report["band"] == "xl"
    assert report["blocks_merge"] is False
    assert report["corrupt_axes"] == []


def test_an_unscored_candidate_is_not_blocked_as_corrupt():
    """Guard against over-blocking: an unscored run's masked 0.0 parts produce the SAME
    ``delta: None`` diff shape as a corrupt axis, but it stays mergeable-with-no-band."""
    baseline = dict(_artifact(0.5, 0.5, 0.5), scored_repos=3)
    candidate = dict(_artifact(0.0, 0.0, 0.0), scored_repos=0)
    report = score_pr_delta(baseline, candidate)
    assert report["corrupt_axes"] == []
    assert report["band"] == "none"
    assert report["blocks_merge"] is False


def test_generalization_corrupt_axis_blocks_even_behind_a_healthy_partition():
    """A corrupt axis in ONE partition used to vanish: _generalization_pareto_axes keeps the
    worse *usable* delta, so the healthy partition's reading masked it entirely."""
    baseline = {
        "repo_set": "curated", "generalization_gap": 0.0,
        "tuned": _gen_part(0.5, 0.5), "held_out": _gen_part(0.5, 0.5),
    }
    candidate = {
        "repo_set": "curated", "generalization_gap": 0.0,
        "tuned": _gen_part(0.7, 0.7),        # healthy
        "held_out": _gen_part(NAN, 0.7),     # corrupt judge axis
    }
    report = score_pr_delta(baseline, candidate)
    assert report["band"] == "blocked"
    assert report["blocks_merge"] is True
    assert report["label"] is None
    assert report["corrupt_axes"] == ["judge_mean"]


def test_generalization_unscored_partition_is_not_blocked_as_corrupt():
    baseline = {
        "repo_set": "curated", "generalization_gap": 0.0,
        "tuned": _gen_part(0.5, 0.5), "held_out": _gen_part(0.5, 0.5),
    }
    candidate = {
        "repo_set": "curated", "generalization_gap": 0.0,
        "tuned": _gen_part(0.7, 0.7),
        "held_out": _gen_part(0.0, 0.0, scored_repos=0),
    }
    report = score_pr_delta(baseline, candidate)
    assert report["corrupt_axes"] == []
    assert report["blocks_merge"] is False


def test_headline_surfaces_the_corrupt_axis_reason():
    report = score_pr_delta(_artifact(0.5, 0.5, 0.5), _artifact(0.7, NAN, 0.7))
    line = headline(report)
    assert "BLOCKED" in line
    assert "judge_mean" in line


def test_corrupt_axis_survives_a_json_round_trip_through_the_cli(tmp_path):
    """End-to-end: a NaN written by a real eval run reaches the report as a block, not a band.
    json.dump emits bare NaN and json.load reads it back as float('nan')."""
    baseline_path = tmp_path / "baseline.json"
    candidate_path = tmp_path / "candidate.json"
    out_path = tmp_path / "report.json"
    baseline_path.write_text(json.dumps(_artifact(0.5, 0.5, 0.5)))
    candidate_path.write_text(json.dumps(_artifact(0.7, NAN, 0.7)))

    result = subprocess.run(
        [sys.executable, "-m", "scripts.score_pr_delta",
         str(baseline_path), str(candidate_path), "--out", str(out_path)],
        cwd=ROOT, capture_output=True, text=True,
    )
    assert result.returncode == 0          # still a reporter, never a gate
    report = json.loads(out_path.read_text())
    assert report["band"] == "blocked"
    assert report["label"] is None
    assert report["corrupt_axes"] == ["judge_mean"]
    assert "BLOCKED" in result.stderr


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


def test_run_exits_cleanly_on_a_missing_artifact_path(tmp_path, capsys):
    missing = tmp_path / "does_not_exist.json"
    other = tmp_path / "candidate.json"
    other.write_text(json.dumps(_artifact(0.6, 0.55, 0.65)))
    rc = run([str(missing), str(other)])
    assert rc == 2
    captured = capsys.readouterr()
    assert "Traceback" not in captured.err
    assert "artifact not found" in captured.err
    assert "does_not_exist.json" in captured.err


def test_run_exits_cleanly_when_a_path_is_a_directory(tmp_path, capsys):
    # A directory path raises IsADirectoryError (POSIX) or PermissionError (Windows) from
    # open() -- both are OSError subclasses that must be caught, not just FileNotFoundError,
    # and each gets its own actionable message (hence the platform-dependent wording here).
    other = tmp_path / "candidate.json"
    other.write_text(json.dumps(_artifact(0.6, 0.55, 0.65)))
    rc = run([str(tmp_path), str(other)])
    assert rc == 2
    captured = capsys.readouterr()
    assert "Traceback" not in captured.err
    assert "directory" in captured.err or "not readable" in captured.err
    assert str(tmp_path) in captured.err


def test_run_exits_cleanly_when_the_artifact_is_unreadable(tmp_path, capsys):
    unreadable = tmp_path / "unreadable.json"
    unreadable.write_text(json.dumps(_artifact(0.6, 0.55, 0.65)))
    other = tmp_path / "candidate.json"
    other.write_text(json.dumps(_artifact(0.6, 0.55, 0.65)))
    os.chmod(unreadable, 0o000)
    try:
        if os.access(unreadable, os.R_OK):
            pytest.skip("root or this OS ignores file permission bits")
        rc = run([str(unreadable), str(other)])
        assert rc == 2
        captured = capsys.readouterr()
        assert "Traceback" not in captured.err
        assert "not readable" in captured.err
    finally:
        os.chmod(unreadable, 0o644)


def test_run_exits_cleanly_on_invalid_json(tmp_path, capsys):
    bad = tmp_path / "bad.json"
    bad.write_text("{not valid json")
    other = tmp_path / "candidate.json"
    other.write_text(json.dumps(_artifact(0.6, 0.55, 0.65)))
    rc = run([str(bad), str(other)])
    assert rc == 2
    captured = capsys.readouterr()
    assert "Traceback" not in captured.err
    assert "not valid JSON" in captured.err


def test_run_exits_cleanly_on_a_non_object_json_artifact(tmp_path, capsys):
    # Valid JSON, wrong shape (a list, not an object) -- must degrade cleanly too, not just
    # OSError/JSONDecodeError cases.
    not_an_object = tmp_path / "list.json"
    not_an_object.write_text(json.dumps([1, 2, 3]))
    other = tmp_path / "candidate.json"
    other.write_text(json.dumps(_artifact(0.6, 0.55, 0.65)))
    rc = run([str(not_an_object), str(other)])
    assert rc == 2
    captured = capsys.readouterr()
    assert "Traceback" not in captured.err
    assert "must be a JSON object" in captured.err


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


# --- M7: foresight breakdown snapshot (module/kind/release prediction accuracy) -------------

def _fs(**overrides):
    base = {"module_recall_mean": 0.75, "module_recall_n": 4,
            "kind_recall_mean": 0.5, "kind_recall_n": 4,
            "release_accuracy": None, "release_accuracy_n": 0}
    base.update(overrides)
    return base


def test_foresight_of_reads_top_level_for_single_repo_artifact():
    artifact = {"composite_mean": 0.6, "foresight": _fs()}
    assert _foresight_of(artifact) == _fs()


def test_foresight_of_reads_tuned_partition_for_generalization_artifact():
    # A --generalization artifact has no top-level foresight; the current, un-diffed accuracy
    # lives under `tuned` (mirrors benchmark/leaderboard.py's _components() partition read).
    artifact = {
        "tuned": {"composite_mean": 0.7, "foresight": _fs(module_recall_mean=0.9)},
        "held_out": {"composite_mean": 0.6, "foresight": _fs(module_recall_mean=0.4)},
    }
    assert _foresight_of(artifact) == _fs(module_recall_mean=0.9)


def test_foresight_of_none_when_absent_or_malformed():
    for bad in ({"composite_mean": 0.6}, {"foresight": "nope"}, {"foresight": None},
                {}, None, "x", 42, []):
        assert _foresight_of(bad) is None, bad


def test_score_pr_delta_snapshots_the_candidates_foresight_not_a_diff():
    # foresight is the CANDIDATE's current accuracy -- an absolute snapshot, not a delta between
    # baseline and candidate, so the published figure reflects "where does accuracy stand now."
    baseline = {"composite_mean": 0.5, "composite_parts": {"judge_mean": 0.5, "objective_mean": 0.5},
                "foresight": _fs(module_recall_mean=0.2)}
    candidate = {"composite_mean": 0.6, "composite_parts": {"judge_mean": 0.6, "objective_mean": 0.6},
                 "foresight": _fs(module_recall_mean=0.9)}
    report = score_pr_delta(baseline, candidate)
    assert report["foresight"] == _fs(module_recall_mean=0.9)


def test_score_pr_delta_foresight_none_for_a_pre_m7_or_offline_artifact():
    baseline = {"composite_mean": 0.5, "composite_parts": {"judge_mean": 0.5, "objective_mean": 0.5}}
    candidate = {"composite_mean": 0.6, "composite_parts": {"judge_mean": 0.6, "objective_mean": 0.6}}
    report = score_pr_delta(baseline, candidate)
    assert report["foresight"] is None
