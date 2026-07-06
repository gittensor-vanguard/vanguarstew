"""Tests for replay artifact Markdown reporting."""

import copy
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from benchmark.report import render_report  # noqa: E402
from scripts.report import load_artifact  # noqa: E402


def _single_repo():
    return {
        "tasks": 3,
        "baseline": "empty",
        "composite_mean": 0.65,
        "composite_parts": {"judge_mean": 0.7, "objective_mean": 0.55},
        "weights": {"judge": 0.6, "objective": 0.4},
        "judge_report": {
            "wins": 2,
            "losses": 1,
            "ties": 0,
            "disagreement_rate": 0.25,
        },
    }


def _multi_repo():
    return {
        "repos": 2,
        "scored_repos": 2,
        "skipped": 0,
        "composite_mean": 0.6,
        "composite_parts": {"judge_mean": 0.65, "objective_mean": 0.5},
        "judge_report": {
            "wins": 3,
            "losses": 2,
            "ties": 1,
            "disagreement_rate": 0.2,
        },
        "per_repo": [
            {"repo_path": "/a", "composite_mean": 0.55, "tasks": 2},
            {"repo_path": "/b", "composite_mean": 0.65, "tasks": 3},
        ],
    }


def _generalization():
    return {
        "repo_set": "benchmark/repo_sets/curated.json",
        "generalization_gap": 0.05,
        "tuned": {
            "scored_repos": 1,
            "composite_mean": 0.7,
            "composite_parts": {"judge_mean": 0.8, "objective_mean": 0.55},
            "judge_report": {"wins": 2, "losses": 0, "ties": 0, "disagreement_rate": 0.0},
            "per_repo": [{"repo_name": "tuned-a", "composite_mean": 0.7, "tasks": 2}],
        },
        "held_out": {
            "scored_repos": 1,
            "composite_mean": 0.65,
            "composite_parts": {"judge_mean": 0.7, "objective_mean": 0.5},
            "judge_report": {"wins": 1, "losses": 1, "ties": 0, "disagreement_rate": 0.5},
            "per_repo": [{"repo_name": "held-b", "composite_mean": 0.65, "tasks": 2}],
        },
    }


def test_render_single_repo_includes_headline_and_judge():
    md = render_report(_single_repo())
    assert "# Benchmark report (single-repo)" in md
    assert "Composite mean: 0.650" in md
    assert "Judge mean: 0.700" in md
    assert "Objective mean: 0.550" in md
    assert "Judge W-L-T: 2-1-0" in md
    assert "Order disagreement rate: 25.0%" in md
    assert "Tasks: 3" in md


def test_render_multi_repo_includes_per_repo_table():
    md = render_report(_multi_repo())
    assert "# Benchmark report (multi-repo)" in md
    assert "### Per-repo" in md
    assert "| /a | 0.550 | 2 |" in md
    assert "| /b | 0.650 | 3 |" in md
    assert "Repos: 2/2 scored" in md


def test_render_generalization_includes_gap_and_partitions():
    md = render_report(_generalization())
    assert "# Benchmark report (generalization)" in md
    assert "Generalization gap (tuned − held-out): 0.050" in md
    assert "Verdict: pass" in md
    assert "### Tuned" in md
    assert "### Held-out" in md
    assert "| tuned-a | 0.700 | 2 |" in md
    assert "| held-b | 0.650 | 2 |" in md


def test_render_treats_unscored_partition_composite_as_unavailable():
    # A tuned partition that scored 0 repos (empty/unusable repo set for that run) carries a
    # placeholder composite_mean: 0.0 from run_multi_replay's own _mean([]) fallback -- that must
    # render as n/a, not a fabricated perfect zero, while a genuinely-scored partition alongside
    # it (held-out) still shows its real score.
    art = _generalization()
    art["tuned"] = {
        "repos": 2,
        "scored_repos": 0,
        "skipped": 2,
        "composite_mean": 0.0,
        "composite_parts": {"judge_mean": 0.0, "objective_mean": 0.0},
        "per_repo": [
            {"repo_name": "tuned-a", "error": "no usable tasks", "tasks": 0},
            {"repo_name": "tuned-b", "error": "no usable tasks", "tasks": 0},
        ],
    }
    md = render_report(art)
    tuned_section = md.split("### Held-out")[0]
    assert "Composite mean: n/a" in tuned_section
    assert "Judge mean: n/a" in tuned_section
    assert "Objective mean: n/a" in tuned_section
    assert "Scored repos: 0, 2 skipped" in tuned_section
    # the held-out partition, which did score, is unaffected
    assert "Composite mean: 0.650" in md.split("### Held-out")[1]


def test_generalization_inspect_verdict_when_gap_exceeds_threshold():
    art = _generalization()
    art["generalization_gap"] = 0.15
    md = render_report(art)
    assert "Verdict: inspect" in md


def test_render_error_shape():
    md = render_report({"error": "no usable tasks", "tasks": 0})
    assert "# Benchmark report (error)" in md
    assert "no usable tasks" in md
    assert "Tasks: 0" in md


def test_render_unknown_for_non_dict():
    md = render_report("not a dict")
    assert "# Benchmark report (unknown)" in md


def test_render_tolerates_missing_optional_fields():
    md = render_report({"composite_mean": 0.5})
    assert "Composite mean: 0.500" in md
    assert "Judge mean: n/a" in md
    assert "Judge W-L-T: n/a" in md


def test_render_tolerates_malformed_per_repo_rows():
    art = _multi_repo()
    art["per_repo"] = [{"repo_path": "/ok", "composite_mean": 0.4, "tasks": 1}, "bad"]
    md = render_report(art)
    assert "| /ok | 0.400 | 1 |" in md
    assert "| n/a | n/a | n/a |" in md


def test_render_does_not_mutate_artifact():
    art = _generalization()
    snapshot = copy.deepcopy(art)
    render_report(art)
    assert art == snapshot


def test_load_artifact_round_trip(tmp_path):
    path = tmp_path / "result.json"
    payload = _single_repo()
    path.write_text(json.dumps(payload), encoding="utf-8")
    assert load_artifact(str(path)) == payload
