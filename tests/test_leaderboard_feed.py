"""Tests for scripts/leaderboard_feed.py -- the public-safe extraction for the gh-pages
leaderboard feed. The core invariant under test: the private target NEVER leaks per-repo
data or repo identities, only its composite delta.
"""

import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from scripts.leaderboard_feed import (  # noqa: E402
    append_entry,
    to_anchor_entry,
    to_leaderboard_entry,
)
from scripts.score_pr_delta import combine_dual_target, score_pr_delta  # noqa: E402


def _artifact(composite_mean, judge_mean, objective_mean):
    return {
        "composite_mean": composite_mean,
        "composite_parts": {"judge_mean": judge_mean, "objective_mean": objective_mean},
    }


def _real_combined_report():
    """A real combine_dual_target() output, built from score_pr_delta() -- not a hand-rolled
    fake shape -- so this test exercises the actual field structure the bot will pass in."""
    public_baseline = _artifact(0.60, 0.55, 0.65)
    public_candidate = _artifact(0.65, 0.60, 0.70)
    public_candidate["per_repo"] = None  # score_pr_delta doesn't itself add per_repo; compare_eval does
    public_report = score_pr_delta(public_baseline, public_candidate)
    # Graft a realistic per_repo breakdown onto the diff, matching what compare_eval_artifacts
    # actually produces for a multi-repo run (see scripts/compare_eval.py).
    public_report["diff"]["per_repo"] = [
        {"repo": "https://github.com/pypa/hatch", "composite_mean": {"baseline": 0.6, "candidate": 0.7, "delta": 0.1}},
        {"repo": "https://github.com/pytest-dev/pluggy", "composite_mean": {"baseline": 0.6, "candidate": 0.6, "delta": 0.0}},
    ]
    private_baseline = _artifact(0.60, 0.55, 0.65)
    private_candidate = _artifact(0.62, 0.57, 0.67)
    private_report = score_pr_delta(private_baseline, private_candidate)
    private_report["diff"]["per_repo"] = [
        {"repo": "https://github.com/some/hidden-repo", "composite_mean": {"baseline": 0.6, "candidate": 0.62, "delta": 0.02}},
    ]
    return combine_dual_target(public_report, private_report)


def test_to_leaderboard_entry_never_leaks_private_per_repo_data():
    combined = _real_combined_report()
    entry = to_leaderboard_entry(combined, pr_number=1400, timestamp="2026-07-10T00:00:00+00:00")
    assert "per_repo" not in entry["private"]
    assert "diff" not in entry["private"]
    assert set(entry["private"]) == {"composite_delta"}
    assert "hidden-repo" not in json.dumps(entry)


def test_to_leaderboard_entry_keeps_public_per_repo_breakdown():
    combined = _real_combined_report()
    entry = to_leaderboard_entry(combined, pr_number=1400, timestamp="2026-07-10T00:00:00+00:00")
    assert entry["public"]["per_repo"] == [
        {"repo": "https://github.com/pypa/hatch", "composite_delta": 0.1},
        {"repo": "https://github.com/pytest-dev/pluggy", "composite_delta": 0.0},
    ]


def test_to_leaderboard_entry_shape_and_values():
    combined = _real_combined_report()
    entry = to_leaderboard_entry(combined, pr_number=1400, timestamp="2026-07-10T00:00:00+00:00")
    assert entry["timestamp"] == "2026-07-10T00:00:00+00:00"
    assert entry["pr_number"] == 1400
    assert entry["band"] == combined["band"]
    assert entry["label"] == combined["label"]
    assert entry["public"]["composite_delta"] == combined["public"]["composite_deltas"]["composite_mean"]
    assert entry["private"]["composite_delta"] == combined["private"]["composite_deltas"]["composite_mean"]


def test_to_leaderboard_entry_defaults_timestamp_to_now():
    combined = _real_combined_report()
    entry = to_leaderboard_entry(combined, pr_number=1)
    assert isinstance(entry["timestamp"], str) and entry["timestamp"]


def test_to_leaderboard_entry_tolerates_missing_public_and_private():
    entry = to_leaderboard_entry({}, pr_number=1, timestamp="t")
    assert entry["public"] == {"composite_delta": None, "per_repo": []}
    assert entry["private"] == {"composite_delta": None}
    assert entry["band"] is None


def test_to_leaderboard_entry_skips_malformed_per_repo_rows():
    combined = {
        "band": "s",
        "label": "perf:s",
        "public": {"composite_deltas": {"composite_mean": 0.02},
                    "diff": {"per_repo": [None, {"repo": 42}, {"repo": ""},
                                          {"repo": "https://github.com/a/b",
                                           "composite_mean": {"delta": 0.03}}]}},
        "private": {"composite_deltas": {"composite_mean": 0.01}},
    }
    entry = to_leaderboard_entry(combined, pr_number=2, timestamp="t")
    assert entry["public"]["per_repo"] == [{"repo": "https://github.com/a/b", "composite_delta": 0.03}]


def _since_anchor_report():
    """A real score_pr_delta()-shaped pair, as if diffing the candidate against a cached,
    FIXED anchor baseline (e.g. v0.5.0) rather than the shifting base-branch one."""
    anchor_baseline = _artifact(0.60, 0.55, 0.65)
    public_since = score_pr_delta(anchor_baseline, _artifact(0.72, 0.68, 0.78))
    public_since["diff"]["per_repo"] = [
        {"repo": "https://github.com/pypa/hatch", "composite_mean": {"delta": 0.12}},
    ]
    private_since = score_pr_delta(anchor_baseline, _artifact(0.64, 0.60, 0.70))
    private_since["diff"]["per_repo"] = [
        {"repo": "https://github.com/some/hidden-repo", "composite_mean": {"delta": 0.04}},
    ]
    return {"anchor": "v0.5.0", "public": public_since, "private": private_since}


def test_since_anchor_is_omitted_when_not_given():
    combined = _real_combined_report()
    entry = to_leaderboard_entry(combined, pr_number=3, timestamp="t")
    assert "since_anchor" not in entry


def test_since_anchor_carries_anchor_name_and_both_deltas():
    combined = _real_combined_report()
    since = _since_anchor_report()
    entry = to_leaderboard_entry(combined, pr_number=3, timestamp="t", since_anchor=since)
    assert entry["since_anchor"]["anchor"] == "v0.5.0"
    assert entry["since_anchor"]["public"] == {
        "composite_delta": 0.12, "composite_score": 0.72, "anchor_score": 0.6,
    }
    assert entry["since_anchor"]["private"] == {
        "composite_delta": 0.04, "composite_score": 0.64, "anchor_score": 0.6,
    }


def test_since_anchor_never_leaks_private_per_repo_data():
    combined = _real_combined_report()
    since = _since_anchor_report()
    entry = to_leaderboard_entry(combined, pr_number=3, timestamp="t", since_anchor=since)
    assert set(entry["since_anchor"]["private"]) == {"composite_delta", "composite_score", "anchor_score"}
    assert "hidden-repo" not in json.dumps(entry)


def test_since_anchor_tolerates_malformed_input():
    combined = _real_combined_report()
    entry = to_leaderboard_entry(combined, pr_number=3, timestamp="t", since_anchor={"anchor": "v0.5.0"})
    assert entry["since_anchor"] == {
        "anchor": "v0.5.0",
        "public": {"composite_delta": None, "composite_score": None, "anchor_score": None},
        "private": {"composite_delta": None, "composite_score": None, "anchor_score": None},
    }
    # a non-dict since_anchor is treated the same as not passing one at all
    entry2 = to_leaderboard_entry(combined, pr_number=3, timestamp="t", since_anchor="not a dict")
    assert "since_anchor" not in entry2


def test_since_anchor_score_is_consistent_with_delta():
    """composite_score - anchor_score should equal composite_delta -- the bar chart on the
    leaderboard page relies on these three numbers being internally consistent."""
    combined = _real_combined_report()
    since = _since_anchor_report()
    entry = to_leaderboard_entry(combined, pr_number=3, timestamp="t", since_anchor=since)
    for side in ("public", "private"):
        fields = entry["since_anchor"][side]
        assert round(fields["composite_score"] - fields["anchor_score"], 4) == fields["composite_delta"]


def test_append_entry_creates_file_when_missing(tmp_path):
    path = str(tmp_path / "results.json")
    result = append_entry(path, {"a": 1})
    assert result == [{"a": 1}]
    assert json.loads(open(path).read()) == [{"a": 1}]


def test_append_entry_appends_to_existing_file(tmp_path):
    path = str(tmp_path / "results.json")
    append_entry(path, {"n": 1})
    result = append_entry(path, {"n": 2})
    assert result == [{"n": 1}, {"n": 2}]


def test_append_entry_caps_history_length(tmp_path):
    path = str(tmp_path / "results.json")
    for i in range(5):
        append_entry(path, {"n": i}, max_entries=3)
    result = json.loads(open(path).read())
    assert result == [{"n": 2}, {"n": 3}, {"n": 4}]


def test_append_entry_raises_on_non_array_file(tmp_path):
    path = tmp_path / "results.json"
    path.write_text('{"not": "a list"}')
    try:
        append_entry(str(path), {"a": 1})
        assert False, "expected ValueError"
    except ValueError:
        pass


def test_to_anchor_entry_reads_composite_mean_directly_off_each_artifact():
    """Anchor artifacts are raw run_eval outputs, not a score_pr_delta diff -- composite_mean
    sits at the top level, not under diff.composite_mean."""
    public_artifact = {"composite_mean": 0.717, "repos": 3, "scored_repos": 3}
    private_artifact = {"composite_mean": 0.644, "repos": 3, "scored_repos": 3}
    entry = to_anchor_entry("v0.5.0", public_artifact, private_artifact, timestamp="2026-07-10T09:00:00+00:00")
    assert entry == {
        "anchor": "v0.5.0",
        "timestamp": "2026-07-10T09:00:00+00:00",
        "public_score": 0.717,
        "private_score": 0.644,
    }


def test_to_anchor_entry_defaults_timestamp_to_now():
    entry = to_anchor_entry("v0.5.0", {"composite_mean": 0.6}, {"composite_mean": 0.6})
    assert isinstance(entry["timestamp"], str) and entry["timestamp"]


def test_to_anchor_entry_tolerates_missing_artifacts():
    entry = to_anchor_entry("v0.5.0", None, None, timestamp="t")
    assert entry == {"anchor": "v0.5.0", "timestamp": "t", "public_score": None, "private_score": None}


def test_to_anchor_entry_never_includes_per_repo_or_repo_names():
    public_artifact = {
        "composite_mean": 0.717,
        "per_repo": [{"repo": "https://github.com/pypa/hatch", "composite_mean": 0.8}],
    }
    private_artifact = {
        "composite_mean": 0.644,
        "per_repo": [{"repo": "https://github.com/some/hidden-repo", "composite_mean": 0.6}],
    }
    entry = to_anchor_entry("v0.5.0", public_artifact, private_artifact, timestamp="t")
    assert set(entry) == {"anchor", "timestamp", "public_score", "private_score"}
    assert "hidden-repo" not in json.dumps(entry)
    assert "hatch" not in json.dumps(entry)
