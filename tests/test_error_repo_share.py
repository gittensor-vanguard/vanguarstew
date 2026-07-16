"""Tests for the errored-repo share utility (deterministic, offline)."""

import errno
import json
import os
import subprocess
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from benchmark.error_repo_share import (  # noqa: E402
    _error_share,
    _has_error,
    _repo_error_flags,
    error_repo_share_headline,
    summarize_error_repo_share,
)
from scripts import error_repo_share as cli  # noqa: E402


def _ok(**extra):
    return {"composite_mean": 0.6, "tasks": 5, **extra}


def _err(msg="boom", **extra):
    return {"error": msg, "tasks": 0, **extra}


# --- single / multi ------------------------------------------------------------------------------

def test_single_clean_and_errored():
    assert summarize_error_repo_share(_ok())["error_share"] == 0.0
    errored = summarize_error_repo_share(_err())
    assert errored["kind"] == "single"
    assert errored == {
        "kind": "single", "repos": 1, "error_repos": 1, "error_share": 1.0, "partitions": None,
    }


def test_multi_share():
    summary = summarize_error_repo_share({"per_repo": [_ok(), _err(), _ok(), _err()]})
    assert summary["kind"] == "multi"
    assert summary["repos"] == 4
    assert summary["error_repos"] == 2
    assert summary["error_share"] == 0.5


def test_empty_per_repo_has_none_share():
    summary = summarize_error_repo_share({"per_repo": []})
    assert summary == {
        "kind": "multi", "repos": 0, "error_repos": 0, "error_share": None, "partitions": None,
    }


def test_non_countable_per_repo_entries_are_skipped():
    # Ints, None, and empty/whitespace strings carry no error signal and are not counted.
    summary = summarize_error_repo_share({"per_repo": [_err(), 5, None, "", "   ", _ok()]})
    assert summary["repos"] == 2 and summary["error_repos"] == 1


def test_malformed_string_per_repo_row_counts_as_error():
    # A per_repo row that is itself a non-empty string is a malformed/corrupt entry, not a
    # well-formed result dict — count it as an errored repo (matching the canonical
    # acceptance._partition_error and check_run_clean) so the share reflects the real failure
    # rate rather than silently under-reporting it.
    summary = summarize_error_repo_share({"per_repo": [{"tasks": 3}, "corrupt row"]})
    assert summary == {
        "kind": "multi", "repos": 2, "error_repos": 1, "error_share": 0.5, "partitions": None,
    }
    # Under a generalization partition too: the malformed row counts within its slice.
    gen = summarize_error_repo_share({
        "tuned": {"per_repo": [_ok(), "boom"]},
        "held_out": {"per_repo": [_ok()]},
        "generalization_gap": 0.0,
    })
    assert gen["partitions"]["tuned"]["error_repos"] == 1
    assert gen["partitions"]["held_out"]["error_repos"] == 0


def test_per_repo_present_does_not_double_count_top_level_error():
    # A malformed run can carry both a top-level error and a per_repo list; the per_repo rows win, so
    # the top-level error is not counted a second time.
    summary = summarize_error_repo_share({"error": "top-level boom", "per_repo": [_ok(), _ok()]})
    assert summary["error_repos"] == 0 and summary["error_share"] == 0.0


def test_empty_string_and_missing_error_are_clean():
    assert _has_error({"error": ""}) is False
    assert _has_error({"error": None}) is False
    assert _has_error({}) is False
    assert _has_error("not a dict") is False
    assert _has_error({"error": "x"}) is True


# --- generalization ------------------------------------------------------------------------------

def test_generalization_partitions_and_overall():
    summary = summarize_error_repo_share({
        "generalization_gap": 0.05,
        "tuned": {"per_repo": [_ok(), _ok()]},
        "held_out": {"per_repo": [_err(), _ok()]},
    })
    assert summary["kind"] == "generalization"
    assert summary["repos"] == 4 and summary["error_repos"] == 1
    assert summary["error_share"] == 0.25
    assert summary["partitions"]["tuned"]["error_share"] == 0.0
    assert summary["partitions"]["held_out"]["error_share"] == 0.5


def test_generalization_missing_partitions():
    summary = summarize_error_repo_share({
        "generalization_gap": 0.0,
        "tuned": {"per_repo": []},
        "held_out": {},   # single-repo shape: one (clean) repo
    })
    assert summary["partitions"]["tuned"]["error_share"] is None
    assert summary["partitions"]["held_out"] == {"repos": 1, "error_repos": 0, "error_share": 0.0}


# --- invalid -------------------------------------------------------------------------------------

def test_invalid_and_non_dict_artifacts():
    # {} classifies as invalid; None/scalars/lists degrade to an empty dict → also invalid.
    for bad in ({}, None, 5, "x", [1, 2]):
        summary = summarize_error_repo_share(bad)
        assert summary["kind"] == "invalid"
        assert summary["partitions"] is None


# --- helpers -------------------------------------------------------------------------------------

def test_error_share_helper():
    assert _error_share([]) == {"repos": 0, "error_repos": 0, "error_share": None}
    assert _error_share([True, False, False, True]) == {"repos": 4, "error_repos": 2, "error_share": 0.5}


def test_repo_error_flags_single_and_multi():
    assert _repo_error_flags({"error": "x"}) == [True]
    assert _repo_error_flags({"per_repo": [_ok(), _err()]}) == [False, True]


def test_headline_variants():
    summary = summarize_error_repo_share({"per_repo": [_ok(), _err()]})
    assert error_repo_share_headline(summary) == "error repo share: 50.0% (1/2 repos errored)"
    assert error_repo_share_headline({"repos": 0}) == "error repo share: no repos"
    assert error_repo_share_headline({}) == "error repo share: no repos"
    assert error_repo_share_headline("nope") == "error repo share: no repos"
    # Defensive: a positive repo count with a non-numeric share renders n/a, not a crash.
    assert "n/a" in error_repo_share_headline({"repos": 2, "error_repos": 0, "error_share": None})


# --- CLI: success + every error path -------------------------------------------------------------

def _write(tmp_path, name, text):
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return str(path)


def test_cli_success(tmp_path, capsys):
    path = _write(tmp_path, "ok.json", json.dumps({"per_repo": [_ok(), _err()]}))
    assert cli.run([path]) == 0
    assert json.loads(capsys.readouterr().out)["error_share"] == 0.5


def test_cli_generalization(tmp_path, capsys):
    artifact = {"generalization_gap": 0.05, "tuned": {"per_repo": [_ok(), _ok()]},
                "held_out": {"per_repo": [_err(), _ok()]}}
    path = _write(tmp_path, "gen.json", json.dumps(artifact))
    assert cli.run([path]) == 0
    assert json.loads(capsys.readouterr().out)["partitions"]["held_out"]["error_share"] == 0.5


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


def test_cli_oversized_int_literal_exits_two(tmp_path, capsys):
    path = _write(tmp_path, "huge.json", '{"repos": ' + "9" * 5000 + "}")
    assert cli.run([path]) == 2
    err = capsys.readouterr().err
    assert "Traceback" not in err
    assert err.startswith(f"artifact is not valid JSON ({path}):")


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
        [sys.executable, "-m", "scripts.error_repo_share"],
        cwd=ROOT, capture_output=True, text=True,
    )
    assert proc.returncode != 0
    assert "artifact" in proc.stderr.lower()
