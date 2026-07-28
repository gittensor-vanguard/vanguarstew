"""Tests for freeze digest extraction and CLI (deterministic, offline)."""

import errno
import json
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from benchmark.freeze_digest import freeze_digest, freeze_digest_headline  # noqa: E402
from scripts import freeze_digest as cli  # noqa: E402


def _row(repo, freeze="abc123def456"):
    return {"repo": repo, "freeze_commit": freeze, "tasks": 3}


def test_multi_repo_digest_is_sorted():
    art = {"per_repo": [_row("b"), _row("a")], "composite_mean": 0.5}
    out = freeze_digest(art)
    assert out["kind"] == "multi"
    assert out["count"] == 2
    assert [e["repo"] for e in out["entries"]] == ["a", "b"]


def test_generalization_includes_partition():
    art = {
        "tuned": {"per_repo": [_row("t1")]},
        "held_out": {"per_repo": [_row("h1")]},
        "generalization_gap": 0.1,
    }
    out = freeze_digest(art)
    assert out["count"] == 2
    assert out["entries"][0]["partition"] == "held_out"


def test_single_repo_has_empty_entries():
    out = freeze_digest({"composite_mean": 0.5, "tasks": 3})
    assert out["kind"] == "single"
    assert out["entries"] == []


def test_malformed_per_repo_row_skipped():
    art = {"per_repo": ["bad", _row("ok")], "composite_mean": 0.5}
    out = freeze_digest(art)
    assert out["count"] == 1


def test_headline():
    out = freeze_digest({"per_repo": [_row("a")], "composite_mean": 0.5})
    assert "1 entry" in freeze_digest_headline(out)


@pytest.fixture
def tmp_artifact(tmp_path):
    def write(payload):
        path = tmp_path / "run.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        return str(path)
    return write


def test_cli(tmp_artifact, capsys):
    path = tmp_artifact({"per_repo": [_row("a")], "composite_mean": 0.5})
    assert cli.run([path]) == 0
    body = json.loads(capsys.readouterr().out)
    assert body["count"] == 1


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
