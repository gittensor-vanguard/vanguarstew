"""Tests for reference baselines (issue #12). Run:

    VANGUARSTEW_OFFLINE=1 python -m pytest -q
"""

import os
import shutil
import subprocess
import sys
import tempfile

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

os.environ["VANGUARSTEW_OFFLINE"] = "1"

from benchmark.baselines import (  # noqa: E402
    BASELINES,
    _infer_kind,
    empty_solve,
    get_baseline,
    heuristic_philosophy,
    heuristic_solve,
)
from benchmark.runner import run_replay  # noqa: E402

CTX = {
    "frozen_at": {"commit": "abc0123456"},
    "recent_commits": [
        {"subject": "Fix crash in parser"},
        {"subject": "Add streaming API"},
        {"subject": "Refactor client internals"},
        {"subject": "Docs: document the config format"},
        {"subject": "Bump version to 1.2.0; update changelog"},
    ],
    "open_issues": [
        {"title": "Memory leak under load"},
        {"title": "Support YAML config"},
    ],
}


def test_registry_selection_and_unknown():
    assert get_baseline("empty") is empty_solve
    assert get_baseline("heuristic") is heuristic_solve
    assert set(BASELINES) >= {"empty", "heuristic"}
    with pytest.raises(ValueError):
        get_baseline("does-not-exist")


def test_empty_baseline_proposes_nothing():
    out = empty_solve(context=CTX, n=5)
    assert out["plan"] == []
    assert out["philosophy"] == {}


def test_heuristic_baseline_derives_a_real_plan():
    out = heuristic_solve(context=CTX, n=5)
    plan = out["plan"]
    assert 0 < len(plan) <= 5
    for item in plan:
        assert {"title", "kind", "rationale", "theme"} <= set(item)
    # open issues are addressed...
    assert any("Memory leak" in item["title"] for item in plan)
    # ...and the philosophy reflects the repo's own signals
    phil = out["philosophy"]
    assert phil["summary"] and phil["values"] and phil["evidence"]
    # the release cadence in history is anticipated
    assert any(item["kind"] == "release" for item in plan) or len(plan) == 5


def test_heuristic_is_stronger_than_empty_offline():
    # Given the same context, the heuristic proposes more than the empty floor.
    assert len(heuristic_solve(context=CTX, n=5)["plan"]) > len(empty_solve(context=CTX)["plan"])


def test_release_subject_at_start_is_release():
    """A version-leading subject is classified as a release by both baseline and scoring."""
    assert _infer_kind("v1.2.0") == "release"
    assert _infer_kind("Release v2.0.0") == "release"
    assert _infer_kind("v1.0.0-beta.1") == "release"


def test_dependency_bump_is_not_a_release():
    """An in-sentence version mention (dependency bump) must not classify as a release."""
    assert _infer_kind("bump lodash to v4.17.21") != "release"
    assert _infer_kind("Bump dependency to v10.0") != "release"
    assert _infer_kind("fix crash in v1.2.0 parser") != "release"


def test_explicit_release_wording_is_release():
    """Explicit release wording in the subject body counts as a release."""
    assert _infer_kind("Release v1.2.0") == "release"
    assert _infer_kind("update changelog for v2.0") == "release"
    assert _infer_kind("bump version to 1.3.0") == "release"


def test_infer_kind_recognizes_test_ci_commits_as_test_not_triage():
    # "test"/"coverage"/"ci" commits must not silently collapse to the unrelated
    # issue-backlog-flavored "triage" kind.
    assert _infer_kind("ci: pin runner os version") == "test"
    assert _infer_kind("increase test coverage for the parser") == "test"


def test_heuristic_philosophy_does_not_mislabel_test_ci_history_as_triage():
    ctx = {
        "recent_commits": [
            {"subject": "ci: pin windows runner version"},
            {"subject": "increase test coverage for the parser"},
        ],
        "open_issues": [],
    }
    phil = heuristic_philosophy(ctx)
    assert "dominated by test work" in phil["summary"]
    assert "dominated by triage work" not in phil["summary"]


@pytest.mark.skipif(shutil.which("git") is None, reason="git required")
def test_replay_selects_baseline_and_tallies():
    d = tempfile.mkdtemp()
    try:
        subprocess.run(["git", "init", "-q", d], check=True)
        subprocess.run(["git", "-C", d, "config", "user.email", "t@t"], check=True)
        subprocess.run(["git", "-C", d, "config", "user.name", "t"], check=True)
        for i in range(20):
            with open(os.path.join(d, f"f{i}.py"), "w", encoding="utf-8") as f:
                f.write(f"x = {i}\n")
            subprocess.run(["git", "-C", d, "add", "-A"], check=True)
            subprocess.run(["git", "-C", d, "commit", "-q", "-m", f"add feature {i}"], check=True)
        res = run_replay(d, agent_file=os.path.join(ROOT, "agent.py"),
                         n_tasks=2, horizon=3, baseline="heuristic")
        assert res["baseline"] == "heuristic"
        tally = res["tally"]
        # every task is decided; the counts are consistent with the number of tasks
        assert tally["challenger"] + tally["baseline"] + tally["tie"] == res["tasks"]
        assert res["tasks"] >= 1
    finally:
        shutil.rmtree(d, ignore_errors=True)
