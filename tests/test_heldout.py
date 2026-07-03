"""Tests for held-out repo evaluation (issue #52, M3). Run:

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

from benchmark.runner import run_heldout_eval, split_heldout  # noqa: E402

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


def test_split_is_deterministic_disjoint_and_covers_all():
    repos = [f"/r/{c}" for c in "edcba"]  # unsorted on purpose
    tuned, held = split_heldout(repos, holdout=2, seed=0)
    assert len(held) == 2 and len(tuned) == 3
    assert set(tuned).isdisjoint(held)
    assert sorted(tuned + held) == sorted(repos)          # partition covers everything
    assert split_heldout(repos, 2, seed=0) == (tuned, held)  # deterministic under a seed
    # a fraction picks round(frac * n) repos, at least one
    _, held_frac = split_heldout(repos, holdout=0.5, seed=0)
    assert len(held_frac) == 2  # round(0.5 * 5) == round(2.5) == 2 (banker's rounding)


def test_split_fraction_and_bounds():
    repos = [f"/r/{i}" for i in range(4)]
    _, held = split_heldout(repos, holdout=0.25, seed=1)
    assert len(held) == 1                     # round(0.25 * 4) == 1
    tuned, held = split_heldout(repos, holdout=99, seed=1)
    assert len(held) == 4 and tuned == []     # clamped to the set size


@pytest.mark.skipif(shutil.which("git") is None, reason="git required")
def test_heldout_eval_reports_heldout_separately_and_is_deterministic():
    a = _tiny_repo(tempfile.mkdtemp(), prefix="alpha")
    b = _tiny_repo(tempfile.mkdtemp(), prefix="beta")
    try:
        kw = dict(agent_file=AGENT, n_tasks=2, horizon=3, seed=0)
        res = run_heldout_eval([a], [b], **kw)

        # held-out composite is reported separately, alongside the tuned one and the gap
        assert res["heldout_composite_mean"] == res["heldout"]["composite_mean"]
        assert res["tuned_composite_mean"] == res["tuned"]["composite_mean"]
        assert res["generalization_gap"] == round(
            res["tuned_composite_mean"] - res["heldout_composite_mean"], 3)
        # per-repo detail is preserved under each group
        assert [r["repo"] for r in res["heldout"]["per_repo"]] == [b]
        assert [r["repo"] for r in res["tuned"]["per_repo"]] == [a]

        assert run_heldout_eval([a], [b], **kw) == res  # deterministic
    finally:
        shutil.rmtree(a, ignore_errors=True)
        shutil.rmtree(b, ignore_errors=True)


@pytest.mark.skipif(shutil.which("git") is None, reason="git required")
def test_heldout_only_when_no_tuned_repos():
    b = _tiny_repo(tempfile.mkdtemp(), prefix="beta")
    try:
        res = run_heldout_eval([], [b], agent_file=AGENT, n_tasks=2, horizon=3, seed=0)
        assert res["tuned"] is None and res["tuned_composite_mean"] is None
        assert res["generalization_gap"] is None            # no gap without a tuned group
        assert res["heldout_composite_mean"] is not None
    finally:
        shutil.rmtree(b, ignore_errors=True)
