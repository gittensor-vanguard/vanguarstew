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

from benchmark.repo_set import RepoSetError  # noqa: E402
from benchmark.runner import (  # noqa: E402
    run_generalization_report,
    run_multi_replay,
    run_replay,
)

AGENT = os.path.join(ROOT, "agent.py")


def _tiny_repo(dirpath, n=16, prefix="feat"):
    subprocess.run(["git", "init", "-q", "-b", "main", dirpath], check=True)
    subprocess.run(["git", "-C", dirpath, "config", "user.email", "t@t"], check=True)
    subprocess.run(["git", "-C", dirpath, "config", "user.name", "t"], check=True)
    # Git 2.43+ fsync defaults can corrupt rapid /tmp commits on CI ("invalid object").
    # Valid values are none|objects|reference|... — "false" is ignored as unknown.
    subprocess.run(["git", "-C", dirpath, "config", "core.fsync", "none"], check=True)
    for i in range(n):
        relpath = f"{prefix}{i}.py"
        with open(os.path.join(dirpath, relpath), "w", encoding="utf-8") as f:
            f.write(f"x = {i}\n")
        subprocess.run(["git", "-C", dirpath, "add", "--", relpath], check=True)
        completed = subprocess.run(
            ["git", "-C", dirpath, "commit", "-q", "-m", f"{prefix} {i}"],
            capture_output=True,
            text=True,
        )
        if completed.returncode != 0:
            raise RuntimeError(
                f"git commit failed in {dirpath!r} at {relpath}: "
                f"{completed.stderr.strip() or completed.stdout.strip()}"
            )
    return dirpath


def _write_repo_set(path, repos):
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"name": "local", "description": "test", "strategy": "test", "repos": repos}, f)


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
        assert res["rows"] and all(
            "objective" in r and "composite" in r and "judge_order" in r for r in res["rows"])
        assert res["composite_mean"] == round(
            sum(r["composite"] for r in res["rows"]) / len(res["rows"]), 3)
        assert res["judge_order_stats"]["offline"] == len(res["rows"])
        assert res["judge_order_stats"]["disagreement_rate"] is None
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
        assert res["judge_order_stats"]["offline"] == sum(
            len(r["rows"]) for r in res["per_repo"])

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


def _non_git_dir():
    """A real directory that is not a git repository."""
    d = tempfile.mkdtemp()
    return d, d


def _missing_path():
    """A path that does not exist on disk."""
    parent = tempfile.mkdtemp()
    return os.path.join(parent, "does_not_exist"), parent


@pytest.mark.skipif(shutil.which("git") is None, reason="git required")
@pytest.mark.parametrize("make_bad", [_non_git_dir, _missing_path],
                         ids=["non_git_dir", "missing_path"])
def test_multi_repo_survives_unusable_repo_without_aborting(make_bad):
    good = _tiny_repo(tempfile.mkdtemp())
    bad, bad_cleanup = make_bad()
    try:
        kw = dict(agent_file=AGENT, n_tasks=2, horizon=5, seed=0)
        res = run_multi_replay([good, bad], **kw)

        # the whole batch completes; one unusable repo does not abort it or drop the good repo
        assert res["repos"] == 2
        assert res["scored_repos"] == 1 and res["skipped"] == 1

        # the unusable repo is recorded like a zero-task repo: an error plus tasks == 0
        bad_row = next(r for r in res["per_repo"] if r["repo"] == bad)
        assert bad_row.get("tasks") == 0 and bad_row.get("error")

        # and it does not dilute the aggregate: the mean equals the good repo's alone
        good_alone = run_multi_replay([good], **kw)
        assert res["composite_mean"] == good_alone["composite_mean"]
        assert res["composite_parts"] == good_alone["composite_parts"]
    finally:
        shutil.rmtree(good, ignore_errors=True)
        shutil.rmtree(bad_cleanup, ignore_errors=True)


@pytest.mark.skipif(shutil.which("git") is None, reason="git required")
def test_multi_repo_aggregates_surviving_repos_when_one_fails():
    good_a = _tiny_repo(tempfile.mkdtemp(), prefix="aa")
    good_b = _tiny_repo(tempfile.mkdtemp(), prefix="bb")
    bad = tempfile.mkdtemp()  # a real directory that is NOT a git repo
    try:
        kw = dict(agent_file=AGENT, n_tasks=2, horizon=5, seed=0)
        res = run_multi_replay([good_a, bad, good_b], **kw)

        # both good repos survive and are aggregated; only the unusable one is skipped
        assert res["repos"] == 3
        assert res["scored_repos"] == 2 and res["skipped"] == 1

        # the aggregate is exactly the mean of the two survivors, matching a clean run of them
        survivors = run_multi_replay([good_a, good_b], **kw)
        assert res["composite_mean"] == survivors["composite_mean"]
        assert res["composite_parts"] == survivors["composite_parts"]
        scored = [r["composite_mean"] for r in res["per_repo"] if r.get("tasks", 0) > 0]
        assert len(scored) == 2
        assert res["composite_mean"] == round(sum(scored) / 2, 3)
    finally:
        for d in (good_a, good_b, bad):
            shutil.rmtree(d, ignore_errors=True)


@pytest.mark.skipif(shutil.which("git") is None, reason="git required")
def test_generalization_report_survives_non_git_repo_set_source():
    # min_history=3 and horizon=3 need len(commits) > 6; n=8 keeps enough history without
    # the 16-commit git loop that flakes on CI under load (see Git 2.43+ /tmp fsync issues).
    tuned_ok = _tiny_repo(tempfile.mkdtemp(), n=8, prefix="tuned")
    tuned_bad = tempfile.mkdtemp()  # materializes as a plain dir, then fails inside run_replay
    held = _tiny_repo(tempfile.mkdtemp(), n=8, prefix="held")
    cfg_dir = tempfile.mkdtemp()
    cfg = os.path.join(cfg_dir, "repos.json")
    _write_repo_set(cfg, [
        {"name": "tuned-ok", "source": tuned_ok, "tier": "recent",
         "freeze_window": {"min_history": 3}},
        {"name": "tuned-bad", "source": tuned_bad, "tier": "recent",
         "freeze_window": {"min_history": 3}},
        {"name": "held-b", "source": held, "tier": "obscure", "held_out": True,
         "freeze_window": {"min_history": 3}},
    ])
    try:
        # _partition guards only RepoSetError, so a non-git source used to crash the whole
        # report; the per-repo guard now records it and the report still completes with a gap
        report = run_generalization_report(cfg, agent_file=AGENT, n_tasks=2, horizon=3, seed=0)

        tuned = report["tuned"]
        assert tuned["repos"] == 2 and tuned["scored_repos"] == 1 and tuned["skipped"] == 1
        bad_row = next(r for r in tuned["per_repo"] if r["repo_name"] == "tuned-bad")
        assert bad_row.get("tasks") == 0 and bad_row.get("error")

        # both partitions still scored a repo, so the generalization gap is reported
        assert report["held_out"]["scored_repos"] == 1
        assert report["generalization_gap"] is not None
    finally:
        for d in (tuned_ok, tuned_bad, held, cfg_dir):
            shutil.rmtree(d, ignore_errors=True)


@pytest.mark.skipif(shutil.which("git") is None, reason="git required")
def test_repo_set_replay_uses_validated_config_and_tuned_slice():
    tuned = _tiny_repo(tempfile.mkdtemp(), prefix="tuned")
    held = _tiny_repo(tempfile.mkdtemp(), prefix="held")
    cfg_dir = tempfile.mkdtemp()
    cfg = os.path.join(cfg_dir, "repos.json")
    _write_repo_set(cfg, [
        {"name": "tuned-a", "source": tuned, "tier": "recent",
         "freeze_window": {"min_history": 3, "rotation_seed": 5}},
        {"name": "held-b", "source": held, "tier": "obscure", "held_out": True,
         "freeze_window": {"min_history": 3}},
    ])
    try:
        res = run_multi_replay(
            repo_set=cfg, agent_file=AGENT, n_tasks=2, horizon=3, seed=0)
        assert res["repo_set"] == {"path": cfg, "name": "local", "selection": "tuned"}
        assert res["repos"] == 1 and res["scored_repos"] == 1
        assert [r["repo_name"] for r in res["per_repo"]] == ["tuned-a"]
        assert res["per_repo"][0]["repo"] == tuned
        assert res["per_repo"][0]["freeze_window"] == {"min_history": 3, "rotation_seed": 5}

        held_res = run_multi_replay(
            repo_set=cfg, repo_set_partition="held_out",
            agent_file=AGENT, n_tasks=2, horizon=3, seed=0)
        assert held_res["repo_set"]["selection"] == "held_out"
        assert [r["repo_name"] for r in held_res["per_repo"]] == ["held-b"]

        all_res = run_multi_replay(
            repo_set=cfg, repo_set_partition="all",
            agent_file=AGENT, n_tasks=2, horizon=3, seed=0)
        assert all_res["repo_set"]["selection"] == "all"
        assert all_res["repos"] == 2
    finally:
        shutil.rmtree(tuned, ignore_errors=True)
        shutil.rmtree(held, ignore_errors=True)
        shutil.rmtree(cfg_dir, ignore_errors=True)


def test_repo_set_replay_rejects_placeholder_sources():
    cfg_dir = tempfile.mkdtemp()
    cfg = os.path.join(cfg_dir, "repos.json")
    _write_repo_set(cfg, [
        {"name": "example", "source": "https://github.com/OWNER/example", "tier": "recent"},
    ])
    try:
        with pytest.raises(RepoSetError, match="placeholder"):
            run_multi_replay(repo_set=cfg, agent_file=AGENT, n_tasks=1, horizon=1, seed=0)
    finally:
        shutil.rmtree(cfg_dir, ignore_errors=True)
