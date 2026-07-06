"""Tests for the Markdown report renderer (deterministic, offline)."""

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from benchmark.report import artifact_kind, render_report  # noqa: E402

_SINGLE = {
    "tasks": 3,
    "baseline": "empty",
    "composite_mean": 0.62,
    "composite_parts": {"judge_mean": 0.67, "objective_mean": 0.55},
    "tally": {"challenger": 2, "baseline": 1, "tie": 0},
    "judge_report": {"wins": 2, "losses": 1, "ties": 0, "disagreement_rate": 0.333},
    "rows": [{"task": 0}],
}

_MULTI = {
    "repos": 2,
    "scored_repos": 2,
    "skipped": 0,
    "composite_mean": 0.5,
    "composite_parts": {"judge_mean": 0.5, "objective_mean": 0.5},
    "judge_report": {"wins": 1, "losses": 1, "ties": 0, "disagreement_rate": 0.0},
    "per_repo": [
        {"repo_name": "alpha", "tasks": 3, "composite_mean": 0.6},
        {"repo": "/local/beta", "tasks": 2, "composite_mean": 0.4},
    ],
}

_GEN = {
    "repo_set": {"name": "curated"},
    "tuned": {"composite_mean": 0.6, "scored_repos": 3, "per_repo": [{"repo_name": "a", "tasks": 2, "composite_mean": 0.6}]},
    "held_out": {"composite_mean": 0.5, "scored_repos": 2, "per_repo": [{"repo_name": "b", "tasks": 2, "composite_mean": 0.5}]},
    "generalization_gap": 0.1,
}


def test_artifact_kind_classifies_each_shape():
    assert artifact_kind(_SINGLE) == "single"
    assert artifact_kind(_MULTI) == "multi"
    assert artifact_kind(_GEN) == "generalization"
    assert artifact_kind({"error": "no usable tasks", "tasks": 0}) == "error"
    assert artifact_kind({"unrelated": 1}) == "unknown"
    assert artifact_kind("not a dict") == "unknown"       # non-dict never crashes
    assert artifact_kind(None) == "unknown"


def test_single_repo_report_has_headline_score_and_judge():
    out = render_report(_SINGLE)
    assert out.startswith("# Replay report - single repo")
    assert "**tasks**: 3" in out
    assert "`empty`" in out
    assert "**composite_mean**: 0.620" in out
    assert "judge component: 0.670" in out
    assert "objective anchor: 0.550" in out
    assert "**judge W-L-T**: 2-1-0" in out
    assert "order-disagreement rate**: 33.3%" in out


def test_multi_repo_report_renders_per_repo_table():
    out = render_report(_MULTI)
    assert out.startswith("# Replay report - multi-repo")
    assert "scored 2, skipped 0" in out
    assert "| repo | tasks | composite_mean |" in out
    assert "| alpha | 3 | 0.600 |" in out
    assert "| /local/beta | 2 | 0.400 |" in out


def test_generalization_report_shows_gap_and_both_partitions():
    out = render_report(_GEN)
    assert out.startswith("# Replay report - generalization")
    assert "**generalization_gap** (tuned - held-out): 0.100" in out
    assert "held-out holds up" in out          # gap <= 0.1
    assert "## tuned" in out and "## held_out" in out
    assert "| a | 2 | 0.600 |" in out
    assert "| b | 2 | 0.500 |" in out


def test_generalization_flags_a_wide_gap():
    wide = dict(_GEN, generalization_gap=0.4)
    assert "held-out degrades - inspect" in render_report(wide)


def test_error_artifact_reports_reason_not_crash():
    out = render_report({"error": "no usable tasks (repo too small)", "tasks": 0})
    assert "produced no scored tasks" in out
    assert "repo too small" in out


def test_missing_and_malformed_fields_render_as_na_not_crash():
    # Every scalar is missing or the wrong type; the report must still render with n/a.
    partial = {
        "composite_mean": "not-a-number",
        "composite_parts": "oops",
        "tally": None,
        "judge_report": ["bad"],
        "rows": [],
    }
    out = render_report(partial)
    assert "**composite_mean**: n/a" in out
    assert "judge W-L-T**: n/a-n/a-n/a" in out
    assert "order-disagreement rate**: n/a" in out


def test_per_repo_table_tolerates_non_dict_entries():
    out = render_report({"per_repo": ["bad", {"repo_name": "ok", "tasks": 1, "composite_mean": 0.9}]})
    assert "| ok | 1 | 0.900 |" in out
    assert "| n/a |" in out                     # the non-dict entry degrades to n/a, no crash


def test_unknown_shape_returns_a_report_string():
    out = render_report(12345)
    assert "unrecognized artifact shape" in out
    assert out.endswith("\n")


def test_report_never_mutates_the_artifact():
    import copy
    original = copy.deepcopy(_GEN)
    render_report(_GEN)
    assert _GEN == original
