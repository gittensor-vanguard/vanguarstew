"""Tests for the per-repo composite-score spread utility (deterministic, offline)."""

import errno
import json
import os
import subprocess
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from benchmark.repo_score_spread import (  # noqa: E402
    _is_number,
    _repo_scores,
    _spread,
    repo_score_spread_headline,
    summarize_repo_score_spread,
)
from scripts import repo_score_spread as cli  # noqa: E402


def _repo(score, tasks=5):
    return {"composite_mean": score, "tasks": tasks, "repos": 1, "scored_repos": 1}


def _multi(*scores):
    return {"per_repo": [_repo(s) for s in scores], "repos": len(scores), "scored_repos": len(scores)}


# --- the numeric guard (the review's crash + bool-coercion asks) -----------------------------------

def test_is_number_accepts_finite_numbers_only():
    assert _is_number(0) and _is_number(0.6) and _is_number(-1.5)
    assert not _is_number(True)          # bool never coerced to 1.0
    assert not _is_number("0.6")         # str does not reach math.isfinite (no TypeError)
    assert not _is_number(None)
    assert not _is_number(float("nan"))
    assert not _is_number(float("inf"))


# --- single / multi ------------------------------------------------------------------------------

def test_single_artifact_has_degenerate_spread():
    summary = summarize_repo_score_spread({"composite_mean": 0.6, "tasks": 5})
    assert summary["kind"] == "single"
    assert summary["scored_repos"] == 1
    assert summary["min"] == summary["max"] == 0.6
    assert summary["range"] == 0.0
    assert summary["partitions"] is None


def test_multi_artifact_spread():
    summary = summarize_repo_score_spread(_multi(0.4, 0.8, 0.6))
    assert summary["kind"] == "multi"
    assert summary["scored_repos"] == 3
    assert summary["min"] == 0.4
    assert summary["max"] == 0.8
    assert summary["range"] == 0.4


def test_empty_per_repo_has_no_scores():
    summary = summarize_repo_score_spread({"per_repo": []})
    assert summary["scored_repos"] == 0
    assert summary["min"] is None and summary["max"] is None and summary["range"] is None


def test_missing_and_non_numeric_scores_skipped():
    artifact = {
        "per_repo": [
            {"tasks": 1},                       # no composite_mean
            {"composite_mean": "x"},            # non-numeric
            {"composite_mean": True},           # bool, not coerced
            {"composite_mean": float("nan")},   # non-finite
            "nope",                             # non-dict entry
            5,
            {"composite_mean": 0.5},            # the only usable score
        ],
    }
    summary = summarize_repo_score_spread(artifact)
    assert summary["scored_repos"] == 1
    assert summary["min"] == summary["max"] == 0.5


# --- generalization ------------------------------------------------------------------------------

def test_generalization_reports_partitions_and_overall():
    summary = summarize_repo_score_spread({
        "generalization_gap": 0.05,
        "tuned": _multi(0.7, 0.9),
        "held_out": _multi(0.3, 0.5),
    })
    assert summary["kind"] == "generalization"
    assert summary["min"] == 0.3 and summary["max"] == 0.9  # overall across both partitions
    assert summary["scored_repos"] == 4
    assert summary["partitions"]["tuned"] == {"scored_repos": 2, "min": 0.7, "max": 0.9, "range": 0.2}
    assert summary["partitions"]["held_out"]["range"] == 0.2


def test_generalization_missing_partitions():
    summary = summarize_repo_score_spread({
        "generalization_gap": 0.0,
        "tuned": {"per_repo": []},   # no scored repos
        "held_out": {},              # missing everything
    })
    assert summary["scored_repos"] == 0
    assert summary["partitions"]["tuned"]["min"] is None
    assert summary["partitions"]["held_out"] == {
        "scored_repos": 0, "min": None, "max": None, "range": None,
    }


# --- invalid / unknown kinds ---------------------------------------------------------------------

def test_invalid_and_non_dict_artifacts():
    for bad in ({}, None, 5, "x", [1, 2]):
        summary = summarize_repo_score_spread(bad)
        assert summary["kind"] == "invalid"
        assert summary["scored_repos"] == 0
        assert summary["partitions"] is None


# --- helpers -------------------------------------------------------------------------------------

def test_repo_scores_single_and_non_numeric_top_level():
    assert _repo_scores({"composite_mean": 0.6}) == [0.6]
    assert _repo_scores({"composite_mean": "x"}) == []
    assert _repo_scores(None) == []


def test_spread_helper():
    assert _spread([]) == {"scored_repos": 0, "min": None, "max": None, "range": None}
    assert _spread([0.4, 0.8, 0.6]) == {"scored_repos": 3, "min": 0.4, "max": 0.8, "range": 0.4}


def test_headline_variants():
    summary = summarize_repo_score_spread(_multi(0.4, 0.8))
    assert repo_score_spread_headline(summary) == (
        "repo score spread: range 0.400 across 2 repo(s) (min 0.4, max 0.8)")
    assert repo_score_spread_headline({"scored_repos": 0}) == "repo score spread: no scored repos"
    assert repo_score_spread_headline({}) == "repo score spread: no scored repos"
    assert repo_score_spread_headline("nope") == "repo score spread: no scored repos"
    # Defensive: a positive count with a non-numeric range degrades the range text, not crashes.
    assert "n/a" in repo_score_spread_headline({"scored_repos": 2, "range": None, "min": 1, "max": 1})


# --- CLI: success + every error path (incl. the OSError/permission branch) ------------------------

def _write(tmp_path, name, text):
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return str(path)


def test_cli_success(tmp_path, capsys):
    path = _write(tmp_path, "ok.json", json.dumps(_multi(0.4, 0.8)))
    assert cli.run([path]) == 0
    body = json.loads(capsys.readouterr().out)
    assert body["range"] == 0.4


def test_cli_generalization_reports_partitions(tmp_path, capsys):
    artifact = {"generalization_gap": 0.05, "tuned": _multi(0.7, 0.9), "held_out": _multi(0.3, 0.5)}
    path = _write(tmp_path, "gen.json", json.dumps(artifact))
    assert cli.run([path]) == 0
    body = json.loads(capsys.readouterr().out)
    assert body["kind"] == "generalization"
    assert body["partitions"]["tuned"]["max"] == 0.9


def test_cli_missing_file(tmp_path, capsys):
    missing = tmp_path / "nope.json"
    assert cli.run([str(missing)]) == 2
    err = capsys.readouterr().err
    assert err == f"artifact not found: {missing}\n"


def test_cli_invalid_json(tmp_path, capsys):
    path = _write(tmp_path, "bad.json", "{not json")
    assert cli.run([path]) == 2
    err = capsys.readouterr().err
    assert "Traceback" not in err
    assert err.startswith(f"artifact is not valid JSON ({path}):")


def test_cli_non_object_artifact(tmp_path, capsys):
    path = _write(tmp_path, "arr.json", "[1, 2, 3]")
    assert cli.run([path]) == 2
    assert capsys.readouterr().err == f"artifact must be a JSON object: {path}\n"


def test_cli_directory_path_exits_two(tmp_path, capsys):
    # POSIX: IsADirectoryError → "directory … not a file".
    # Windows: PermissionError → "not readable" (directory permission error).
    assert cli.run([str(tmp_path)]) == 2
    err = capsys.readouterr().err
    assert "Traceback" not in err
    assert "Errno" not in err
    if os.name == "nt":
        assert err == (
            f"artifact is not readable (check file permissions): {tmp_path}\n"
        )
    else:
        assert err == f"artifact path is a directory, not a file: {tmp_path}\n"


def test_cli_broken_symlink_exits_two(tmp_path, capsys):
    link = tmp_path / "broken.json"
    link.symlink_to(tmp_path / "nonexistent.json")
    assert cli.run([str(link)]) == 2
    assert capsys.readouterr().err == (
        f"artifact is a broken symlink (target does not exist): {link}\n"
    )


@pytest.mark.skipif(
    os.name == "nt" or (hasattr(os, "geteuid") and os.geteuid() == 0),
    reason="POSIX permission bits are not enforced on Windows; root bypasses them too",
)
def test_cli_unreadable_file_reports_clean_error(tmp_path, capsys):
    path = tmp_path / "artifact.json"
    path.write_text("{}", encoding="utf-8")
    os.chmod(path, 0)
    try:
        assert cli.run([str(path)]) == 2
    finally:
        os.chmod(path, 0o644)
    assert capsys.readouterr().err == (
        f"artifact is not readable (check file permissions): {path}\n"
    )


def test_cli_symlink_to_directory_exits_two(tmp_path, capsys):
    target = tmp_path / "dir_target"
    target.mkdir()
    link = tmp_path / "link-to-dir.json"
    link.symlink_to(target)
    assert cli.run([str(link)]) == 2
    err = capsys.readouterr().err
    assert "Traceback" not in err
    assert "Errno" not in err
    if os.name == "nt":
        assert err == (
            f"artifact is not readable (check file permissions): {link}\n"
        )
    else:
        assert err == f"artifact path is a directory, not a file: {link}\n"


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


def test_load_artifact_is_a_directory_error_is_handled(monkeypatch, tmp_path, capsys):
    path = str(tmp_path / "run.json")

    def _raise(*args, **kwargs):
        raise IsADirectoryError(21, "Is a directory", path)

    monkeypatch.setattr("builtins.open", _raise)
    with pytest.raises(SystemExit) as excinfo:
        cli.load_artifact(path)
    assert excinfo.value.code == 2
    assert capsys.readouterr().err == f"artifact path is a directory, not a file: {path}\n"


def test_load_artifact_permission_error_is_handled(monkeypatch, tmp_path, capsys):
    path = str(tmp_path / "run.json")

    def _raise(*args, **kwargs):
        raise PermissionError(13, "Permission denied", path)

    monkeypatch.setattr("builtins.open", _raise)
    with pytest.raises(SystemExit) as excinfo:
        cli.load_artifact(path)
    assert excinfo.value.code == 2
    assert capsys.readouterr().err == (
        f"artifact is not readable (check file permissions): {path}\n"
    )


def test_load_artifact_windows_directory_permission_error_message(monkeypatch, tmp_path, capsys):
    # Explicit Windows directory-open failure path: PermissionError, exact message.
    path = str(tmp_path)

    def _raise(*args, **kwargs):
        raise PermissionError(13, "Permission denied", path)

    monkeypatch.setattr("builtins.open", _raise)
    with pytest.raises(SystemExit) as excinfo:
        cli.load_artifact(path)
    assert excinfo.value.code == 2
    assert capsys.readouterr().err == (
        f"artifact is not readable (check file permissions): {path}\n"
    )


def test_load_artifact_generic_os_error_is_handled(monkeypatch, tmp_path, capsys):
    path = str(tmp_path / "run.json")
    exc = OSError(5, "Input/output error", path)

    def _raise(*args, **kwargs):
        raise exc

    monkeypatch.setattr("builtins.open", _raise)
    with pytest.raises(SystemExit) as excinfo:
        cli.load_artifact(path)
    assert excinfo.value.code == 2
    assert capsys.readouterr().err == f"cannot read artifact ({path}): {exc}\n"


def test_module_main_no_arg_exits_nonzero():
    proc = subprocess.run(
        [sys.executable, "-m", "scripts.repo_score_spread"],
        cwd=ROOT, capture_output=True, text=True,
    )
    assert proc.returncode != 0
    assert "artifact" in proc.stderr.lower()
