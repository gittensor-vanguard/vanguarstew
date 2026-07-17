"""Tests for replay-result reporting/artifact helpers."""

import json
import os
import shutil
import subprocess
import sys
from unittest.mock import patch

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from benchmark.repo_set import RepoSetError  # noqa: E402
from scripts.run_eval import (  # noqa: E402
    _weight_sweep_rows,
    check_score_floor,
    main,
    result_summary_lines,
    write_result_artifact,
)


def _tiny_repo(dirpath, n=4, prefix="feat"):
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


def _run_cli(*args, env=None):
    full_env = {**os.environ, "VANGUARSTEW_OFFLINE": "1"}
    if env:
        full_env.update(env)
    return subprocess.run(
        [sys.executable, "-m", "scripts.run_eval", *args],
        cwd=ROOT, capture_output=True, text=True, check=False, env=full_env,
    )


def test_write_result_artifact_preserves_judge_order_stats(tmp_path):
    out = tmp_path / "result.json"
    result = {
        "tasks": 2,
        "judge_order_stats": {
            "agree": 1,
            "disagree": 1,
            "tie": 0,
            "single": 0,
            "offline": 0,
            "dual_order_tasks": 2,
            "disagreement_rate": 0.5,
        },
        "judge_report": {
            "summary": "judge W-L-T 1-0-1; disagreement_rate=50.0% (1/2 dual-order tasks)",
        },
    }
    write_result_artifact(str(out), result)
    with open(out, "r", encoding="utf-8") as f:
        saved = json.load(f)
    assert saved["judge_order_stats"]["disagreement_rate"] == 0.5
    assert saved["judge_report"]["summary"].startswith("judge W-L-T")


def test_result_summary_lines_emit_judge_headline_when_present():
    lines = result_summary_lines({
        "judge_report": {
            "summary": "judge W-L-T 1-0-1; disagreement_rate=50.0% (1/2 dual-order tasks)",
        }
    })
    assert lines == ["judge W-L-T 1-0-1; disagreement_rate=50.0% (1/2 dual-order tasks)"]


def test_result_summary_lines_omit_missing_judge_report():
    assert result_summary_lines({"tasks": 0, "error": "no usable tasks"}) == []


def test_check_score_floor_passes_when_above():
    assert check_score_floor({"composite_mean": 0.6}, 0.5) is None


def test_check_score_floor_passes_at_exact_threshold():
    assert check_score_floor({"composite_mean": 0.5}, 0.5) is None


def test_check_score_floor_fails_when_below():
    msg = check_score_floor({"composite_mean": 0.4}, 0.5)
    assert msg is not None
    assert "FAIL" in msg
    assert "0.400" in msg
    assert "--fail-under=0.5" in msg


def test_check_score_floor_fails_when_missing():
    msg = check_score_floor({}, 0.5)
    assert msg is not None
    assert "missing" in msg


def test_check_score_floor_fails_closed_on_non_finite_composite():
    # NaN/Inf must not silently pass --fail-under (nan < x and inf < x are both False).
    for bad in (float("nan"), float("inf"), float("-inf")):
        msg = check_score_floor({"composite_mean": bad}, 0.5)
        assert msg is not None, bad
        assert "missing or non-numeric" in msg
        assert "--fail-under=0.5" in msg


def test_check_score_floor_fails_closed_on_oversized_int_composite():
    # json.load can yield an int too large for float(); treat as non-numeric, never crash.
    msg = check_score_floor({"composite_mean": 10**400}, 0.5)
    assert msg is not None
    assert "missing or non-numeric" in msg


def test_check_score_floor_rejects_bool_and_string_scores():
    # bool is an int subclass; string "NaN" is not numeric — both fail closed.
    for bad in (True, False, "NaN", "0.9"):
        msg = check_score_floor({"composite_mean": bad}, 0.5)
        assert msg is not None, bad
        assert "missing or non-numeric" in msg


def test_check_score_floor_skipped_when_disabled():
    assert check_score_floor({"composite_mean": 0.1}, None) is None


def _generalization_result(tuned=0.6, held_out=0.6, tuned_scored=2, held_scored=1):
    return {
        "repo_set": "foo.json",
        "tuned": {"composite_mean": tuned, "scored_repos": tuned_scored},
        "held_out": {"composite_mean": held_out, "scored_repos": held_scored},
        "generalization_gap": round(tuned - held_out, 3) if tuned_scored and held_scored else None,
    }


def test_check_score_floor_passes_for_generalization_shape():
    assert check_score_floor(_generalization_result(), 0.0) is None
    assert check_score_floor(_generalization_result(tuned=0.6, held_out=0.55), 0.5) is None


def test_check_score_floor_fails_when_generalization_partition_below_floor():
    msg = check_score_floor(_generalization_result(tuned=0.4, held_out=0.6), 0.5)
    assert msg is not None and "tuned" in msg and "0.400" in msg
    msg = check_score_floor(_generalization_result(tuned=0.6, held_out=0.4), 0.5)
    assert msg is not None and "held_out" in msg


def test_check_score_floor_fails_closed_on_non_finite_generalization_partition():
    # A scored partition with NaN/Inf/oversized composite must fail closed, not skip.
    for label, bad in (
        ("tuned", float("nan")),
        ("held_out", float("inf")),
        ("tuned", 10**400),
        ("held_out", True),
    ):
        result = _generalization_result()
        result[label]["composite_mean"] = bad
        msg = check_score_floor(result, 0.5)
        assert msg is not None, (label, bad)
        assert label in msg
        assert "missing or non-numeric" in msg


def test_check_score_floor_skips_unscored_generalization_partition():
    # A partition with scored_repos=0 is not gated — same posture as generalization_gap.
    assert check_score_floor(
        _generalization_result(tuned=0.95, tuned_scored=2, held_scored=0), 0.9,
    ) is None


# --- #610: an unscored multi-repo run must not be gated as a real 0.0 below the floor -----


def test_check_score_floor_skips_unscored_multi_repo_placeholder():
    # A multi-repo run that scored nothing reports scored_repos: 0 with a placeholder 0.0. It has
    # no real score to gate, so the floor is skipped (None), not reported as "below threshold".
    assert check_score_floor(
        {"repos": 2, "scored_repos": 0, "skipped": 2, "composite_mean": 0.0}, 0.5,
    ) is None


def test_check_score_floor_float_zero_scored_repos_is_a_placeholder():
    # scored_repos may arrive as a float; a float 0.0 count is still the unscored placeholder.
    assert check_score_floor(
        {"repos": 2, "scored_repos": 0.0, "skipped": 2, "composite_mean": 0.0}, 0.5,
    ) is None


def test_check_score_floor_flags_genuine_zero_multi_repo():
    # Control isolating the cause: same composite_mean 0.0, but scored_repos > 0 means the run
    # really scored 0.0, so it IS gated as below the floor — proving scored_repos, not the numeric
    # 0.0, is what marks the placeholder unscored.
    msg = check_score_floor(
        {"repos": 2, "scored_repos": 2, "skipped": 0, "composite_mean": 0.0}, 0.5,
    )
    assert msg is not None and "FAIL" in msg and "0.000" in msg


def test_check_score_floor_bool_scored_repos_is_not_a_placeholder():
    # A bool scored_repos (isinstance(False, int) is True in Python) is malformed, not the zero
    # placeholder, so a missing composite must still be reported as an error, not silently skipped.
    msg = check_score_floor({"repos": 1, "scored_repos": False}, 0.5)
    assert msg is not None and "missing or non-numeric" in msg


def test_check_score_floor_single_repo_zero_below_floor_unchanged():
    # A single-repo run carries no scored_repos key, so its real 0.0 is still gated normally.
    msg = check_score_floor({"tasks": 3, "composite_mean": 0.0}, 0.5)
    assert msg is not None and "FAIL" in msg


# --- #573: non-list weight_sweep must not abort stderr reporting --------------------

_MALFORMED_WEIGHT_SWEEP = [42, 3.14, True, {"w_judge": 0.6}, "not a list"]


def test_weight_sweep_rows_accepts_only_real_lists():
    rows = [{"w_judge": 0.6, "w_objective": 0.4, "composite_mean": 0.5}]
    for bad in _MALFORMED_WEIGHT_SWEEP:
        assert _weight_sweep_rows({"weight_sweep": bad}) == [], bad
    assert _weight_sweep_rows({"weight_sweep": rows}) == rows
    assert _weight_sweep_rows({}) == []


def test_weight_sweep_rows_logs_warning_for_non_list_field(caplog):
    import logging

    with caplog.at_level(logging.WARNING, logger="scripts.run_eval"):
        assert _weight_sweep_rows({"weight_sweep": 42}) == []
    assert any("weight_sweep is int" in r.message for r in caplog.records)


# --- unit-level: main()'s try/except around the dispatch, without needing real git/repo-set
# fixtures -- isolates the error-handling logic itself from the subprocess integration tests
# below, so a regression in the except clause is caught even if the integration tests' exact
# git/gh error text ever changes. -----------------------------------------------------------

def _argv(*args):
    return ["run_eval.py", *args]


def test_main_catches_runtime_error_from_run_replay(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", _argv("--repo", "/some/repo", "--tasks", "1", "--horizon", "1"))
    with patch("scripts.run_eval.run_replay", side_effect=RuntimeError("git thing failed: boom")):
        with pytest.raises(SystemExit) as exc:
            main()
    assert exc.value.code == 1
    assert "git thing failed: boom" in capsys.readouterr().err


def test_main_catches_repo_set_error_from_run_multi_replay(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", _argv("--repo-set", "/some/config.json"))
    with patch("scripts.run_eval.run_multi_replay", side_effect=RepoSetError("bad config: boom")):
        with pytest.raises(SystemExit) as exc:
            main()
    assert exc.value.code == 1
    assert "bad config: boom" in capsys.readouterr().err


def test_main_catches_repo_set_error_from_run_generalization_report(monkeypatch, capsys):
    monkeypatch.setattr(
        sys, "argv",
        _argv("--repo-set", "/some/config.json", "--generalization"),
    )
    with patch("scripts.run_eval.run_generalization_report",
               side_effect=RepoSetError("bad config: boom")):
        with pytest.raises(SystemExit) as exc:
            main()
    assert exc.value.code == 1
    assert "bad config: boom" in capsys.readouterr().err


def test_main_catches_os_error_writing_the_out_artifact(monkeypatch, capsys, tmp_path):
    bad_out = tmp_path / "does-not-exist-dir" / "out.json"
    monkeypatch.setattr(
        sys, "argv",
        _argv("--repo", "/some/repo", "--tasks", "1", "--horizon", "1", "--out", str(bad_out)),
    )
    with patch("scripts.run_eval.run_replay", return_value={"composite_mean": 0.6, "tasks": 1}):
        with pytest.raises(SystemExit) as exc:
            main()
    assert exc.value.code == 1
    err = capsys.readouterr().err
    assert "cannot write --out" in err
    assert str(bad_out) in err


def test_main_does_not_catch_unrelated_exceptions(monkeypatch):
    # The guard is deliberately narrow to (RuntimeError, RepoSetError); anything else (a real
    # bug elsewhere) must still surface normally rather than being silently swallowed.
    monkeypatch.setattr(sys, "argv", _argv("--repo", "/some/repo", "--tasks", "1", "--horizon", "1"))
    with patch("scripts.run_eval.run_replay", side_effect=KeyError("unexpected")):
        with pytest.raises(KeyError):
            main()


# --- subprocess-level: drive the actual CLI entry point end to end -------------------------

@pytest.mark.skipif(shutil.which("git") is None, reason="git required")
def test_cli_reports_a_clean_error_for_a_non_git_repo_path(tmp_path):
    # --repo pointing at a directory that isn't a git repo must not crash with a raw
    # traceback -- it's the CLI's most basic invocation path.
    not_git = tmp_path / "not-a-git-dir"
    not_git.mkdir()
    result = _run_cli("--repo", str(not_git), "--tasks", "1", "--horizon", "1")
    assert result.returncode == 1
    assert "Traceback" not in result.stderr
    assert "not a git repository" in result.stderr


@pytest.mark.skipif(shutil.which("git") is None, reason="git required")
def test_cli_reports_a_clean_error_for_a_nonexistent_repo_path(tmp_path):
    missing = tmp_path / "does-not-exist"
    result = _run_cli("--repo", str(missing), "--tasks", "1", "--horizon", "1")
    assert result.returncode == 1
    assert "Traceback" not in result.stderr
    # the real git stderr text, not a generic placeholder
    assert "No such file or directory" in result.stderr
    assert str(missing) in result.stderr


@pytest.mark.skipif(shutil.which("git") is None, reason="git required")
def test_cli_reports_a_clean_error_for_a_missing_agent_file(tmp_path):
    repo = _tiny_repo(str(tmp_path / "repo"), n=16)
    missing = tmp_path / "no-such-agent.py"
    result = _run_cli(
        "--repo", repo, "--tasks", "1", "--horizon", "1", "--agent", str(missing),
    )
    assert result.returncode == 1
    assert "Traceback" not in result.stderr
    assert "does not exist or is not a regular file" in result.stderr
    assert missing.name in result.stderr


@pytest.mark.skipif(shutil.which("git") is None, reason="git required")
def test_cli_reports_a_clean_error_for_an_agent_directory(tmp_path):
    repo = _tiny_repo(str(tmp_path / "repo"), n=16)
    agent_dir = tmp_path / "agent-dir"
    agent_dir.mkdir()
    result = _run_cli(
        "--repo", repo, "--tasks", "1", "--horizon", "1", "--agent", str(agent_dir),
    )
    assert result.returncode == 1
    assert "Traceback" not in result.stderr
    assert "does not exist or is not a regular file" in result.stderr
    assert agent_dir.name in result.stderr


@pytest.mark.skipif(shutil.which("git") is None, reason="git required")
def test_cli_reports_a_clean_error_for_an_agent_syntax_error(tmp_path):
    repo = _tiny_repo(str(tmp_path / "repo"), n=16)
    bad_agent = tmp_path / "bad_agent.py"
    bad_agent.write_text("def solve():\n", encoding="utf-8")
    result = _run_cli(
        "--repo", repo, "--tasks", "1", "--horizon", "1", "--agent", str(bad_agent),
    )
    assert result.returncode == 1
    assert "Traceback" not in result.stderr
    assert "cannot load agent file" in result.stderr
    assert "expected an indented block" in result.stderr
    assert bad_agent.name in result.stderr


def test_cli_reports_a_clean_error_for_a_missing_repo_set(tmp_path):
    missing = tmp_path / "does-not-exist.json"
    result = _run_cli("--repo-set", str(missing))
    assert result.returncode == 1
    assert "Traceback" not in result.stderr
    # benchmark/repo_set.py's own _require message: "repo-set config not found: {path}"
    assert "not found" in result.stderr
    assert str(missing) in result.stderr


@pytest.mark.skipif(shutil.which("git") is None, reason="git required")
def test_cli_reports_a_clean_error_for_an_unwritable_out_path(tmp_path):
    repo = _tiny_repo(str(tmp_path / "repo"), n=16)
    bad_out = tmp_path / "does-not-exist-dir" / "out.json"
    result = _run_cli("--repo", repo, "--tasks", "1", "--horizon", "1", "--out", str(bad_out))
    assert result.returncode == 1
    assert "Traceback" not in result.stderr
    assert "cannot write --out" in result.stderr


@pytest.mark.skipif(shutil.which("git") is None, reason="git required")
def test_cli_still_replays_a_well_formed_repo(tmp_path):
    # The guard must be inert on the happy path: a real git repo still produces a real
    # replay artifact -- proving the try/except doesn't swallow successful runs, and that
    # the run actually executed the replay logic (not just an empty/stub result).
    repo = _tiny_repo(str(tmp_path / "repo"), n=16)
    out_path = tmp_path / "result.json"
    result = _run_cli("--repo", repo, "--tasks", "1", "--horizon", "1", "--out", str(out_path))
    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert "composite_mean" in payload
    assert isinstance(payload.get("tasks"), int) and payload["tasks"] >= 1
    assert "rows" in payload and len(payload["rows"]) == payload["tasks"]
    # --out actually wrote the same artifact that was printed to stdout
    with open(out_path, "r", encoding="utf-8") as f:
        assert json.load(f) == payload


# ---- --fail-under CLI gate --------------------------------------------------


def test_cli_fail_under_exits_1_when_below_floor(monkeypatch, capsys):
    monkeypatch.setattr(
        sys, "argv",
        _argv("--repo", "/some/repo", "--tasks", "1", "--horizon", "1", "--fail-under", "0.5"),
    )
    with patch(
        "scripts.run_eval.run_replay",
        return_value={"composite_mean": 0.3, "tasks": 1, "rows": [{}]},
    ):
        with pytest.raises(SystemExit) as exc:
            main()
    assert exc.value.code == 1
    err = capsys.readouterr().err
    assert "FAIL" in err
    assert "0.300" in err
    assert "--fail-under=0.5" in err


def test_cli_fail_under_exits_0_when_above_floor(monkeypatch):
    monkeypatch.setattr(
        sys, "argv",
        _argv("--repo", "/some/repo", "--tasks", "1", "--horizon", "1", "--fail-under", "0.5"),
    )
    with patch(
        "scripts.run_eval.run_replay",
        return_value={"composite_mean": 0.6, "tasks": 1, "rows": [{}]},
    ):
        main()  # should not raise SystemExit
