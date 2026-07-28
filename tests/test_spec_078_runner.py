"""Spec 078 contract tests for benchmark/runner.py (replay orchestrator).

Pins the as-built behavior described in specs/078-benchmark-runner/spec.md with literal expected
keys, messages, and merge/gating outcomes -- including the as-built gaps (the dead `cleanup` flag,
`weight_sweep`'s asymmetric skip, the zero-sum blend fallback, `run_generalization_report`'s catch
narrowed to RepoSetError). Runs offline against in-memory fakes and tiny throwaway git repos; no
network access and no real repo is ever cloned. Realistic end-to-end coverage of run_replay /
run_multi_replay over real git history stays in tests/test_runner.py.
"""

import json
import logging
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
    _JUDGE_COMPONENT,
    CLONE_TIMEOUT_SECONDS,
    WEIGHT_SWEEP_GRID,
    _materialize_repo_source,
    _submission,
    load_solve,
    run_multi_replay,
    run_replay,
    weight_sweep,
)
from benchmark.score import composite_score  # noqa: E402


def _tiny_repo(dirpath, n=16, prefix="feat"):
    subprocess.run(["git", "init", "-q", dirpath], check=True)
    subprocess.run(["git", "-C", dirpath, "config", "user.email", "t@t"], check=True)
    subprocess.run(["git", "-C", dirpath, "config", "user.name", "t"], check=True)
    subprocess.run(["git", "-C", dirpath, "config", "core.fsync", "none"], check=True)
    for i in range(n):
        with open(os.path.join(dirpath, f"{prefix}{i}.py"), "w", encoding="utf-8") as f:
            f.write(f"x = {i}\n")
        subprocess.run(["git", "-C", dirpath, "add", "-A"], check=True)
        subprocess.run(["git", "-C", dirpath, "commit", "-q", "-m", f"{prefix} {i}"], check=True)
    return dirpath


def _write_repo_set(tmp_path, entries, name="t"):
    config = {"name": name, "description": "d", "strategy": "s", "repos": entries}
    path = tmp_path / "repos.json"
    path.write_text(json.dumps(config))
    return str(path)


def _replay_ok(composite_mean=0.5):
    return {
        "tasks": 1,
        "tally": {"challenger": 1, "baseline": 0, "tie": 0},
        "composite_mean": composite_mean,
        "composite_parts": {"judge_mean": 1.0, "objective_mean": 0.0},
        "foresight": {},
        "rows": [],
    }


GIT_REQUIRED = pytest.mark.skipif(shutil.which("git") is None, reason="git required")


# --- Constants -----------------------------------------------------------------------------------

def test_clone_timeout_seconds_pinned():
    assert CLONE_TIMEOUT_SECONDS == 300


def test_judge_component_map_pinned():
    assert _JUDGE_COMPONENT == {"challenger": 1.0, "tie": 0.5, "baseline": 0.0}


def test_weight_sweep_grid_pinned():
    assert WEIGHT_SWEEP_GRID == ((0.2, 0.8), (0.4, 0.6), (0.5, 0.5), (0.6, 0.4), (0.8, 0.2))


# --- Agent entrypoint loading (load_solve) --------------------------------------------------------

def test_load_solve_missing_file_message(tmp_path):
    with pytest.raises(RuntimeError, match="does not exist or is not a regular file"):
        load_solve(str(tmp_path / "nope.py"))


def test_load_solve_directory_shares_missing_file_message(tmp_path):
    # os.path.isfile(directory) is False too, so a directory hits the same check/message as a
    # missing file -- there is no separate "is a directory" branch.
    with pytest.raises(RuntimeError, match="does not exist or is not a regular file"):
        load_solve(str(tmp_path))


def test_load_solve_exec_error_wraps_original(tmp_path):
    bad = tmp_path / "agent.py"
    bad.write_text("raise ValueError('boom')\n")
    with pytest.raises(RuntimeError) as exc_info:
        load_solve(str(bad))
    assert "boom" in str(exc_info.value)
    assert isinstance(exc_info.value.__cause__, ValueError)


def test_load_solve_missing_entrypoint_message(tmp_path):
    f = tmp_path / "agent.py"
    f.write_text("x = 1\n")
    with pytest.raises(RuntimeError, match="does not define a callable 'solve' entrypoint"):
        load_solve(str(f))


def test_load_solve_non_callable_solve_message(tmp_path):
    f = tmp_path / "agent.py"
    f.write_text("solve = 'not-callable'\n")
    with pytest.raises(RuntimeError, match="does not define a callable 'solve' entrypoint"):
        load_solve(str(f))


def test_load_solve_inserts_agent_dir_into_sys_path_once(tmp_path):
    d = tmp_path / "pkg"
    d.mkdir()
    f = d / "agent.py"
    f.write_text("def solve(**kwargs):\n    return {}\n")
    root_str = str(d.resolve())
    assert root_str not in sys.path
    try:
        load_solve(str(f))
        assert sys.path.count(root_str) == 1
        load_solve(str(f))
        assert sys.path.count(root_str) == 1  # not inserted a second time
    finally:
        while root_str in sys.path:
            sys.path.remove(root_str)


# --- Judged-submission projection (_submission) ---------------------------------------------------

def test_submission_projects_exactly_three_keys():
    out = {
        "philosophy": {"a": 1}, "plan": [1, 2], "rationale": "x",
        "action": "plan", "version_bump": "minor",
    }
    result = _submission(out)
    assert result == {"philosophy": {"a": 1}, "plan": [1, 2], "rationale": "x"}


def test_submission_non_dict_returns_none_triple():
    for bad in (None, [], "x", 5):
        assert _submission(bad) == {"philosophy": None, "plan": None, "rationale": None}


# --- Repo-source materialization (_materialize_repo_source) ---------------------------------------

def test_materialize_placeholder_raises_regardless_of_checkout_root(tmp_path):
    with pytest.raises(RepoSetError, match="placeholder"):
        _materialize_repo_source("https://github.com/OWNER/repo", None)
    with pytest.raises(RepoSetError, match="placeholder"):
        _materialize_repo_source("https://github.com/OWNER/repo", str(tmp_path))


def test_materialize_local_dir_returns_false_and_ignores_checkout_root(tmp_path):
    d = tmp_path / "localrepo"
    d.mkdir()
    assert _materialize_repo_source(str(d), None) == (str(d), False)

    root = tmp_path / "checkout"
    root.mkdir()
    assert _materialize_repo_source(str(d), str(root)) == (str(d), False)
    assert os.listdir(root) == []  # a local source is never cloned into checkout_root


def test_materialize_missing_root_raises(tmp_path):
    missing_source = str(tmp_path / "does-not-exist")
    with pytest.raises(RepoSetError, match="not found locally"):
        _materialize_repo_source(missing_source, None)


def test_materialize_clone_success_returns_true(tmp_path, monkeypatch):
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        os.makedirs(cmd[-1], exist_ok=True)
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr("benchmark.runner.subprocess.run", fake_run)
    root = tmp_path / "checkout"
    root.mkdir()
    dest, cleanup = _materialize_repo_source("not-a-real-local-source", str(root))
    assert cleanup is True
    assert dest == os.path.join(str(root), "repo_0")
    assert calls[0][:4] == ["git", "clone", "-q", "--"]


def test_materialize_clone_timeout_raises_repo_set_error(tmp_path, monkeypatch):
    def fake_run(cmd, **kwargs):
        raise subprocess.TimeoutExpired(cmd, kwargs.get("timeout"))

    monkeypatch.setattr("benchmark.runner.subprocess.run", fake_run)
    root = tmp_path / "checkout"
    root.mkdir()
    with pytest.raises(RepoSetError, match=f"timed out cloning.*{CLONE_TIMEOUT_SECONDS}s"):
        _materialize_repo_source("some-source", str(root))


def test_materialize_clone_failure_raises_with_stderr(tmp_path, monkeypatch):
    def fake_run(cmd, **kwargs):
        raise subprocess.CalledProcessError(128, cmd, stderr="fatal: repo not found\n")

    monkeypatch.setattr("benchmark.runner.subprocess.run", fake_run)
    root = tmp_path / "checkout"
    root.mkdir()
    with pytest.raises(RepoSetError, match="fatal: repo not found"):
        _materialize_repo_source("some-source", str(root))


def test_materialize_cleanup_flag_is_never_read_back(tmp_path, monkeypatch):
    """Pins the as-built dead-flag gap: `cleanup` is computed and carried on
    `selected[i]["cleanup"]`, but nothing acts on it per-clone -- only the whole `checkout_root`
    is ever removed, once, regardless of any individual entry's cleanup value."""
    import benchmark.runner as runner

    def fake_clone(cmd, **kwargs):
        os.makedirs(cmd[-1], exist_ok=True)
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr(runner.subprocess, "run", fake_clone)
    path = _write_repo_set(
        tmp_path, [{"name": "cloned", "source": "https://example.invalid/cloned.git",
                     "tier": "recent"}])

    rmtree_calls = []
    real_rmtree = shutil.rmtree

    def spy_rmtree(p, *a, **kw):
        rmtree_calls.append(p)
        return real_rmtree(p, *a, **kw)

    monkeypatch.setattr(runner.shutil, "rmtree", spy_rmtree)

    def fake_run_replay(repo_path, **kwargs):
        assert os.path.isdir(repo_path)  # the cloned dest is still present mid-loop
        return _replay_ok()

    monkeypatch.setattr(runner, "run_replay", fake_run_replay)

    result = runner.run_multi_replay(repo_set=path)

    assert "cleanup" not in result["per_repo"][0]
    assert len(rmtree_calls) == 1
    assert "vanguarstew_repo_set_" in rmtree_calls[0]


# --- Single-repo replay artifact (run_replay) ------------------------------------------------------

def test_run_replay_solve_fn_type_error():
    with pytest.raises(TypeError, match="solve_fn must be callable"):
        run_replay("/irrelevant", solve_fn="not-callable")


@GIT_REQUIRED
def test_run_replay_solve_fn_overrides_agent_file(tmp_path, monkeypatch):
    import benchmark.runner as runner

    def unsafe_load(*a, **kw):
        raise AssertionError("load_solve must not be called when solve_fn is supplied")

    monkeypatch.setattr(runner, "load_solve", unsafe_load)
    d = _tiny_repo(str(tmp_path / "repo"), n=16)
    calls = []

    def stub(**kwargs):
        calls.append(kwargs)
        return {"philosophy": {}, "plan": [], "rationale": ""}

    res = runner.run_replay(d, agent_file="/nonexistent/agent.py", solve_fn=stub,
                             n_tasks=1, horizon=5, min_history=10)
    assert calls
    assert res["tasks"] == 1


@GIT_REQUIRED
def test_run_replay_empty_tasks_shortcut_shape(tmp_path):
    d = _tiny_repo(str(tmp_path / "repo"), n=3)  # far too small for min_history=10
    res = run_replay(d, solve_fn=lambda **k: {}, n_tasks=1, horizon=5, min_history=10)
    assert res == {"error": "no usable tasks (repo too small for horizon/min_history)", "tasks": 0}


@GIT_REQUIRED
def test_run_replay_non_dict_challenger_degrades_to_empty(tmp_path):
    d = _tiny_repo(str(tmp_path / "repo"), n=16)
    res = run_replay(d, solve_fn=lambda **k: None, n_tasks=1, horizon=5, min_history=10)
    assert res["tasks"] == 1
    assert res["rows"][0]["overlap"] == 0.0


@GIT_REQUIRED
def test_run_replay_row_keys_and_winner_decode(tmp_path):
    d = _tiny_repo(str(tmp_path / "repo"), n=16)
    res = run_replay(d, solve_fn=lambda **k: {"philosophy": {}, "plan": [], "rationale": ""},
                      n_tasks=1, horizon=5, min_history=10)
    row = res["rows"][0]
    assert set(row) == {"task", "freeze", "winner", "judge_order", "overlap", "objective",
                        "composite"}
    assert len(row["freeze"]) == 10
    assert row["winner"] in {"challenger", "baseline", "tie"}


@GIT_REQUIRED
def test_run_replay_full_key_set(tmp_path):
    d = _tiny_repo(str(tmp_path / "repo"), n=16)
    res = run_replay(d, solve_fn=lambda **k: {"philosophy": {}, "plan": [], "rationale": ""},
                      n_tasks=1, horizon=5, min_history=10)
    assert set(res) == {
        "tasks", "baseline", "tally", "decisive_margin", "composite_mean", "composite_parts",
        "foresight", "weights", "rows", "judge_order_stats", "judge_report", "offline",
        "github_enriched", "judge_dual_order",
    }


@GIT_REQUIRED
def test_run_replay_decisive_margin_excludes_ties(tmp_path):
    d = _tiny_repo(str(tmp_path / "repo"), n=16)
    res = run_replay(d, solve_fn=lambda **k: {"philosophy": {}, "plan": [], "rationale": ""},
                      n_tasks=1, horizon=5, min_history=10)
    assert res["decisive_margin"] == res["tally"]["challenger"] - res["tally"]["baseline"]


@GIT_REQUIRED
def test_run_replay_work_dir_supplied_is_not_removed(tmp_path):
    d = _tiny_repo(str(tmp_path / "repo"), n=16)
    work = tmp_path / "work"
    work.mkdir()
    run_replay(d, solve_fn=lambda **k: {"philosophy": {}, "plan": [], "rationale": ""},
               n_tasks=1, horizon=5, min_history=10, work_dir=str(work))
    assert os.path.isdir(work)
    assert os.listdir(str(work))  # task_0 was written into the caller-owned dir


# --- Weight sweep (weight_sweep) -------------------------------------------------------------------

def test_weight_sweep_scored_set_requires_dict_and_known_winner():
    rows = [{"winner": "challenger", "objective": {}}, {"winner": "bogus", "objective": {}},
            "not-a-dict", None]
    sweep = weight_sweep(rows, grid=((0.6, 0.4),))
    assert len(sweep) == 1
    assert sweep[0]["composite_mean"] == round(_JUDGE_COMPONENT["challenger"] * 0.6, 3)


def test_weight_sweep_non_dict_row_warns_and_skips(caplog):
    caplog.set_level(logging.WARNING)
    rows = ["not-a-dict", {"winner": "tie", "objective": {}}]
    weight_sweep(rows, grid=((0.6, 0.4),))
    assert any("non-dict row" in r.message for r in caplog.records)


def test_weight_sweep_bad_winner_dict_row_skips_silently(caplog):
    caplog.set_level(logging.WARNING)
    good = {"winner": "challenger", "objective": {"module_recall": 0.5}}
    bad_dict_row = {"winner": "bogus", "objective": {"module_recall": 0.9}}
    grid = ((0.6, 0.4),)
    with_bad = weight_sweep([good, bad_dict_row], grid=grid)
    without_bad = weight_sweep([good], grid=grid)
    assert with_bad == without_bad  # the bad-winner row contributes nothing to the sweep
    assert not caplog.records  # ...and, unlike a non-dict row, no warning marks it


def test_weight_sweep_zero_sum_weights_do_not_raise():
    rows = [{"winner": "challenger", "objective": {}}]
    sweep = weight_sweep(rows, grid=((0.0, 0.0),))
    assert sweep == [{"w_judge": 0.0, "w_objective": 0.0, "composite_mean": 0.0}]


def test_weight_sweep_empty_scored_set_all_zero():
    sweep = weight_sweep([], grid=WEIGHT_SWEEP_GRID)
    assert [(e["w_judge"], e["w_objective"]) for e in sweep] == list(WEIGHT_SWEEP_GRID)
    assert all(e["composite_mean"] == 0.0 for e in sweep)


def test_weight_sweep_matches_composite_score_at_run_weights():
    rows = [
        {"winner": "challenger", "objective": {"module_recall": 0.8}},
        {"winner": "baseline", "objective": {"module_recall": 0.2}},
        {"winner": "tie", "objective": {}},
    ]
    sweep = weight_sweep(rows, grid=((0.6, 0.4),))
    expected = [
        composite_score("A", {"module_recall": 0.8}, 0.6, 0.4),
        composite_score("B", {"module_recall": 0.2}, 0.6, 0.4),
        composite_score("tie", {}, 0.6, 0.4),
    ]
    assert sweep[0]["composite_mean"] == round(sum(expected) / len(expected), 3)


# --- Multi-repo aggregation (run_multi_replay) ------------------------------------------------------

def test_run_multi_replay_requires_exactly_one_of_repos_or_repo_set():
    with pytest.raises(ValueError, match="pass exactly one"):
        run_multi_replay()
    with pytest.raises(ValueError, match="pass exactly one"):
        run_multi_replay(repos=["a"], repo_set="b")


def test_run_multi_replay_per_repo_merge_precedence(monkeypatch):
    import benchmark.runner as runner
    monkeypatch.setattr(runner, "run_replay", lambda repo_path, **kw: _replay_ok(0.7))
    result = runner.run_multi_replay(repos=["/repo/a"])
    entry = result["per_repo"][0]
    assert entry["repo"] == "/repo/a"  # meta's key survives (res never defines "repo")
    assert entry["composite_mean"] == 0.7  # from res, not meta


def test_run_multi_replay_runtime_error_isolated_as_zero_task_repo(monkeypatch, caplog):
    import benchmark.runner as runner
    caplog.set_level(logging.WARNING)

    def fake_run_replay(repo_path, **kw):
        if repo_path == "/bad":
            raise RuntimeError("freeze failed")
        return _replay_ok()

    monkeypatch.setattr(runner, "run_replay", fake_run_replay)
    result = runner.run_multi_replay(repos=["/bad", "/good"])
    bad_entry = result["per_repo"][0]
    assert bad_entry["error"] == "freeze failed"
    assert bad_entry["tasks"] == 0
    assert result["scored_repos"] == 1
    assert result["skipped"] == 1
    assert any("freeze failed" in r.message for r in caplog.records)


def test_run_multi_replay_other_exception_types_propagate(monkeypatch):
    import benchmark.runner as runner
    monkeypatch.setattr(
        runner, "run_replay",
        lambda repo_path, **kw: (_ for _ in ()).throw(ValueError("not a runtime error")))
    with pytest.raises(ValueError, match="not a runtime error"):
        runner.run_multi_replay(repos=["/repo"])


def test_run_multi_replay_tasks_gate_excludes_from_mean_and_scored_repos(monkeypatch):
    import benchmark.runner as runner
    responses = {
        "/scored": _replay_ok(0.9),
        "/short": {"tasks": 0, "error": "no usable tasks (repo too small for horizon/min_history)"},
    }
    monkeypatch.setattr(runner, "run_replay", lambda repo_path, **kw: responses[repo_path])
    result = runner.run_multi_replay(repos=["/scored", "/short"])
    assert result["scored_repos"] == 1
    assert result["skipped"] == 1
    assert result["composite_mean"] == 0.9


def test_run_multi_replay_tally_sums_across_all_repos_regardless_of_scoring(monkeypatch):
    import benchmark.runner as runner
    responses = {
        "/a": {**_replay_ok(0.5), "tally": {"challenger": 2, "baseline": 1, "tie": 0}},
        "/b": {"tasks": 0, "tally": {"challenger": 0, "baseline": 0, "tie": 3}},
    }
    monkeypatch.setattr(runner, "run_replay", lambda repo_path, **kw: responses[repo_path])
    result = runner.run_multi_replay(repos=["/a", "/b"])
    assert result["judge_report"]["wins"] == 2
    assert result["judge_report"]["losses"] == 1
    assert result["judge_report"]["ties"] == 3
    assert result["scored_repos"] == 1  # only /a counted toward the composite mean


def test_run_multi_replay_unscored_batch_reports_zero_placeholders(monkeypatch):
    import benchmark.runner as runner
    monkeypatch.setattr(runner, "run_replay",
                        lambda repo_path, **kw: {"tasks": 0, "error": "too small"})
    result = runner.run_multi_replay(repos=["/a", "/b"])
    assert result["scored_repos"] == 0
    assert result["skipped"] == 2
    assert result["composite_mean"] == 0.0
    assert result["composite_parts"] == {"judge_mean": 0.0, "objective_mean": 0.0}


def test_run_multi_replay_partition_selection_precedence(tmp_path, monkeypatch):
    import benchmark.runner as runner
    tuned_dir = tmp_path / "tuned_repo"
    tuned_dir.mkdir()
    held_dir = tmp_path / "held_repo"
    held_dir.mkdir()
    path = _write_repo_set(tmp_path, [
        {"name": "tuned1", "source": str(tuned_dir), "tier": "recent", "held_out": False},
        {"name": "held1", "source": str(held_dir), "tier": "recent", "held_out": True},
    ])
    seen = []
    monkeypatch.setattr(runner, "run_replay",
                        lambda repo_path, **kw: (seen.append(repo_path), _replay_ok())[1])

    runner.run_multi_replay(repo_set=path, held_out=True, repo_set_partition="tuned")
    assert seen == [str(tuned_dir)]  # repo_set_partition wins over held_out
    seen.clear()

    runner.run_multi_replay(repo_set=path, held_out=True)
    assert seen == [str(held_dir)]  # held_out selects the held_out partition
    seen.clear()

    result = runner.run_multi_replay(repo_set=path)
    assert seen == [str(tuned_dir)]  # default is "tuned"
    assert result["repo_set"]["selection"] == "tuned"


def test_run_multi_replay_empty_selection_raises_before_checkout_root(tmp_path, monkeypatch):
    import benchmark.runner as runner
    held_dir = tmp_path / "held_repo"
    held_dir.mkdir()
    path = _write_repo_set(
        tmp_path, [{"name": "held1", "source": str(held_dir), "tier": "recent",
                    "held_out": True}])  # no tuned entries

    mkdtemp_calls = []
    real_mkdtemp = tempfile.mkdtemp

    def spy_mkdtemp(*a, **kw):
        p = real_mkdtemp(*a, **kw)
        mkdtemp_calls.append(p)
        return p

    monkeypatch.setattr(runner.tempfile, "mkdtemp", spy_mkdtemp)
    with pytest.raises(RepoSetError, match="no tuned repos"):
        runner.run_multi_replay(repo_set=path)  # default partition is "tuned"; none exist
    assert not mkdtemp_calls


def test_run_multi_replay_materialization_failure_cleans_checkout_root(tmp_path, monkeypatch):
    import benchmark.runner as runner
    path = _write_repo_set(
        tmp_path,
        [{"name": "missing", "source": str(tmp_path / "does-not-exist"), "tier": "recent"}])

    rmtree_calls = []
    real_rmtree = shutil.rmtree

    def spy_rmtree(p, *a, **kw):
        rmtree_calls.append(p)
        return real_rmtree(p, *a, **kw)

    monkeypatch.setattr(runner.shutil, "rmtree", spy_rmtree)
    # checkout_root is always set on the repo_set path, so a missing source hits the real `git
    # clone` attempt (and its CalledProcessError branch), not _materialize_repo_source's
    # checkout_root-is-None guard.
    with pytest.raises(RepoSetError, match="failed to clone"):
        runner.run_multi_replay(repo_set=path)
    assert len(rmtree_calls) == 1


def test_run_multi_replay_repo_set_meta_present_only_for_repo_set_path(tmp_path, monkeypatch):
    import benchmark.runner as runner
    monkeypatch.setattr(runner, "run_replay", lambda repo_path, **kw: _replay_ok())

    result_repos = runner.run_multi_replay(repos=["/a"])
    assert "repo_set" not in result_repos

    d = tmp_path / "r"
    d.mkdir()
    path = _write_repo_set(tmp_path, [{"name": "a", "source": str(d), "tier": "recent"}])
    result_set = runner.run_multi_replay(repo_set=path)
    assert result_set["repo_set"] == {"path": path, "name": "t", "selection": "tuned"}


def test_run_multi_replay_checkout_root_removed_after_loop(tmp_path, monkeypatch):
    import benchmark.runner as runner
    d = tmp_path / "r"
    d.mkdir()
    path = _write_repo_set(tmp_path, [{"name": "a", "source": str(d), "tier": "recent"}])

    created_roots = []
    real_mkdtemp = tempfile.mkdtemp

    def spy_mkdtemp(*a, **kw):
        p = real_mkdtemp(*a, **kw)
        created_roots.append(p)
        return p

    monkeypatch.setattr(runner.tempfile, "mkdtemp", spy_mkdtemp)
    monkeypatch.setattr(runner, "run_replay", lambda repo_path, **kw: _replay_ok())
    runner.run_multi_replay(repo_set=path)
    assert created_roots and not os.path.isdir(created_roots[0])


# --- Generalization report (run_generalization_report) ---------------------------------------------

def test_run_generalization_report_catches_only_repo_set_error(monkeypatch):
    import benchmark.runner as runner

    def fake_multi(repo_set, repo_set_partition=None, **kw):
        if repo_set_partition == "tuned":
            raise RepoSetError("no tuned repos")
        return {"scored_repos": 2, "composite_mean": 0.7}

    monkeypatch.setattr(runner, "run_multi_replay", fake_multi)
    result = runner.run_generalization_report("some-repo-set.json")
    assert result["tuned"] == {"error": "no tuned repos", "scored_repos": 0, "composite_mean": 0.0}
    assert result["held_out"] == {"scored_repos": 2, "composite_mean": 0.7}
    assert result["generalization_gap"] is None  # tuned side never scored


def test_run_generalization_report_other_exceptions_propagate(monkeypatch):
    import benchmark.runner as runner
    monkeypatch.setattr(
        runner, "run_multi_replay",
        lambda repo_set, repo_set_partition=None, **kw: (_ for _ in ()).throw(
            RuntimeError("boom")))
    with pytest.raises(RuntimeError, match="boom"):
        runner.run_generalization_report("some-repo-set.json")


def test_run_generalization_report_gap_requires_both_sides_scored(monkeypatch):
    import benchmark.runner as runner

    def one_sided(repo_set, repo_set_partition=None, **kw):
        if repo_set_partition == "tuned":
            return {"scored_repos": 3, "composite_mean": 0.8}
        return {"scored_repos": 0, "composite_mean": 0.0}

    monkeypatch.setattr(runner, "run_multi_replay", one_sided)
    assert runner.run_generalization_report("x.json")["generalization_gap"] is None

    def both_sided(repo_set, repo_set_partition=None, **kw):
        return {"scored_repos": 2,
                "composite_mean": 0.8 if repo_set_partition == "tuned" else 0.5}

    monkeypatch.setattr(runner, "run_multi_replay", both_sided)
    result = runner.run_generalization_report("x.json")
    assert result["generalization_gap"] == 0.3


def test_run_generalization_report_result_key_set(monkeypatch):
    import benchmark.runner as runner
    monkeypatch.setattr(
        runner, "run_multi_replay",
        lambda repo_set, repo_set_partition=None, **kw: {"scored_repos": 1,
                                                          "composite_mean": 0.5})
    result = runner.run_generalization_report("x.json")
    assert set(result) == {"repo_set", "tuned", "held_out", "generalization_gap"}
