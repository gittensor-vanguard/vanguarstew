"""Tests for the tuned vs held-out generalization report (M3, issue #208). Run:

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

from benchmark.runner import run_generalization_report  # noqa: E402

AGENT = os.path.join(ROOT, "agent.py")


def _tiny_repo(dirpath, n=16, prefix="feat"):
    subprocess.run(["git", "init", "-q", dirpath], check=True)
    subprocess.run(["git", "-C", dirpath, "config", "user.email", "t@t"], check=True)
    subprocess.run(["git", "-C", dirpath, "config", "user.name", "t"], check=True)
    # Git 2.43+ fsync defaults can corrupt rapid /tmp commits on CI ("invalid object").
    # Valid values are none|objects|reference|... — "false" is ignored as unknown.
    subprocess.run(["git", "-C", dirpath, "config", "core.fsync", "none"], check=True)
    for i in range(n):
        with open(os.path.join(dirpath, f"{prefix}{i}.py"), "w", encoding="utf-8") as f:
            f.write(f"x = {i}\n")
        subprocess.run(["git", "-C", dirpath, "add", "-A"], check=True)
        subprocess.run(["git", "-C", dirpath, "commit", "-q", "-m", f"{prefix} {i}"], check=True)
    return dirpath


def _write_repo_set(tmp, repos):
    path = os.path.join(tmp, "set.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"name": "gen-set", "description": "d", "strategy": "s", "repos": repos}, f)
    return path


@pytest.mark.skipif(shutil.which("git") is None, reason="git required")
def test_report_has_both_partitions_and_gap():
    tmp = tempfile.mkdtemp()
    a = _tiny_repo(os.path.join(tmp, "a"), prefix="alpha")
    b = _tiny_repo(os.path.join(tmp, "b"), prefix="beta")
    cfg = _write_repo_set(tmp, [
        {"name": "tuned-a", "source": a, "tier": "recent"},
        {"name": "held-b", "source": b, "tier": "obscure", "held_out": True},
    ])
    try:
        res = run_generalization_report(cfg, agent_file=AGENT, n_tasks=2, horizon=3, seed=0)
        assert res["tuned"]["scored_repos"] == 1
        assert res["held_out"]["scored_repos"] == 1
        for part in ("tuned", "held_out"):
            assert 0.0 <= res[part]["composite_mean"] <= 1.0
        # the gap is exactly tuned minus held-out, computed once both sides scored
        assert res["generalization_gap"] == round(
            res["tuned"]["composite_mean"] - res["held_out"]["composite_mean"], 3)
        # each partition really replayed its own repo, not the other
        assert [r["repo_name"] for r in res["tuned"]["per_repo"]] == ["tuned-a"]
        assert [r["repo_name"] for r in res["held_out"]["per_repo"]] == ["held-b"]
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


@pytest.mark.skipif(shutil.which("git") is None, reason="git required")
def test_gap_is_none_and_partition_records_error_when_empty():
    tmp = tempfile.mkdtemp()
    a = _tiny_repo(os.path.join(tmp, "a"), prefix="alpha")
    # a config with tuned repos only -> the held-out partition has nothing to replay
    cfg = _write_repo_set(tmp, [{"name": "tuned-a", "source": a, "tier": "recent"}])
    try:
        res = run_generalization_report(cfg, agent_file=AGENT, n_tasks=2, horizon=3, seed=0)
        assert res["tuned"]["scored_repos"] == 1
        assert res["held_out"]["scored_repos"] == 0
        assert "error" in res["held_out"] and "held_out" in res["held_out"]["error"]
        # a gap is never reported from a single side
        assert res["generalization_gap"] is None
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


@pytest.mark.skipif(shutil.which("git") is None, reason="git required")
def test_report_is_deterministic():
    tmp = tempfile.mkdtemp()
    a = _tiny_repo(os.path.join(tmp, "a"), prefix="alpha")
    b = _tiny_repo(os.path.join(tmp, "b"), prefix="beta")
    cfg = _write_repo_set(tmp, [
        {"name": "tuned-a", "source": a, "tier": "recent"},
        {"name": "held-b", "source": b, "tier": "obscure", "held_out": True},
    ])
    try:
        kw = dict(agent_file=AGENT, n_tasks=2, horizon=3, seed=0)
        r1 = run_generalization_report(cfg, **kw)
        r2 = run_generalization_report(cfg, **kw)
        assert r1["generalization_gap"] == r2["generalization_gap"]
        assert r1["tuned"]["composite_mean"] == r2["tuned"]["composite_mean"]
        assert r1["held_out"]["composite_mean"] == r2["held_out"]["composite_mean"]
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
