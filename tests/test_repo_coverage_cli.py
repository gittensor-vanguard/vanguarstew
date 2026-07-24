"""Tests for the repo-coverage CLI's artifact loader (path-error classification)."""

import errno
import json
import os
import subprocess
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from scripts import repo_coverage as cli  # noqa: E402


def _run(*args):
    return subprocess.run(
        [sys.executable, "-m", "scripts.repo_coverage", *args],
        cwd=ROOT, capture_output=True, text=True, check=False,
    )


def test_cli_renders_a_valid_artifact():
    # A well-formed multi-repo artifact still reports and exits 0 (behavior unchanged).
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "cov.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"repos": 3, "scored_repos": 3, "skipped": 0,
                       "per_repo": [{"tasks": 3}, {"tasks": 3}, {"tasks": 3}]}, f)
        result = _run(path)
    assert result.returncode == 0
    assert "Errno" not in result.stderr


def test_cli_directory_path_reports_the_specific_reason(tmp_path):
    result = _run(str(tmp_path))
    assert result.returncode == 2
    assert "Traceback" not in result.stderr
    assert "Errno" not in result.stderr
    if os.name == "nt":
        assert result.stderr == f"artifact is not readable (check file permissions): {tmp_path}\n"
    else:
        assert result.stderr == f"artifact path is a directory, not a file: {tmp_path}\n"


def test_cli_missing_file_reports_not_found(tmp_path):
    missing = tmp_path / "nope.json"
    result = _run(str(missing))
    assert result.returncode == 2
    assert "Errno" not in result.stderr
    assert result.stderr == f"artifact not found: {missing}\n"


def test_cli_broken_symlink_reports_the_dangling_target(tmp_path):
    link = tmp_path / "broken.json"
    try:
        link.symlink_to(tmp_path / "nonexistent.json")
    except OSError as _symlink_exc:
        pytest.skip(f"symlink not available on this platform: {_symlink_exc}")
    result = _run(str(link))
    assert result.returncode == 2
    assert result.stderr == f"artifact is a broken symlink (target does not exist): {link}\n"


def test_cli_oversized_int_literal_reports_clean_json_error(tmp_path):
    # json.load raises a plain ValueError (not JSONDecodeError) on an oversized int literal.
    path = tmp_path / "huge.json"
    path.write_text('{"repos": ' + "9" * 5000 + "}", encoding="utf-8")
    result = _run(str(path))
    assert result.returncode == 2
    assert "Traceback" not in result.stderr
    assert result.stderr.startswith(f"artifact is not valid JSON ({path}):")


def test_cli_non_object_artifact_reports_clean_error(tmp_path):
    path = tmp_path / "arr.json"
    path.write_text("[1, 2, 3]", encoding="utf-8")
    result = _run(str(path))
    assert result.returncode == 2
    assert result.stderr == f"artifact must be a JSON object: {path}\n"


@pytest.mark.skipif(
    os.name == "nt" or (hasattr(os, "geteuid") and os.geteuid() == 0),
    reason="POSIX permission bits are not enforced on Windows; root bypasses them too",
)
def test_cli_unreadable_file_reports_a_permission_hint(tmp_path):
    path = tmp_path / "artifact.json"
    path.write_text("{}", encoding="utf-8")
    os.chmod(path, 0)
    try:
        result = _run(str(path))
    finally:
        os.chmod(path, 0o644)
    assert result.returncode == 2
    assert result.stderr == f"artifact is not readable (check file permissions): {path}\n"


def test_load_artifact_symlink_loop_reports_a_loop(monkeypatch, tmp_path, capsys):
    path = str(tmp_path / "loop.json")

    def _raise(*args, **kwargs):
        raise OSError(errno.ELOOP, "Too many levels of symbolic links", path)

    monkeypatch.setattr("builtins.open", _raise)
    with pytest.raises(SystemExit) as exc:
        cli.load_artifact(path)
    assert exc.value.code == 2
    assert capsys.readouterr().err == f"artifact path is a symlink loop: {path}\n"


def test_load_artifact_other_oserror_keeps_the_generic_message(monkeypatch, tmp_path, capsys):
    path = str(tmp_path / "run.json")

    def _raise(*args, **kwargs):
        raise OSError(errno.EIO, "Input/output error", path)

    monkeypatch.setattr("builtins.open", _raise)
    with pytest.raises(SystemExit) as exc:
        cli.load_artifact(path)
    assert exc.value.code == 2
    err = capsys.readouterr().err
    assert err == f"cannot read artifact ({path}): Input/output error\n"
    assert err.count(path) == 1
