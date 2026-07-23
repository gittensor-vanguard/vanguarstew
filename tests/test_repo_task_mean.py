"""Tests for repo task mean summary and CLI (deterministic, offline)."""

import errno
import json
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from benchmark.repo_task_mean import repo_task_mean_headline, summarize_repo_task_mean  # noqa: E402
from scripts import repo_task_mean as cli  # noqa: E402


def _repo(tasks, name="r"):
    return {"repo": name, "tasks": tasks, "composite_mean": 0.6}


def _multi(*task_counts):
    return {
        "repos": len(task_counts),
        "scored_repos": sum(1 for t in task_counts if t > 0),
        "composite_mean": 0.6,
        "per_repo": [_repo(t, f"r{i}") for i, t in enumerate(task_counts)],
    }


def test_single_repo_mean_is_task_count():
    out = summarize_repo_task_mean({"composite_mean": 0.6, "tasks": 8})
    assert out["mean_tasks_per_repo"] == 8.0
    assert out["scored_repos"] == 1


def test_multi_repo_mean_averages_scored_repos_only():
    out = summarize_repo_task_mean(_multi(6, 0, 4))
    assert out["scored_repos"] == 2
    assert out["total_tasks"] == 10
    assert out["mean_tasks_per_repo"] == 5.0


def test_generalization_reports_partitions():
    art = {
        "tuned": _multi(4, 2),
        "held_out": _multi(3),
        "generalization_gap": 0.1,
    }
    out = summarize_repo_task_mean(art)
    assert out["scored_repos"] == 3
    assert out["total_tasks"] == 9
    assert out["mean_tasks_per_repo"] == 3.0
    assert out["partitions"]["tuned"]["mean_tasks_per_repo"] == 3.0


def test_zero_scored_repos_yields_none_mean():
    out = summarize_repo_task_mean(_multi(0, 0))
    assert out["mean_tasks_per_repo"] is None


def test_malformed_row_skipped():
    art = {"per_repo": ["bad", _repo(5)], "composite_mean": 0.5, "repos": 1, "scored_repos": 1}
    out = summarize_repo_task_mean(art)
    assert out["mean_tasks_per_repo"] == 5.0


def test_headline():
    out = summarize_repo_task_mean(_multi(3, 3))
    assert "mean 3.000" in repo_task_mean_headline(out)


def test_headline_tolerates_a_non_finite_or_oversized_mean():
    # A hand-built/deserialized summary can carry a mean_tasks_per_repo that json round-trips
    # (NaN/Infinity) or an oversized int; `f"{mean:.3f}"` renders `mean nan`/`mean inf` or raises
    # OverflowError. A non-finite/oversized mean is not a real value, so the headline shows
    # `mean n/a` instead of crashing; a finite mean is still formatted (behavior unchanged).
    for bad in (float("nan"), float("inf"), float("-inf"), 10**400):
        line = repo_task_mean_headline(
            {"kind": "multi", "scored_repos": 3, "mean_tasks_per_repo": bad})
        assert "mean n/a tasks/repo" in line, bad
    assert "mean 4.000" in repo_task_mean_headline(
        {"kind": "multi", "scored_repos": 3, "mean_tasks_per_repo": 4.0})


def test_single_repo_oversized_task_count_is_skipped():
    # json.load yields a Python int for an oversized literal; it must be treated as malformed
    # (skipped) rather than crashing float(tasks) with OverflowError.
    out = summarize_repo_task_mean({"composite_mean": 0.5, "tasks": 10**400})
    assert out["scored_repos"] == 0
    assert out["mean_tasks_per_repo"] is None


def test_multi_repo_oversized_task_count_is_skipped():
    art = {"per_repo": [{"repo": "a", "tasks": 10**400}, _repo(4, "b")], "scored_repos": 2}
    out = summarize_repo_task_mean(art)
    assert out["scored_repos"] == 1
    assert out["total_tasks"] == 4
    assert out["mean_tasks_per_repo"] == 4.0


def test_generalization_oversized_task_count_is_skipped():
    art = {
        "tuned": {"per_repo": [{"repo": "a", "tasks": 10**400}]},
        "held_out": _multi(3),
        "generalization_gap": 0.0,
    }
    out = summarize_repo_task_mean(art)
    assert out["scored_repos"] == 1
    assert out["total_tasks"] == 3
    assert out["mean_tasks_per_repo"] == 3.0
    assert out["partitions"]["tuned"]["scored_repos"] == 0


@pytest.fixture
def tmp_artifact(tmp_path):
    def write(payload):
        path = tmp_path / "run.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        return str(path)
    return write


def test_cli(tmp_artifact, capsys):
    path = tmp_artifact(_multi(4, 2))
    assert cli.run([path]) == 0
    body = json.loads(capsys.readouterr().out)
    assert body["mean_tasks_per_repo"] == 3.0


def test_cli_directory_path_exits_two(tmp_path, capsys):
    # A directory artifact path is an OSError (IsADirectoryError on POSIX, PermissionError on
    # Windows), not a FileNotFoundError -- it must exit 2 with an actionable message, not a raw
    # traceback.
    assert cli.run([str(tmp_path)]) == 2
    err = capsys.readouterr().err
    assert "directory" in err or "not readable" in err


def test_cli_broken_symlink_reports_clean_error(tmp_path, capsys):
    link = tmp_path / "broken.json"
    link.symlink_to(tmp_path / "nonexistent.json")
    assert cli.run([str(link)]) == 2
    assert capsys.readouterr().err == (
        f"artifact is a broken symlink (target does not exist): {link}\n"
    )


def test_load_artifact_broken_symlink_is_handled(tmp_path, capsys):
    link = tmp_path / "broken.json"
    link.symlink_to(tmp_path / "nonexistent.json")
    with pytest.raises(SystemExit) as excinfo:
        cli.load_artifact(str(link))
    assert excinfo.value.code == 2
    assert capsys.readouterr().err == (
        f"artifact is a broken symlink (target does not exist): {link}\n"
    )


def test_load_artifact_symlink_loop_is_handled(monkeypatch, tmp_path, capsys):
    path = str(tmp_path / "loop.json")

    def _raise(*args, **kwargs):
        raise OSError(errno.ELOOP, "Too many levels of symbolic links", path)

    monkeypatch.setattr("builtins.open", _raise)
    with pytest.raises(SystemExit) as excinfo:
        cli.load_artifact(path)
    assert excinfo.value.code == 2
    assert capsys.readouterr().err == f"artifact path is a symlink loop: {path}\n"
