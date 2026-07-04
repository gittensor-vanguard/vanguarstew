"""Tests for multi-repo replay + aggregated composite (issue #51). Run:

    VANGUARSTEW_OFFLINE=1 python -m pytest -q
"""

import json
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

from benchmark.repo_set import EXAMPLE_REPO_SET, RepoSetError  # noqa: E402
from benchmark.runner import run_multi_replay, run_replay  # noqa: E402

AGENT = os.path.join(ROOT, "agent.py")


def _tiny_repo(dirpath, n=16, prefix="feat"):
    subprocess.run(["git", "init", "-q", dirpath], check=True)
    subprocess.run(["git", "-C", dirpath, "config", "user.email", "t@t"], check=True)
    subprocess.run(["git", "-C", dirpath, "config", "user.name", "t"], check=True)
    for i in range(n):
        with open(os.path.join(dirpath, f"{prefix}{i}.py"), "w", encoding="utf-8") as f:
            f.write(f"x = {i}\n")
        subprocess.run(["git", "-C", dirpath, "add", "-A"], check=True)
        subprocess.run(["git", "-C", dirpath, "commit", "-q", "-m", f"{prefix} {i}"], check=True)
    return dirpath


@pytest.mark.skipif(shutil.which("git") is None, reason="git required")
def test_single_run_reports_composite_mean_and_parts():
    d = _tiny_repo(tempfile.mkdtemp())
    try:
        res = run_replay(d, agent_file=AGENT, n_tasks=2, horizon=3, seed=0)
        # single-repo composite output contract: composite_mean PLUS its parts and weights
        assert "composite_mean" in res and 0.0 <= res["composite_mean"] <= 1.0
        parts = res["composite_parts"]
        assert {"judge_mean", "objective_mean"} <= set(parts)
        assert all(0.0 <= parts[k] <= 1.0 for k in ("judge_mean", "objective_mean"))
        assert res["weights"] == {"judge": 0.6, "objective": 0.4}
        # each task row carries both the objective anchor and the blended composite
        assert res["rows"] and all("objective" in r and "composite" in r for r in res["rows"])
        assert res["composite_mean"] == round(
            sum(r["composite"] for r in res["rows"]) / len(res["rows"]), 3)
    finally:
        shutil.rmtree(d, ignore_errors=True)


@pytest.mark.skipif(shutil.which("git") is None, reason="git required")
def test_multi_repo_aggregates_and_is_deterministic():
    a = _tiny_repo(tempfile.mkdtemp(), prefix="alpha")
    b = _tiny_repo(tempfile.mkdtemp(), prefix="beta")
    try:
        kw = dict(agent_file=AGENT, n_tasks=2, horizon=3, seed=0)
        res = run_multi_replay([a, b], **kw)

        # per-repo results are preserved, one per input repo, in order
        assert res["repos"] == 2
        assert [r["repo"] for r in res["per_repo"]] == [a, b]
        assert res["scored_repos"] == 2 and res["skipped"] == 0

        # overall composite_mean is exactly the mean of each repo's own composite_mean
        expected = round(sum(r["composite_mean"] for r in res["per_repo"]) / 2, 3)
        assert res["composite_mean"] == expected
        assert 0.0 <= res["composite_mean"] <= 1.0
        # the aggregate also averages the parts across repos
        assert res["composite_parts"] == {
            "judge_mean": round(sum(r["composite_parts"]["judge_mean"]
                                    for r in res["per_repo"]) / 2, 3),
            "objective_mean": round(sum(r["composite_parts"]["objective_mean"]
                                        for r in res["per_repo"]) / 2, 3),
        }

        # deterministic under a fixed seed
        res2 = run_multi_replay([a, b], **kw)
        assert res2["composite_mean"] == res["composite_mean"]
        assert res2["per_repo"] == res["per_repo"]
    finally:
        shutil.rmtree(a, ignore_errors=True)
        shutil.rmtree(b, ignore_errors=True)


@pytest.mark.skipif(shutil.which("git") is None, reason="git required")
def test_multi_repo_skips_zero_task_repo_without_diluting():
    good = _tiny_repo(tempfile.mkdtemp())
    tiny = _tiny_repo(tempfile.mkdtemp(), n=2)  # too small for horizon -> tasks == 0
    try:
        kw = dict(agent_file=AGENT, n_tasks=2, horizon=5, seed=0)
        res = run_multi_replay([good, tiny], **kw)

        # the zero-task repo is skipped (gated on tasks > 0), not counted as scored
        assert res["repos"] == 2
        assert res["scored_repos"] == 1 and res["skipped"] == 1
        tiny_row = next(r for r in res["per_repo"] if r["repo"] == tiny)
        assert tiny_row.get("tasks") == 0 and "error" in tiny_row

        # and it does NOT dilute the aggregate: composite_mean equals the good repo's alone
        good_alone = run_multi_replay([good], **kw)["composite_mean"]
        assert res["composite_mean"] == good_alone
        assert res["composite_parts"] == run_multi_replay([good], **kw)["composite_parts"]
    finally:
        shutil.rmtree(good, ignore_errors=True)
        shutil.rmtree(tiny, ignore_errors=True)


@pytest.mark.skipif(shutil.which("git") is None, reason="git required")
def test_repo_set_replay_uses_validated_tuned_entries_and_freeze_hints(tmp_path):
    tuned = _tiny_repo(tempfile.mkdtemp(), n=20, prefix="tuned")
    held = _tiny_repo(tempfile.mkdtemp(), n=20, prefix="held")
    cfg = tmp_path / "repos.json"
    cfg.write_text(json.dumps({
        "name": "curated",
        "repos": [
            {
                "name": "tuned-a",
                "source": tuned,
                "tier": "recent",
                "freeze_window": {"min_history": 12, "rotation_seed": 9},
            },
            {
                "name": "held-b",
                "source": held,
                "tier": "obscure",
                "held_out": True,
                "freeze_window": {"min_history": 11},
            },
        ],
    }), encoding="utf-8")
    try:
        kw = dict(agent_file=AGENT, n_tasks=2, horizon=3, seed=0)
        expected = run_replay(tuned, min_history=12, rotation_seed=9, **kw)
        res = run_multi_replay(repo_set=str(cfg), **kw)
        assert res["repos"] == 1
        row = res["per_repo"][0]
        assert row["repo"] == tuned
        assert row["repo_name"] == "tuned-a"
        assert row["tier"] == "recent"
        assert row["held_out"] is False
        assert {k: row[k] for k in expected} == expected

        with_held = run_multi_replay(repo_set=str(cfg), include_held_out=True, **kw)
        assert with_held["repos"] == 2
        assert [r["repo_name"] for r in with_held["per_repo"]] == ["tuned-a", "held-b"]
    finally:
        shutil.rmtree(tuned, ignore_errors=True)
        shutil.rmtree(held, ignore_errors=True)


def test_repo_set_replay_rejects_placeholder_sources():
    with pytest.raises(RepoSetError, match="placeholder sources"):
        run_multi_replay(repo_set=EXAMPLE_REPO_SET, agent_file=AGENT, n_tasks=1, horizon=1, seed=0)
