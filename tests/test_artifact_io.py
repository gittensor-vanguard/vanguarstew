"""Tests for the shared scripts.artifact_io.load_artifact helper."""

from __future__ import annotations

import errno
import json
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from scripts.artifact_io import load_artifact  # noqa: E402


def test_load_artifact_round_trip(tmp_path):
    path = tmp_path / "run.json"
    payload = {"composite_mean": 0.7, "scored_repos": 2}
    path.write_text(json.dumps(payload), encoding="utf-8")
    assert load_artifact(str(path)) == payload


def test_missing_file_exits_two(tmp_path, capsys):
    missing = tmp_path / "does-not-exist.json"
    with pytest.raises(SystemExit) as excinfo:
        load_artifact(str(missing))
    assert excinfo.value.code == 2
    err = capsys.readouterr().err
    assert err == f"artifact not found: {missing}\n"
    assert "Traceback" not in err


def test_broken_symlink_reports_dangling_target(tmp_path, capsys):
    link = tmp_path / "broken.json"
    try:
        link.symlink_to(tmp_path / "nonexistent.json")
    except OSError as exc:
        pytest.skip(f"symlink not available on this platform: {exc}")
    with pytest.raises(SystemExit) as excinfo:
        load_artifact(str(link))
    assert excinfo.value.code == 2
    assert capsys.readouterr().err == (
        f"artifact is a broken symlink (target does not exist): {link}\n"
    )


def test_symlink_loop_exits_two(monkeypatch, tmp_path, capsys):
    path = str(tmp_path / "loop.json")

    def _raise(*args, **kwargs):
        raise OSError(errno.ELOOP, "Too many levels of symbolic links", path)

    monkeypatch.setattr("builtins.open", _raise)
    with pytest.raises(SystemExit) as excinfo:
        load_artifact(path)
    assert excinfo.value.code == 2
    err = capsys.readouterr().err
    assert err == f"artifact path is a symlink loop: {path}\n"
    assert "Traceback" not in err


def test_directory_path_exits_two(tmp_path, capsys):
    with pytest.raises(SystemExit) as excinfo:
        load_artifact(str(tmp_path))
    assert excinfo.value.code == 2
    err = capsys.readouterr().err
    assert "directory" in err or "not readable" in err
    assert "Traceback" not in err


def test_unreadable_file_exits_two(tmp_path, capsys):
    path = tmp_path / "locked.json"
    path.write_text("{}", encoding="utf-8")
    os.chmod(path, 0)
    if os.access(str(path), os.R_OK):
        os.chmod(path, 0o600)
        pytest.skip("file is readable despite chmod 0 (running as root / Windows?)")
    try:
        with pytest.raises(SystemExit) as excinfo:
            load_artifact(str(path))
        assert excinfo.value.code == 2
        assert "not readable" in capsys.readouterr().err
    finally:
        os.chmod(path, 0o600)


def test_not_a_directory_error_exits_two(monkeypatch, tmp_path, capsys):
    path = str(tmp_path / "nested" / "run.json")

    def _raise(*args, **kwargs):
        raise NotADirectoryError(20, "Not a directory", path)

    monkeypatch.setattr("builtins.open", _raise)
    with pytest.raises(SystemExit) as excinfo:
        load_artifact(path)
    assert excinfo.value.code == 2
    err = capsys.readouterr().err
    assert "parent component is not a directory" in err


def test_other_oserror_reports_cleanly(monkeypatch, tmp_path, capsys):
    path = str(tmp_path / "run.json")

    def _raise(*args, **kwargs):
        raise OSError(errno.EIO, "Input/output error", path)

    monkeypatch.setattr("builtins.open", _raise)
    with pytest.raises(SystemExit) as excinfo:
        load_artifact(path)
    assert excinfo.value.code == 2
    err = capsys.readouterr().err
    assert "Traceback" not in err
    assert err.startswith(f"cannot read artifact ({path}):")


def test_invalid_json_exits_two(tmp_path, capsys):
    path = tmp_path / "bad.json"
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(SystemExit) as excinfo:
        load_artifact(str(path))
    assert excinfo.value.code == 2
    assert "not valid JSON" in capsys.readouterr().err


def test_non_object_json_exits_two(tmp_path, capsys):
    path = tmp_path / "list.json"
    path.write_text("[1, 2, 3]", encoding="utf-8")
    with pytest.raises(SystemExit) as excinfo:
        load_artifact(str(path))
    assert excinfo.value.code == 2
    assert "JSON object" in capsys.readouterr().err


def test_non_utf8_exits_two(tmp_path, capsys):
    path = tmp_path / "bin.json"
    path.write_bytes(b"\xff\xfe{not utf-8")
    with pytest.raises(SystemExit) as excinfo:
        load_artifact(str(path))
    assert excinfo.value.code == 2
    err = capsys.readouterr().err
    assert "UTF-8" in err or "not valid JSON" in err


def test_migrated_clis_reexport_shared_loader():
    from scripts import acceptance, leaderboard, promotion, regression, repeatability, report
    from scripts.artifact_io import load_artifact as shared

    for mod in (acceptance, promotion, regression, repeatability, leaderboard, report):
        assert mod.load_artifact is shared
