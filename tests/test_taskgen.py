"""Tests for replay task generation (benchmark/taskgen.py)."""

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import benchmark.taskgen as taskgen  # noqa: E402


def _fake_git_factory(files_output):
    """A _git stub: the subject for a `log` call, `files_output` for a `show` call."""
    def _fake_git(repo, *args, **kwargs):
        if args and args[0] == "log":
            return "feat: add thing"
        if args and args[0] == "show":
            return files_output
        return ""
    return _fake_git


def test_revealed_window_keeps_paths_with_spaces_intact(monkeypatch):
    # git show --name-only --pretty=format: emits a leading blank line then one path per line;
    # a path may contain spaces, which str.split() would have shattered into bogus entries.
    monkeypatch.setattr(taskgen, "_git", _fake_git_factory("\nsrc/my module.py\npkg/util.py\n"))
    win = taskgen.revealed_window("repo", ["a" * 40, "b" * 40], idx=0, n=1)
    assert len(win) == 1
    assert win[0]["sha"] == "b" * 10
    assert win[0]["subject"] == "feat: add thing"
    assert win[0]["files"] == ["src/my module.py", "pkg/util.py"]


def test_revealed_window_drops_blank_lines_and_caps_at_20(monkeypatch):
    paths = "\n".join(f"dir/file{i}.py" for i in range(30))
    monkeypatch.setattr(taskgen, "_git", _fake_git_factory("\n\n" + paths + "\n"))
    win = taskgen.revealed_window("repo", ["a" * 40, "b" * 40], idx=0, n=1)
    files = win[0]["files"]
    assert "" not in files
    assert len(files) == 20
    assert files[0] == "dir/file0.py"
