"""Contract tests for specs/085-benchmark-freeze — assert benchmark/freeze.py satisfies the
spec's EARS criteria: the _git wrapper's error contract, origin_url/file_at degradation, the
export_tree error surface, _safe_target resolution, the directory-mode rule, the exact git
argv sequences build_context issues, the exact context key set and record shapes (including
the date-less {"tag": ...} release records and the frozen_at.commit pass-through), README
probing, and the write_frozen composition. Literal expected values; offline, deterministic —
real throwaway git repos under tmp_path, with the branches real git cannot produce driven
through a stubbed subprocess.run.

Complements tests/test_freeze.py, which owns the policy-level tag filtering/ordering
(#107/#332), the extraction policy's modes, link skips, and traversal rejections (#173), the
git-archive failure message (#355), and the missing-git-binary translation (#1188) — none of
those cases are re-asserted here. parse_path_list is owned by spec 021 and not touched here.
"""

import io
import json
import os
import shutil
import subprocess
import sys
import tarfile

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import benchmark.freeze as freeze  # noqa: E402

needs_git = pytest.mark.skipif(shutil.which("git") is None, reason="git required")


def _run(repo, *args, env=None):
    subprocess.run(["git", "-C", repo, *args], check=True, env=env)


def _init_repo(path):
    os.makedirs(path, exist_ok=True)
    _run(path, "init", "-q")
    _run(path, "config", "user.email", "t@t")
    _run(path, "config", "user.name", "t")
    return str(path)


def _commit(repo, name, date_iso, message):
    with open(os.path.join(repo, name), "w", encoding="utf-8") as f:
        f.write(f"{message}\n")
    env = os.environ.copy()
    env.update({"GIT_AUTHOR_DATE": date_iso, "GIT_COMMITTER_DATE": date_iso})
    _run(repo, "add", "-A", env=env)
    _run(repo, "commit", "-q", "-m", message, env=env)


def _head(repo):
    return subprocess.run(["git", "-C", repo, "rev-parse", "HEAD"],
                          capture_output=True, text=True).stdout.strip()


@pytest.fixture
def repo(tmp_path):
    """Three commits on 2024-01-01..03; the middle subject carries literal tabs."""
    r = _init_repo(tmp_path / "mylib")
    _commit(r, "a.txt", "2024-01-01T12:00:00+00:00", "first")
    _commit(r, "b.txt", "2024-01-02T12:00:00+00:00", "second\twith\ttabs")
    _commit(r, "mylib.py", "2024-01-03T12:00:00+00:00", "third")
    return r


class _Proc:
    def __init__(self, stdout="", returncode=0, stderr=""):
        self.stdout = stdout
        self.returncode = returncode
        self.stderr = stderr


# --- Constants and defaults ---------------------------------------------------------------


def test_constants_and_defaults():
    assert freeze.CONTEXT_FILE == ".vanguarstew_context.json"
    assert freeze.README_PROBE_NAMES == (
        "README.md", "README.rst", "README.txt", "README", "docs/README.md",
    )
    # build_context(repo, commit, lookback=50); write_frozen(..., lookback=50, scrub=True)
    assert freeze.build_context.__defaults__ == (50,)
    assert freeze.write_frozen.__defaults__ == (50, True)


# --- Git wrapper (_git) -------------------------------------------------------------------


@needs_git
def test_git_wrapper_stdout_return_and_pinned_failure_message(repo):
    head = _head(repo)
    assert freeze._git(repo, "rev-parse", "HEAD") == head + "\n"
    with pytest.raises(RuntimeError, match=r"^git log deadbeef123 failed: fatal:") as ei:
        freeze._git(repo, "log", "deadbeef123")
    # The stderr is .strip()ped into the message: git stderr ends in a newline, so a message
    # that kept it would end in whitespace. Pin the stripped tail, not just the prefix.
    msg = str(ei.value)
    assert msg == msg.strip() and not msg.endswith("\n")
    # check=False: the same failing invocation returns its (empty) stdout without raising.
    assert freeze._git(repo, "log", "deadbeef123", check=False) == ""


# --- Origin remote (origin_url) -----------------------------------------------------------


@needs_git
def test_origin_url_exact_remote_and_empty_without_origin(repo):
    assert freeze.origin_url(repo) == ""  # no origin remote: silent empty, never a raise
    _run(repo, "remote", "add", "origin", "https://example.invalid/own/mylib.git")
    assert freeze.origin_url(repo) == "https://example.invalid/own/mylib.git"  # stripped


# --- File snapshot (file_at) --------------------------------------------------------------


@needs_git
def test_file_at_exact_content_and_silent_empty_degradation(repo):
    assert freeze.file_at(repo, "HEAD", "a.txt") == "first\n"
    assert freeze.file_at(repo, "HEAD", "missing.txt") == ""  # unknown path
    assert freeze.file_at(repo, "deadbeef123", "a.txt") == ""  # unknown commit


# --- Tree export (export_tree) ------------------------------------------------------------


def test_export_tree_zero_exit_empty_archive_guard(tmp_path, monkeypatch):
    # Real git never emits zero bytes with exit 0 — this defensive guard is only reachable
    # through a stubbed process. It must be a clean RuntimeError, not a tarfile.ReadError.
    monkeypatch.setattr(freeze.subprocess, "run",
                        lambda *a, **k: _Proc(stdout=b"", returncode=0, stderr=b""))
    with pytest.raises(RuntimeError, match=r"^git archive failed for HEAD: empty archive$"):
        freeze.export_tree("/nonexistent", "HEAD", str(tmp_path / "out"))


def test_export_tree_nonzero_exit_with_empty_stderr_omits_the_suffix(tmp_path, monkeypatch):
    # A non-zero exit whose stderr is empty: the ": {stderr}" suffix is dropped entirely,
    # not appended as a dangling ": ". Reachable only through a stubbed process.
    monkeypatch.setattr(freeze.subprocess, "run",
                        lambda *a, **k: _Proc(stdout=b"", returncode=1, stderr=b""))
    with pytest.raises(RuntimeError, match=r"^git archive failed for HEAD$") as ei:
        freeze.export_tree("/nonexistent", "HEAD", str(tmp_path / "out"))
    assert str(ei.value) == "git archive failed for HEAD"  # no trailing ": "


# --- Tar member resolution (_safe_target) -------------------------------------------------


def test_safe_target_normalizes_backslashes_dots_and_absolute_names(tmp_path):
    dest = str(tmp_path)
    sep = os.sep
    assert freeze._safe_target(dest, "sub\\file.txt") == dest + sep + "sub" + sep + "file.txt"
    assert freeze._safe_target(dest, "./a//b") == dest + sep + "a" + sep + "b"
    # An absolute member name is neutralized under dest, never the filesystem root.
    assert freeze._safe_target(dest, "/abs.txt") == dest + sep + "abs.txt"


def test_safe_target_rejects_traversal_and_empty_resolutions(tmp_path):
    dest = str(tmp_path)
    # Every traversal/empty resolution rejects with the "unsafe path in archive" message
    # specifically (not the residual "path escapes destination" one) — pinning the message
    # keeps the two distinct rejection reasons from being swapped.
    for bad in ("../x", "a/../b", "", "/", "."):
        with pytest.raises(tarfile.TarError, match=r"^unsafe path in archive: "):
            freeze._safe_target(dest, bad)


# --- Extraction policy (_safe_extractall) -------------------------------------------------


def test_safe_extractall_normalizes_explicit_directory_modes(tmp_path):
    # A directory member recorded 0o700 lands as 0o755: deterministic across archives.
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tf:
        info = tarfile.TarInfo(name="pkg")
        info.type = tarfile.DIRTYPE
        info.mode = 0o700
        tf.addfile(info)
    buf.seek(0)
    dest = str(tmp_path / "out")
    with tarfile.open(fileobj=buf, mode="r:") as tf:
        freeze._safe_extractall(tf, dest)
    assert (os.stat(os.path.join(dest, "pkg")).st_mode & 0o777) == 0o755


def test_safe_extractall_file_exec_bit_is_owner_execute_only(tmp_path):
    # Executability keys on the OWNER-execute bit (mode & 0o100), not any execute bit: a file
    # with only the group-execute bit set (0o010) lands 0o644, never 0o755.
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tf:
        exec_data = b"#!/bin/sh\n"
        exe = tarfile.TarInfo(name="run.sh")  # owner-execute set -> executable
        exe.mode = 0o755
        exe.size = len(exec_data)
        tf.addfile(exe, io.BytesIO(exec_data))
        grp_data = b"data\n"
        grp = tarfile.TarInfo(name="grp-only")  # only group-execute set -> NOT executable
        grp.mode = 0o010
        grp.size = len(grp_data)
        tf.addfile(grp, io.BytesIO(grp_data))
    buf.seek(0)
    dest = str(tmp_path / "out")
    with tarfile.open(fileobj=buf, mode="r:") as tf:
        freeze._safe_extractall(tf, dest)
    assert (os.stat(os.path.join(dest, "run.sh")).st_mode & 0o777) == 0o755
    assert (os.stat(os.path.join(dest, "grp-only")).st_mode & 0o777) == 0o644


# --- Context assembly (build_context): git calls ------------------------------------------


def test_build_context_exact_git_argv_sequence_and_degenerate_result(monkeypatch):
    calls = []

    def spy(argv, **kwargs):
        calls.append(list(argv))
        return _Proc(stdout="")

    monkeypatch.setattr(freeze.subprocess, "run", spy)
    ctx = freeze.build_context("/repo", "HEAD")
    assert calls == [
        ["git", "-C", "/repo", "log", "--pretty=format:%H%x09%cI%x09%s", "-n", "50", "HEAD"],
        ["git", "-C", "/repo", "show", "-s", "--format=%ct", "HEAD"],
        ["git", "-C", "/repo", "tag", "--merged", "HEAD", "--sort=creatordate",
         "--format=%(creatordate:unix)%09%(refname:strip=2)"],
        ["git", "-C", "/repo", "show", "HEAD:README.md"],
        ["git", "-C", "/repo", "show", "HEAD:README.rst"],
        ["git", "-C", "/repo", "show", "HEAD:README.txt"],
        ["git", "-C", "/repo", "show", "HEAD:README"],
        ["git", "-C", "/repo", "show", "HEAD:docs/README.md"],
    ]
    # Degenerate branch real git cannot produce for a valid commit: no parseable log lines.
    assert ctx["frozen_at"] == {"commit": "HEAD", "date": None}
    assert ctx["recent_commits"] == []


@needs_git
def test_build_context_raises_for_unknown_commit(repo):
    # The checked log call raises — never a partial context for a bad freeze point.
    with pytest.raises(RuntimeError, match="git log .* failed"):
        freeze.build_context(repo, "deadbeef123")


# --- Context assembly: record shapes ------------------------------------------------------


@needs_git
def test_context_exact_key_set_and_empty_placeholders(repo):
    ctx = freeze.build_context(repo, "HEAD")
    assert sorted(ctx.keys()) == [
        "_source", "frozen_at", "labels", "milestones", "open_issues", "open_prs",
        "readme_excerpt", "recent_commits", "releases",
    ]
    assert ctx["_source"] == "git-freeze"
    # Constant [] here: enrichment happens in benchmark/github_context.py, not this module.
    assert ctx["open_issues"] == []
    assert ctx["open_prs"] == []
    assert ctx["labels"] == []
    assert ctx["milestones"] == []
    assert ctx["readme_excerpt"] == ""  # no README committed in this fixture


@needs_git
def test_frozen_at_commit_is_callers_argument_truncated_not_resolved(repo):
    head = _head(repo)
    # As-built: the caller's argument is truncated, never resolved to a SHA.
    assert freeze.build_context(repo, "HEAD")["frozen_at"]["commit"] == "HEAD"
    frozen = freeze.build_context(repo, head)["frozen_at"]
    assert frozen["commit"] == head[:10]
    assert len(frozen["commit"]) == 10
    # The date is the freeze commit's own committer time (%cI; Z-suffix is git-build-dependent).
    assert frozen["date"] in ("2024-01-03T12:00:00Z", "2024-01-03T12:00:00+00:00")


@needs_git
def test_recent_commits_shape_order_lookback_and_tab_subjects(repo):
    commits = freeze.build_context(repo, "HEAD", lookback=2)["recent_commits"]
    assert len(commits) == 2  # lookback honored: 3 commits exist
    assert [c["subject"] for c in commits] == ["third", "second\twith\ttabs"]  # newest first
    for c in commits:
        assert sorted(c.keys()) == ["date", "sha", "subject"]
        assert len(c["sha"]) == 10


@needs_git
def test_release_records_are_tag_only_without_dates(tmp_path):
    # Headline as-built: a git-only release record carries exactly one key — no
    # published_at, no name — unlike the GitHub-API path's {tag, published_at} records.
    r = _init_repo(tmp_path / "tagged")
    _commit(r, "a.txt", "2024-01-01T12:00:00+00:00", "c1")
    env = os.environ.copy()
    env.update({"GIT_COMMITTER_DATE": "2024-01-01T12:00:00+00:00"})
    _run(r, "tag", "-a", "v1.0.0", "-m", "v1.0.0", env=env)
    releases = freeze.build_context(r, "HEAD")["releases"]
    assert releases == [{"tag": "v1.0.0"}]
    assert "published_at" not in releases[0] and "name" not in releases[0]


def test_tag_line_parsing_fails_open_on_nondigit_dates_and_skips_empty_names(monkeypatch):
    # Parse-level behavior around the spec-003 date filter, unreachable with real git output:
    # a non-numeric creatordate keeps the tag (fail-open), an empty refname is skipped, the
    # at-T boundary is kept, and after-T is dropped. T = 1704110400 (2024-01-01T12:00:00Z).
    def fake(argv, **kwargs):
        if "log" in argv:
            return _Proc("a" * 40 + "\t2024-01-01T12:00:00+00:00\tsubject\nmalformed-line\n")
        if "--format=%ct" in argv:
            return _Proc("1704110400\n")
        if "tag" in argv:
            return _Proc("notadigit\tkept-nondigit-ts\n"
                         "1704110400\tkept-at-boundary\n"
                         "1704110401\tdropped-after-T\n"
                         "1704000000\t\n")
        return _Proc("")

    monkeypatch.setattr(freeze.subprocess, "run", fake)
    ctx = freeze.build_context("/repo", "HEAD")
    assert ctx["releases"] == [{"tag": "kept-nondigit-ts"}, {"tag": "kept-at-boundary"}]
    # The malformed two-field log line was dropped; the well-formed one was parsed.
    assert ctx["recent_commits"] == [
        {"sha": "a" * 10, "date": "2024-01-01T12:00:00+00:00", "subject": "subject"},
    ]


def test_unparsable_frozen_ts_disables_the_filter_and_keeps_all_tags(monkeypatch):
    # When `%ct` itself is non-numeric, T is unknown: the comparison is disabled entirely
    # (frozen_at is None) and every tag is kept — fail-open, NOT fail-closed-to-drop-all.
    # A tag dated far in the future must survive precisely because T could not be resolved.
    def fake(argv, **kwargs):
        if "log" in argv:
            return _Proc("b" * 40 + "\t2024-01-01T12:00:00+00:00\tsubject\n")
        if "--format=%ct" in argv:
            return _Proc("not-a-timestamp\n")  # unparsable -> frozen_at is None
        if "tag" in argv:
            return _Proc("9999999999\tfuture-dated-tag\n1704110400\tpast-dated-tag\n")
        return _Proc("")

    monkeypatch.setattr(freeze.subprocess, "run", fake)
    ctx = freeze.build_context("/repo", "HEAD")
    assert ctx["releases"] == [{"tag": "future-dated-tag"}, {"tag": "past-dated-tag"}]


@needs_git
def test_readme_probe_skips_empty_files_and_caps_at_4000(tmp_path):
    # README.md exists but is EMPTY: the truthiness probe skips it and README.rst wins,
    # capped at exactly 4000 characters.
    r = _init_repo(tmp_path / "docs")
    with open(os.path.join(r, "README.md"), "w", encoding="utf-8") as f:
        f.write("")
    with open(os.path.join(r, "README.rst"), "w", encoding="utf-8") as f:
        f.write("R" * 5000)
    env = os.environ.copy()
    env.update({"GIT_AUTHOR_DATE": "2024-01-01T12:00:00+00:00",
                "GIT_COMMITTER_DATE": "2024-01-01T12:00:00+00:00"})
    _run(r, "add", "-A", env=env)
    _run(r, "commit", "-q", "-m", "seed", env=env)
    excerpt = freeze.build_context(r, "HEAD")["readme_excerpt"]
    assert excerpt == "R" * 4000
    assert len(excerpt) == 4000


@needs_git
def test_readme_probe_returns_the_first_non_empty_match_not_the_last(tmp_path):
    # Two non-empty READMEs, README.md earlier than README.rst in the probe order: the walk
    # stops at the FIRST non-empty content, so README.md wins — never the last match.
    r = _init_repo(tmp_path / "docs")
    with open(os.path.join(r, "README.md"), "w", encoding="utf-8") as f:
        f.write("first-readme")
    with open(os.path.join(r, "README.rst"), "w", encoding="utf-8") as f:
        f.write("second-readme")
    env = os.environ.copy()
    env.update({"GIT_AUTHOR_DATE": "2024-01-01T12:00:00+00:00",
                "GIT_COMMITTER_DATE": "2024-01-01T12:00:00+00:00"})
    _run(r, "add", "-A", env=env)
    _run(r, "commit", "-q", "-m", "seed", env=env)
    assert freeze.build_context(r, "HEAD")["readme_excerpt"] == "first-readme"


# --- Frozen write (write_frozen) ----------------------------------------------------------


@needs_git
def test_write_frozen_writes_scrubbed_context_inside_exported_tree(repo, tmp_path):
    dest = str(tmp_path / "frozen")
    returned = freeze.write_frozen(repo, _head(repo), dest)
    # The exported tree and the context file sit side by side, where the agent reads them.
    assert os.path.isfile(os.path.join(dest, "a.txt"))
    with open(os.path.join(dest, ".vanguarstew_context.json"), encoding="utf-8") as f:
        raw = f.read()
    assert json.loads(raw) == returned  # returns exactly the dict it wrote
    assert returned["_forward_signal_scrubbed"] is True  # scrub defaults on (#24)
    assert returned["_source"] == "git-freeze"
    assert raw.startswith('{\n "frozen_at":')  # indent=1, insertion order


@needs_git
def test_write_frozen_scrub_false_writes_raw_git_context(repo, tmp_path):
    dest = str(tmp_path / "raw")
    returned = freeze.write_frozen(repo, _head(repo), dest, scrub=False)
    assert "_forward_signal_scrubbed" not in returned
    assert returned["_source"] == "git-freeze"
    with open(os.path.join(dest, ".vanguarstew_context.json"), encoding="utf-8") as f:
        assert json.load(f) == returned
