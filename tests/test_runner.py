"""Tests for the orchestration layer (runner.py): freeze -> run -> judge -> tally. Run:

    VANGUARSTEW_OFFLINE=1 python -m pytest tests/test_runner.py -q
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
    CLONE_TIMEOUT_SECONDS,
    _materialize_repo_source,
    load_solve,
    run_multi_replay,
    run_replay,
)

AGENT = os.path.join(ROOT, "agent.py")


def _tiny_repo(dirpath, n=16, prefix="feat"):
    subprocess.run(["git", "init", "-q", dirpath], check=True)
    subprocess.run(["git", "-C", dirpath, "config", "user.email", "t@t"], check=True)
    subprocess.run(["git", "-C", dirpath, "config", "user.name", "t"], check=True)
    # Valid values are none|objects|reference|... — "false" is ignored as unknown.
    subprocess.run(["git", "-C", dirpath, "config", "core.fsync", "none"], check=True)
    for i in range(n):
        with open(os.path.join(dirpath, f"{prefix}{i}.py"), "w", encoding="utf-8") as f:
            f.write(f"x = {i}\n")
        subprocess.run(["git", "-C", dirpath, "add", "-A"], check=True)
        subprocess.run(["git", "-C", dirpath, "commit", "-q", "-m", f"{prefix} {i}"], check=True)
    return dirpath


# ---- run_replay (single-repo) output contract ----

SINGLE_REPO_KEYS = {
    "tasks", "baseline", "tally", "decisive_margin", "composite_mean",
    "composite_parts", "weights", "rows", "judge_order_stats", "judge_report",
    "offline", "github_enriched", "judge_dual_order",
}


@pytest.mark.skipif(shutil.which("git") is None, reason="git required")
def test_run_replay_returns_expected_keys():
    d = _tiny_repo(tempfile.mkdtemp())
    try:
        res = run_replay(d, agent_file=AGENT, n_tasks=2, horizon=3, seed=0)
        missing = SINGLE_REPO_KEYS - set(res)
        assert not missing, f"run_replay response missing keys: {missing}"
    finally:
        shutil.rmtree(d, ignore_errors=True)


@pytest.mark.skipif(shutil.which("git") is None, reason="git required")
def test_run_replay_composite_mean_in_range():
    d = _tiny_repo(tempfile.mkdtemp())
    try:
        res = run_replay(d, agent_file=AGENT, n_tasks=2, horizon=3, seed=0)
        assert isinstance(res["composite_mean"], (int, float))
        assert 0.0 <= res["composite_mean"] <= 1.0
    finally:
        shutil.rmtree(d, ignore_errors=True)


@pytest.mark.skipif(shutil.which("git") is None, reason="git required")
def test_run_replay_rows_align_with_tasks():
    d = _tiny_repo(tempfile.mkdtemp())
    try:
        n = 3
        res = run_replay(d, agent_file=AGENT, n_tasks=n, horizon=3, seed=0)
        assert res["tasks"] == n
        assert len(res["rows"]) == n
    finally:
        shutil.rmtree(d, ignore_errors=True)


@pytest.mark.skipif(shutil.which("git") is None, reason="git required")
def test_run_replay_composite_parts_match_rows():
    d = _tiny_repo(tempfile.mkdtemp())
    try:
        res = run_replay(d, agent_file=AGENT, n_tasks=3, horizon=3, seed=0)
        parts = res["composite_parts"]
        assert isinstance(parts["judge_mean"], (int, float))
        assert isinstance(parts["objective_mean"], (int, float))
        assert 0.0 <= parts["judge_mean"] <= 1.0
        assert 0.0 <= parts["objective_mean"] <= 1.0
    finally:
        shutil.rmtree(d, ignore_errors=True)


@pytest.mark.skipif(shutil.which("git") is None, reason="git required")
def test_run_replay_too_small_repo_errors_cleanly():
    d = _tiny_repo(tempfile.mkdtemp(), n=5)
    try:
        res = run_replay(d, agent_file=AGENT, n_tasks=5, horizon=10, min_history=50)
        assert "error" in res
        assert res["tasks"] == 0
    finally:
        shutil.rmtree(d, ignore_errors=True)


# ---- run_multi_replay (multi-repo aggregation) output contract ----


@pytest.mark.skipif(shutil.which("git") is None, reason="git required")
def test_run_multi_replay_produces_valid_composite_mean():
    a = _tiny_repo(tempfile.mkdtemp(), prefix="alpha")
    b = _tiny_repo(tempfile.mkdtemp(), prefix="beta")
    try:
        res = run_multi_replay([a, b], agent_file=AGENT, n_tasks=2, horizon=3, seed=0)
        assert res["scored_repos"] >= 1
        assert isinstance(res["composite_mean"], (int, float))
        assert 0.0 <= res["composite_mean"] <= 1.0
    finally:
        shutil.rmtree(a, ignore_errors=True)
        shutil.rmtree(b, ignore_errors=True)


@pytest.mark.skipif(shutil.which("git") is None, reason="git required")
def test_run_multi_replay_per_repo_preserves_order():
    a = _tiny_repo(tempfile.mkdtemp(), prefix="alpha")
    b = _tiny_repo(tempfile.mkdtemp(), prefix="beta")
    try:
        res = run_multi_replay([a, b], agent_file=AGENT, n_tasks=2, horizon=3, seed=0)
        assert res["repos"] == 2
        assert [r["repo"] for r in res["per_repo"]] == [a, b]
    finally:
        shutil.rmtree(a, ignore_errors=True)
        shutil.rmtree(b, ignore_errors=True)


@pytest.mark.skipif(shutil.which("git") is None, reason="git required")
def test_run_multi_replay_deterministic_given_fixed_seed():
    a = _tiny_repo(tempfile.mkdtemp(), prefix="alpha")
    b = _tiny_repo(tempfile.mkdtemp(), prefix="beta")
    try:
        kw = dict(agent_file=AGENT, n_tasks=2, horizon=3, seed=42)
        r1 = run_multi_replay([a, b], **kw)
        r2 = run_multi_replay([a, b], **kw)
        assert r1["composite_mean"] == r2["composite_mean"]
        assert len(r1["per_repo"]) == len(r2["per_repo"])
    finally:
        shutil.rmtree(a, ignore_errors=True)
        shutil.rmtree(b, ignore_errors=True)


@pytest.mark.skipif(shutil.which("git") is None, reason="git required")
def test_run_multi_replay_disallows_ambiguous_args():
    a = _tiny_repo(tempfile.mkdtemp())
    try:
        with pytest.raises(ValueError, match="pass exactly one"):
            run_multi_replay(repos=[a], repo_set="some")
        with pytest.raises(ValueError, match="pass exactly one"):
            run_multi_replay(repos=None, repo_set=None)
    finally:
        shutil.rmtree(a, ignore_errors=True)


# ---- load_solve error handling ----------------------------------------------

def test_load_solve_rejects_missing_file():
    with pytest.raises(RuntimeError, match="does not exist"):
        load_solve("/tmp/vanguarstew-no-such-agent.py")


def test_load_solve_rejects_directory():
    with pytest.raises(RuntimeError, match="does not exist"):
        load_solve("/tmp")


def test_load_solve_rejects_syntax_error(tmp_path):
    bad = tmp_path / "bad.py"
    bad.write_text("def solve():\n")
    with pytest.raises(RuntimeError, match="cannot load agent"):
        load_solve(str(bad))


def test_load_solve_rejects_missing_solve_entrypoint(tmp_path):
    # An agent file that imports cleanly but defines no `solve` must fail with a clean error,
    # not a raw AttributeError from `module.solve`.
    agent = tmp_path / "nosolve.py"
    agent.write_text("x = 1\n")
    with pytest.raises(RuntimeError, match="does not define a callable 'solve'"):
        load_solve(str(agent))


def test_load_solve_rejects_non_callable_solve(tmp_path):
    # A `solve` bound to a non-callable must be rejected up front, not returned silently and
    # crash later when the harness tries to invoke it.
    agent = tmp_path / "badsolve.py"
    agent.write_text("solve = 42\n")
    with pytest.raises(RuntimeError, match="does not define a callable 'solve'"):
        load_solve(str(agent))


def test_load_solve_loads_valid_agent():
    solve = load_solve(os.path.join(ROOT, 'agent.py'))
    assert callable(solve)


# ---- repo-set clone is bounded and option-safe ------------------------------

def test_clone_timeout_raises_clean_repo_set_error(tmp_path, monkeypatch):
    # A network clone must not hang forever: a TimeoutExpired becomes a clean RepoSetError so the
    # run records a per-repo error instead of stalling the whole replay.
    def fake_run(cmd, **kwargs):
        raise subprocess.TimeoutExpired(cmd, kwargs.get("timeout"))

    monkeypatch.setattr("benchmark.runner.subprocess.run", fake_run)
    with pytest.raises(RepoSetError, match="timed out cloning"):
        _materialize_repo_source("https://example.invalid/repo.git", str(tmp_path))


def test_clone_passes_end_of_options_guard_and_finite_timeout(tmp_path, monkeypatch):
    # The clone must carry a `--` immediately before the source (so a leading-dash source is never
    # parsed as a git flag) and a finite timeout.
    calls = {}

    def fake_run(cmd, **kwargs):
        calls["cmd"] = list(cmd)
        calls["timeout"] = kwargs.get("timeout")
        return None

    monkeypatch.setattr("benchmark.runner.subprocess.run", fake_run)
    source = "https://example.invalid/repo.git"
    _materialize_repo_source(source, str(tmp_path))
    assert calls["cmd"][calls["cmd"].index(source) - 1] == "--"
    assert calls["timeout"] == CLONE_TIMEOUT_SECONDS


def test_run_multi_replay_cleans_up_checkout_root_when_a_source_fails(tmp_path, monkeypatch):
    # A repo-set source that can't be materialized (a clone timeout/failure, the shipped
    # OWNER/... placeholder, or a missing local source) makes run_multi_replay raise from the
    # setup loop -- before the replay try/finally that removes the checkout dir is ever entered.
    # The temp checkout root (and any repos already cloned into it) must still be cleaned up, not
    # leaked. Regression test for the setup-phase temp-dir leak.
    cfg = tmp_path / "repo_set.json"
    cfg.write_text(json.dumps({
        "name": "local", "description": "test", "strategy": "test",
        "repos": [{"name": "r0", "source": "https://example.invalid/repo.git", "tier": "recent"}],
    }), encoding="utf-8")

    created = []
    real_mkdtemp = tempfile.mkdtemp

    def spy_mkdtemp(*args, **kwargs):
        path = real_mkdtemp(*args, **kwargs)
        created.append(path)
        return path

    def fail_clone(cmd, **kwargs):
        raise subprocess.TimeoutExpired(cmd, kwargs.get("timeout"))

    monkeypatch.setattr(tempfile, "mkdtemp", spy_mkdtemp)
    monkeypatch.setattr("benchmark.runner.subprocess.run", fail_clone)

    with pytest.raises(RepoSetError):
        run_multi_replay(repo_set=str(cfg))

    roots = [p for p in created if "vanguarstew_repo_set_" in os.path.basename(p)]
    assert roots, "expected run_multi_replay to create a checkout root"
    assert not os.path.exists(roots[0]), (
        f"checkout root {roots[0]} leaked after a materialization failure")
