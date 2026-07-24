"""Spec 083 contract tests for benchmark/runner.py (the replay orchestrator).

Pins the as-built behavior described in specs/083-benchmark-runner/spec.md with literal expected
values. `run_replay` is replaced with an in-memory fake wherever the aggregation contract is under
test and `subprocess.run` is monkeypatched for materialization, so no test clones a repo or touches
the network. Broader behavioral coverage lives in tests/test_runner.py and tests/test_multi_repo.py.
"""

import logging
import os
import subprocess
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import benchmark.runner as runner  # noqa: E402
from benchmark.repo_set import PLACEHOLDER_SOURCE_PREFIX, RepoSetError  # noqa: E402

LOGGER = "benchmark.runner"


def _warnings(caplog):
    return [r.message for r in caplog.records if r.name == LOGGER]


def _row(winner, objective=None):
    return {"winner": winner, "objective": objective if objective is not None else {}}


def _scored(composite=0.6, judge=1.0, objective=0.0, tasks=2, tally=None):
    return {
        "tasks": tasks,
        "composite_mean": composite,
        "composite_parts": {"judge_mean": judge, "objective_mean": objective},
        "foresight": {},
        "rows": [{"judge_order": None}],
        "tally": tally if tally is not None else {"challenger": 1, "baseline": 0, "tie": 0},
    }


# --- Constants -----------------------------------------------------------------------------------

def test_constants_are_pinned():
    assert runner._JUDGE_COMPONENT == {"challenger": 1.0, "tie": 0.5, "baseline": 0.0}
    assert runner.CLONE_TIMEOUT_SECONDS == 300
    assert runner.WEIGHT_SWEEP_GRID == ((0.2, 0.8), (0.4, 0.6), (0.5, 0.5),
                                        (0.6, 0.4), (0.8, 0.2))


# --- Agent entrypoint ----------------------------------------------------------------------------

def test_load_solve_rejects_a_missing_file(tmp_path):
    missing = str(tmp_path / "nope.py")
    with pytest.raises(RuntimeError) as exc:
        runner.load_solve(missing)
    assert "does not exist or is not a regular file" in str(exc.value)
    # A directory is not a regular file either.
    with pytest.raises(RuntimeError):
        runner.load_solve(str(tmp_path))


def test_load_solve_rejects_a_module_that_fails_to_execute(tmp_path):
    bad = tmp_path / "agent_boom.py"
    bad.write_text("raise ValueError('boom')\n", encoding="utf-8")
    with pytest.raises(RuntimeError) as exc:
        runner.load_solve(str(bad))
    assert "cannot load agent file" in str(exc.value)
    assert "boom" in str(exc.value)
    assert isinstance(exc.value.__cause__, ValueError)      # chained, not swallowed


def test_load_solve_rejects_a_module_without_a_callable_solve(tmp_path):
    no_solve = tmp_path / "agent_no_solve.py"
    no_solve.write_text("VALUE = 1\n", encoding="utf-8")
    with pytest.raises(RuntimeError) as exc:
        runner.load_solve(str(no_solve))
    assert "does not define a callable 'solve' entrypoint" in str(exc.value)

    not_callable = tmp_path / "agent_solve_str.py"
    not_callable.write_text("solve = 'not callable'\n", encoding="utf-8")
    with pytest.raises(RuntimeError):
        runner.load_solve(str(not_callable))


def test_load_solve_returns_the_entrypoint_and_extends_sys_path(tmp_path, monkeypatch):
    agent = tmp_path / "agent_ok.py"
    agent.write_text("def solve(**kwargs):\n    return {'plan': []}\n", encoding="utf-8")

    monkeypatch.setattr(sys, "path", list(sys.path))         # isolate the mutation
    solve = runner.load_solve(str(agent))
    assert callable(solve)
    assert solve() == {"plan": []}
    assert str(tmp_path) in sys.path                          # the documented side effect


# --- Judged submission ---------------------------------------------------------------------------

def test_submission_projects_only_the_judged_view():
    assert runner._submission({"philosophy": {"summary": "s"}, "plan": [1], "rationale": "r",
                               "version_bump": "minor", "patch": "diff"}) == {
        "philosophy": {"summary": "s"}, "plan": [1], "rationale": "r"}
    # Missing keys become None rather than being absent.
    assert runner._submission({}) == {"philosophy": None, "plan": None, "rationale": None}


@pytest.mark.parametrize("value", [None, "not-a-dict", 5, [], True])
def test_submission_degrades_a_non_dict_result(value):
    assert runner._submission(value) == {"philosophy": None, "plan": None, "rationale": None}


# --- Repo-source materialization -----------------------------------------------------------------

def test_materialize_rejects_a_placeholder_source(tmp_path, monkeypatch):
    monkeypatch.setattr(subprocess, "run",
                        lambda *a, **k: pytest.fail("must not clone a placeholder"))
    with pytest.raises(RepoSetError) as exc:
        runner._materialize_repo_source(f"{PLACEHOLDER_SOURCE_PREFIX}repo", str(tmp_path))
    assert "placeholder" in str(exc.value)


def test_materialize_uses_a_local_directory_in_place(tmp_path):
    local = tmp_path / "a_repo"
    local.mkdir()
    assert runner._materialize_repo_source(str(local), None) == (str(local), False)


def test_materialize_without_a_checkout_root_fails_closed():
    with pytest.raises(RepoSetError) as exc:
        runner._materialize_repo_source("https://example.invalid/o/r", None)
    assert "not found locally" in str(exc.value)


def test_materialize_clones_with_a_bounded_timeout_and_option_terminator(tmp_path, monkeypatch):
    seen = {}

    def fake_run(cmd, **kwargs):
        seen["cmd"] = cmd
        seen["timeout"] = kwargs.get("timeout")
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(subprocess, "run", fake_run)
    path, cleanup = runner._materialize_repo_source("https://example.invalid/o/r", str(tmp_path))

    assert path == os.path.join(str(tmp_path), "repo_0")
    assert cleanup is True
    assert seen["timeout"] == runner.CLONE_TIMEOUT_SECONDS
    # `--` ends option parsing so a source beginning with `-` is never read as a git flag.
    assert seen["cmd"][:4] == ["git", "clone", "-q", "--"]


def test_materialize_maps_a_clone_timeout_and_failure_to_repo_set_error(tmp_path, monkeypatch):
    def timing_out(cmd, **kwargs):
        raise subprocess.TimeoutExpired(cmd, runner.CLONE_TIMEOUT_SECONDS)

    monkeypatch.setattr(subprocess, "run", timing_out)
    with pytest.raises(RepoSetError) as exc:
        runner._materialize_repo_source("https://example.invalid/o/r", str(tmp_path))
    assert f"after {runner.CLONE_TIMEOUT_SECONDS}s" in str(exc.value)

    def failing(cmd, **kwargs):
        raise subprocess.CalledProcessError(128, cmd, "", "  fatal: repository not found  ")

    monkeypatch.setattr(subprocess, "run", failing)
    with pytest.raises(RepoSetError) as exc:
        runner._materialize_repo_source("https://example.invalid/o/r", str(tmp_path))
    assert "fatal: repository not found" in str(exc.value)     # stderr is stripped and carried


def test_materialize_cleanup_flag_is_advisory_only(tmp_path, monkeypatch):
    # The flag is returned and stored, but no code path acts on it -- it is only ever *excluded*
    # from the per-repo metadata. Cleanup happens solely by removing the checkout root.
    local = tmp_path / "a_repo"
    local.mkdir()
    monkeypatch.setattr(runner, "run_replay", lambda repo_path, **kw: _scored())
    result = runner.run_multi_replay(repos=[str(local)])
    assert "cleanup" not in result["per_repo"][0]
    assert "repo_path" not in result["per_repo"][0]


# --- Single-repo replay --------------------------------------------------------------------------

def test_run_replay_zero_task_shape_is_pinned(tmp_path, monkeypatch):
    agent = tmp_path / "agent_ok.py"
    agent.write_text("def solve(**kwargs):\n    return {}\n", encoding="utf-8")
    monkeypatch.setattr(runner, "generate_tasks", lambda *a, **k: [])

    assert runner.run_replay(str(tmp_path), agent_file=str(agent), api_key="offline") == {
        "error": "no usable tasks (repo too small for horizon/min_history)", "tasks": 0}


# --- Weight sweep --------------------------------------------------------------------------------

def test_weight_sweep_reproduces_the_runs_own_composite_mean():
    # A challenger win with a zero objective blends to the judge weight itself; sweeping at the
    # production 0.6/0.4 pair must reproduce what run_replay reported.
    rows = [_row("challenger"), _row("baseline")]
    assert runner.weight_sweep(rows, grid=((0.6, 0.4),)) == [
        {"w_judge": 0.6, "w_objective": 0.4, "composite_mean": 0.3}]
    assert runner.weight_sweep([_row("tie")], grid=((0.5, 0.5),)) == [
        {"w_judge": 0.5, "w_objective": 0.5, "composite_mean": 0.25}]


def test_weight_sweep_preserves_grid_order():
    sweep = runner.weight_sweep([_row("challenger")])
    assert [(s["w_judge"], s["w_objective"]) for s in sweep] == list(runner.WEIGHT_SWEEP_GRID)
    assert [s["composite_mean"] for s in sweep] == [0.2, 0.4, 0.5, 0.6, 0.8]


def test_weight_sweep_warns_on_a_non_list_rows(caplog):
    with caplog.at_level(logging.WARNING, logger=LOGGER):
        sweep = runner.weight_sweep(42, grid=((0.6, 0.4),))
    assert sweep == [{"w_judge": 0.6, "w_objective": 0.4, "composite_mean": 0.0}]
    assert any("weight_sweep rows is int, not a list" in m for m in _warnings(caplog))


def test_weight_sweep_warns_on_a_non_dict_row(caplog):
    with caplog.at_level(logging.WARNING, logger=LOGGER):
        sweep = runner.weight_sweep(["junk", _row("challenger")], grid=((0.6, 0.4),))
    assert sweep == [{"w_judge": 0.6, "w_objective": 0.4, "composite_mean": 0.6}]
    assert any("skipping a non-dict row" in m for m in _warnings(caplog))


def test_weight_sweep_skips_an_unrecognized_winner_silently(caplog):
    # Asymmetric on purpose: a non-dict row warns (above), an unusable `winner` does not.
    with caplog.at_level(logging.WARNING, logger=LOGGER):
        sweep = runner.weight_sweep([_row("bogus"), {"objective": {}}, None,
                                     _row("challenger")], grid=((0.6, 0.4),))
    assert sweep == [{"w_judge": 0.6, "w_objective": 0.4, "composite_mean": 0.6}]
    assert _warnings(caplog) == []


@pytest.mark.parametrize("objective", [None, {}, 0, "", []])
def test_weight_sweep_reads_a_falsy_objective_as_empty(objective):
    assert runner.weight_sweep([{"winner": "challenger", "objective": objective}],
                               grid=((1.0, 0.0),)) == [
        {"w_judge": 1.0, "w_objective": 0.0, "composite_mean": 1.0}]


def test_weight_sweep_with_nothing_scored_is_zero():
    for rows in ([], [_row("bogus")]):
        assert runner.weight_sweep(rows) == [
            {"w_judge": j, "w_objective": o, "composite_mean": 0.0}
            for j, o in runner.WEIGHT_SWEEP_GRID]


def test_weight_sweep_zero_sum_blend_does_not_raise():
    # `(w_judge + w_objective) or 1.0`: a degenerate grid entry reports 0.0, never ZeroDivisionError.
    assert runner.weight_sweep([_row("challenger")], grid=((0.0, 0.0),)) == [
        {"w_judge": 0.0, "w_objective": 0.0, "composite_mean": 0.0}]


# --- Multi-repo aggregation ----------------------------------------------------------------------

def test_multi_replay_requires_exactly_one_source():
    for kwargs in ({}, {"repos": ["a"], "repo_set": "s.json"}):
        with pytest.raises(ValueError) as exc:
            runner.run_multi_replay(**kwargs)
        assert "pass exactly one of 'repos' or 'repo_set'" in str(exc.value)


def test_multi_replay_aggregates_only_scored_repos(monkeypatch):
    def fake(repo_path, **kw):
        return _scored(composite=0.6) if repo_path == "ok" else {"tasks": 0}

    monkeypatch.setattr(runner, "run_replay", fake)
    result = runner.run_multi_replay(repos=["ok", "short"])
    # A zero-task repo is kept in per_repo and counted in `skipped`, never in the mean.
    assert (result["repos"], result["scored_repos"], result["skipped"]) == (2, 1, 1)
    assert result["composite_mean"] == 0.6
    assert len(result["per_repo"]) == 2


def test_multi_replay_records_a_runtime_error_like_a_zero_task_repo(monkeypatch, caplog):
    def fake(repo_path, **kw):
        if repo_path == "bad":
            raise RuntimeError("not a git repo")
        return _scored()

    monkeypatch.setattr(runner, "run_replay", fake)
    with caplog.at_level(logging.WARNING, logger=LOGGER):
        result = runner.run_multi_replay(repos=["ok", "bad"])
    assert result["per_repo"][1]["error"] == "not a git repo"
    assert result["per_repo"][1]["tasks"] == 0
    assert result["scored_repos"] == 1 and result["skipped"] == 1
    assert any("replay failed for bad" in m for m in _warnings(caplog))


def test_multi_replay_result_shape_is_pinned(monkeypatch):
    monkeypatch.setattr(runner, "run_replay", lambda repo_path, **kw: _scored())
    result = runner.run_multi_replay(repos=["ok"])
    assert sorted(result) == ["composite_mean", "composite_parts", "foresight",
                              "judge_order_stats", "judge_report", "per_repo", "repos",
                              "scored_repos", "skipped"]
    assert sorted(result["composite_parts"]) == ["judge_mean", "objective_mean"]
    assert "repo_set" not in result                 # only present for a repo-set run


def test_multi_replay_unscored_aggregate_is_a_zero_placeholder(monkeypatch):
    # THE placeholder every downstream gate must mask: nothing scored, yet composite_mean is a
    # perfect-looking 0.0 rather than None.
    monkeypatch.setattr(runner, "run_replay", lambda repo_path, **kw: {"tasks": 0})
    result = runner.run_multi_replay(repos=["short", "also-short"])
    assert result["scored_repos"] == 0
    assert result["composite_mean"] == 0.0
    assert result["composite_parts"] == {"judge_mean": 0.0, "objective_mean": 0.0}
    assert result["skipped"] == 2


def test_multi_replay_replay_result_wins_a_key_collision(monkeypatch):
    monkeypatch.setattr(runner, "run_replay",
                        lambda repo_path, **kw: dict(_scored(), repo="from-the-replay"))
    result = runner.run_multi_replay(repos=["from-the-selection"])
    assert result["per_repo"][0]["repo"] == "from-the-replay"


def test_multi_replay_tally_accumulates_over_every_repo(monkeypatch):
    def fake(repo_path, **kw):
        if repo_path == "zero":
            return {"tasks": 0, "tally": {"challenger": 5, "baseline": 0, "tie": 0}}
        return _scored(tally={"challenger": 1, "baseline": 2, "tie": 0})

    monkeypatch.setattr(runner, "run_replay", fake)
    report = runner.run_multi_replay(repos=["ok", "zero"])["judge_report"]
    # The tally is accumulated before the tasks > 0 gate, so a zero-task repo's tally still counts.
    assert (report["wins"], report["losses"], report["ties"]) == (6, 2, 0)


# --- Generalization report -----------------------------------------------------------------------

def test_generalization_report_shape_and_gap(monkeypatch):
    def fake(repo_set=None, repo_set_partition=None, **kw):
        mean = 0.7 if repo_set_partition == "tuned" else 0.4
        return {"scored_repos": 2, "composite_mean": mean}

    monkeypatch.setattr(runner, "run_multi_replay", fake)
    report = runner.run_generalization_report("set.json")
    assert sorted(report) == ["generalization_gap", "held_out", "repo_set", "tuned"]
    assert report["repo_set"] == "set.json"
    assert report["generalization_gap"] == 0.3


def test_generalization_report_gap_is_none_from_a_single_side(monkeypatch):
    def fake(repo_set=None, repo_set_partition=None, **kw):
        if repo_set_partition == "tuned":
            return {"scored_repos": 2, "composite_mean": 0.7}
        return {"scored_repos": 0, "composite_mean": 0.0}

    monkeypatch.setattr(runner, "run_multi_replay", fake)
    assert runner.run_generalization_report("set.json")["generalization_gap"] is None


def test_generalization_report_records_a_repo_set_error_partition(monkeypatch):
    def fake(repo_set=None, repo_set_partition=None, **kw):
        if repo_set_partition == "held_out":
            raise RepoSetError("no held_out repos to replay")
        return {"scored_repos": 2, "composite_mean": 0.7}

    monkeypatch.setattr(runner, "run_multi_replay", fake)
    report = runner.run_generalization_report("set.json")
    assert report["held_out"] == {"error": "no held_out repos to replay",
                                  "scored_repos": 0, "composite_mean": 0.0}
    assert report["generalization_gap"] is None


def test_generalization_report_propagates_a_non_repo_set_error(monkeypatch):
    # Only RepoSetError is caught, despite the docstring's broader "recorded with its error".
    def fake(repo_set=None, repo_set_partition=None, **kw):
        raise RuntimeError("freeze failed")

    monkeypatch.setattr(runner, "run_multi_replay", fake)
    with pytest.raises(RuntimeError):
        runner.run_generalization_report("set.json")


# --- Helper coercions ----------------------------------------------------------------------------

def test_rows_list_coercion(caplog):
    assert runner._rows_list([{"a": 1}]) == [{"a": 1}]
    with caplog.at_level(logging.WARNING, logger=LOGGER):
        assert runner._rows_list(None) == []
    assert _warnings(caplog) == []                              # None is silent
    with caplog.at_level(logging.WARNING, logger=LOGGER):
        assert runner._rows_list("x") == []
    assert any("rows is str, not a list" in m for m in _warnings(caplog))


def test_sweep_rows_uses_its_own_field_name(caplog):
    with caplog.at_level(logging.WARNING, logger=LOGGER):
        assert runner._sweep_rows(7) == []
    assert any("weight_sweep rows is int, not a list" in m for m in _warnings(caplog))


def test_freeze_window_dict_coercion(caplog):
    assert runner._freeze_window_dict({"before": "2021-01-01"}) == {"before": "2021-01-01"}
    with caplog.at_level(logging.WARNING, logger=LOGGER):
        assert runner._freeze_window_dict(None) == {}
    assert _warnings(caplog) == []                              # None is silent
    with caplog.at_level(logging.WARNING, logger=LOGGER):
        assert runner._freeze_window_dict(5) == {}
    assert any("freeze_window is int, not a dict" in m for m in _warnings(caplog))
