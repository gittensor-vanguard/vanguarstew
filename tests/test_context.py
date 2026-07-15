"""Tests for the agent-facing frozen-context view."""

import json
import os
import shutil
import subprocess
import sys
import tempfile

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import benchmark.github_context as gc  # noqa: E402
from agent.context import (  # noqa: E402
    _SHA,
    CONTEXT_FILE,
    README_PROBE_NAMES,
    _agent_context_list,
    _agent_issue_pr_list,
    _context_from_git,
    _looks_like_sha,
    _mask_forward_refs,
    context_for_agent,
    load_context,
    repo_layout,
)
from agent.decider import _render as render_decider_context  # noqa: E402
from agent.philosophy import _render as render_philosophy_context  # noqa: E402
from agent.planner import _render as render_planner_context  # noqa: E402
from benchmark.freeze import build_context  # noqa: E402
from benchmark.leakage import scrub_context  # noqa: E402


def test_context_for_agent_omits_unknown_issue_labels():
    ctx = {
        "open_issues": [{
            "number": 1,
            "title": "bug",
            "labels": [],
            "labels_as_of_t": False,
        }],
        "open_prs": [{
            "number": 2,
            "title": "fix bug",
            "labels": [],
            "labels_as_of_t": False,
        }],
    }
    out = context_for_agent(ctx)
    assert "labels" not in out["open_issues"][0]
    assert out["open_issues"][0]["labels_as_of_t"] is False
    assert "labels" not in out["open_prs"][0]
    assert out["open_prs"][0]["labels_as_of_t"] is False


def test_context_for_agent_omits_labels_when_flag_missing():
    # Older artifacts and hand-edited JSON may carry labels without labels_as_of_t — treat as
    # unknown history, not knowable-at-T labels (#773).
    ctx = {
        "open_issues": [{"number": 1, "title": "bug", "labels": ["bug", "priority"]}],
        "open_prs": [{"number": 2, "title": "fix", "labels": ["enhancement"]}],
    }
    out = context_for_agent(ctx)
    assert "labels" not in out["open_issues"][0]
    assert "labels_as_of_t" not in out["open_issues"][0]
    assert "labels" not in out["open_prs"][0]
    assert "labels_as_of_t" not in out["open_prs"][0]

    payload = json.loads(render_decider_context(ctx))
    assert "labels" not in payload["open_issues"][0]
    assert "labels" not in payload["open_prs"][0]


# --- #493: malformed context / issue-PR lists must not abort agent view ---------------

_MALFORMED_CONTEXTS = [42, 3.14, True, "not a dict"]
_MALFORMED_ISSUE_PR_LISTS = [42, 3.14, True, {"number": 1}, "not a list"]


def test_agent_issue_pr_list_accepts_only_real_lists():
    rows = [{"number": 1}]
    for bad in _MALFORMED_ISSUE_PR_LISTS:
        assert _agent_issue_pr_list(bad, "open_issues") == [], bad
    assert _agent_issue_pr_list(rows, "open_issues") == rows
    assert _agent_issue_pr_list(None, "open_prs") == []


def test_agent_context_list_coerces_other_list_fields():
    rows = [{"sha": "abc", "subject": "init"}]
    for bad in _MALFORMED_ISSUE_PR_LISTS:
        assert _agent_context_list(bad, "recent_commits") == [], bad
    assert _agent_context_list(rows, "recent_commits") == rows
    assert _agent_context_list(None, "labels") == []


def test_context_for_agent_survives_non_dict_context():
    for bad in _MALFORMED_CONTEXTS:
        assert context_for_agent(bad) == {}, bad


def test_context_for_agent_survives_non_list_issue_pr_fields():
    for bad in _MALFORMED_ISSUE_PR_LISTS:
        out = context_for_agent({"open_issues": bad, "open_prs": bad})
        assert out["open_issues"] == [], bad
        assert out["open_prs"] == [], bad


def test_context_for_agent_coerces_other_malformed_list_fields():
    for bad in _MALFORMED_ISSUE_PR_LISTS:
        out = context_for_agent({
            "recent_commits": bad,
            "releases": bad,
            "milestones": bad,
            "labels": bad,
        })
        assert out["recent_commits"] == [], bad
        assert out["releases"] == [], bad
        assert out["milestones"] == [], bad
        assert out["labels"] == [], bad


def test_context_for_agent_keeps_valid_other_list_fields():
    out = context_for_agent({
        "recent_commits": [{"sha": "1", "subject": "init"}],
        "releases": [{"tag": "v1.0"}],
        "milestones": [{"title": "v2"}],
        "labels": ["bug", "enhancement"],
    })
    assert out["recent_commits"][0]["sha"] == "1"
    assert out["releases"][0]["tag"] == "v1.0"
    assert out["milestones"][0]["title"] == "v2"
    assert out["labels"] == ["bug", "enhancement"]


def test_prompt_renderers_coerce_malformed_list_fields_to_empty():
    ctx = {
        "frozen_at": {"commit": "abc"},
        "recent_commits": 42,
        "open_issues": [],
        "open_prs": [],
        "labels": True,
        "milestones": {"title": "oops"},
        "releases": 3.14,
        "readme_excerpt": "",
    }
    for render in (render_philosophy_context, render_planner_context, render_decider_context):
        payload = json.loads(render(ctx))
        assert payload["recent_commits"] == []
        assert payload["releases"] == []
        assert payload["milestones"] == []
        assert payload["labels"] == []


def test_context_for_agent_passes_through_falsy_non_dict_rows():
    for junk in (0, None, False, ""):
        out = context_for_agent({"open_issues": [junk, {"number": 1, "labels_as_of_t": True}]})
        assert out["open_issues"][0] is junk
        assert out["open_issues"][1]["number"] == 1


def test_context_for_agent_survives_asymmetric_malformed_lists():
    out = context_for_agent({
        "open_issues": [{"number": 1, "labels_as_of_t": True}],
        "open_prs": 42,
    })
    assert out["open_issues"][0]["number"] == 1
    assert out["open_prs"] == []


def test_context_for_agent_logs_warning_for_non_dict_context(caplog):
    import logging

    with caplog.at_level(logging.WARNING, logger="agent.context"):
        assert context_for_agent(42) == {}
    assert any("context is int" in r.message for r in caplog.records)


def test_context_for_agent_logs_warning_for_non_list_field(caplog):
    import logging

    with caplog.at_level(logging.WARNING, logger="agent.context"):
        out = context_for_agent({"open_issues": 42})
    assert out["open_issues"] == []
    assert any("open_issues is int" in r.message for r in caplog.records)


def test_context_for_agent_logs_warning_for_non_dict_row_with_index(caplog):
    import logging

    with caplog.at_level(logging.WARNING, logger="agent.context"):
        out = context_for_agent({"open_prs": [0, {"number": 2, "labels_as_of_t": True}]})
    assert out["open_prs"][0] == 0
    assert out["open_prs"][1]["number"] == 2
    assert any("index 0" in r.message and "int" in r.message for r in caplog.records)


def test_context_for_agent_keeps_reconstructed_labels():
    ctx = {
        "open_issues": [{
            "number": 1,
            "title": "bug",
            "labels": ["bug"],
            "labels_as_of_t": True,
        }],
    }
    out = context_for_agent(ctx)
    assert out["open_issues"][0]["labels"] == ["bug"]
    assert out["open_issues"][0]["labels_as_of_t"] is True


def test_context_for_agent_clears_backlog_when_issues_truncated():
    ctx = {
        "_issues_truncated": True,
        "open_issues": [{"number": 1, "title": "partial backlog", "labels_as_of_t": True}],
        "open_prs": [{"number": 2, "title": "partial pr", "labels_as_of_t": True}],
    }
    out = context_for_agent(ctx)
    assert out["_issues_truncated"] is True
    assert out["open_issues"] == []
    assert out["open_prs"] == []


def test_context_for_agent_keeps_backlog_when_issues_truncated_is_not_boolean_true():
    issues = [{"number": 1, "title": "Memory leak under load", "labels_as_of_t": True}]
    prs = [{"number": 2, "title": "Fix parser edge case", "labels_as_of_t": True}]
    ctx = {"_issues_truncated": "false", "open_issues": issues, "open_prs": prs}
    out = context_for_agent(ctx)
    assert out["open_issues"] == issues
    assert out["open_prs"] == prs


def test_context_for_agent_keeps_milestones_and_releases_when_truncated_is_not_boolean_true():
    milestones = [{"title": "v1 milestone", "state": "open"}]
    releases = [{"tag": "v1.0.0", "name": "Initial release"}]
    ctx = {
        "_milestones_truncated": "false",
        "_releases_truncated": "false",
        "milestones": milestones,
        "releases": releases,
    }
    out = context_for_agent(ctx)
    assert out["milestones"] == milestones
    assert out["releases"] == releases


def test_context_for_agent_clears_milestones_and_releases_when_truncated():
    ctx = {
        "_milestones_truncated": True,
        "_releases_truncated": True,
        "milestones": [{"title": "partial milestone", "state": "open"}],
        "releases": [{"tag": "v9.9.9", "name": "partial release"}],
    }
    out = context_for_agent(ctx)
    assert out["milestones"] == []
    assert out["releases"] == []


def test_prompt_renderers_do_not_serialize_unknown_labels_as_empty_history():
    ctx = {
        "frozen_at": {"commit": "abc"},
        "recent_commits": [{"sha": "1", "subject": "init"}],
        "open_issues": [{
            "number": 1,
            "title": "bug",
            "labels": [],
            "labels_as_of_t": False,
        }],
        "open_prs": [{
            "number": 2,
            "title": "fix bug",
            "labels": [],
            "labels_as_of_t": False,
        }],
        "labels": [],
        "milestones": [],
        "releases": [],
        "readme_excerpt": "",
    }
    for render in (render_philosophy_context, render_planner_context, render_decider_context):
        payload = json.loads(render(ctx))
        assert "labels" not in payload["open_issues"][0]
        assert payload["open_issues"][0]["labels_as_of_t"] is False
        assert "labels" not in payload["open_prs"][0]
        assert payload["open_prs"][0]["labels_as_of_t"] is False


# --- git-only fallback (agent.context._context_from_git) --------------------------

def _git(repo, *args, date=None):
    env = dict(os.environ)
    if date:
        env["GIT_AUTHOR_DATE"] = env["GIT_COMMITTER_DATE"] = date
    subprocess.run(
        ["git", "-C", repo, *args], check=True,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=env,
    )


def _init_repo(repo):
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "t@t")
    _git(repo, "config", "user.name", "t")
    _git(repo, "checkout", "-q", "-b", "main")


def _write(repo, relpath, text="x\n"):
    full = os.path.join(repo, relpath)
    os.makedirs(os.path.dirname(full) or repo, exist_ok=True)
    with open(full, "w", encoding="utf-8") as f:
        f.write(text)


def _repo_with_commit():
    repo = tempfile.mkdtemp()
    _init_repo(repo)
    _write(repo, "f.txt")
    _git(repo, "add", "-A", date="2024-01-10T12:00:00+00:00")
    _git(repo, "commit", "-q", "-m", "c1", date="2024-01-10T12:00:00+00:00")
    return repo


@pytest.mark.skipif(shutil.which("git") is None, reason="git required")
@pytest.mark.parametrize("payload", [
    b'{"open_prs": [',            # truncated JSON (interrupted write)
    b"",                          # empty file
    b"\xff\xfe\x00\x01\x02\x80",  # binary / non-UTF-8 content
    b"not json at all",           # plain text
])
def test_load_context_falls_back_to_git_on_unreadable_file(payload, caplog):
    # A present-but-unreadable context file (truncated / empty / binary / non-JSON) must not
    # crash solve(): load_context rebuilds the knowable-at-T context from the frozen git
    # checkout instead, and logs loudly (with the byte size) so the degrade is never silent.
    import logging
    repo = _repo_with_commit()
    try:
        with open(os.path.join(repo, CONTEXT_FILE), "wb") as f:
            f.write(payload)
        with caplog.at_level(logging.WARNING, logger="agent.context"):
            ctx = load_context(repo)  # no exception
        assert ctx["_source"] == "git"
        assert ctx["frozen_at"]["commit"]
        assert any("unreadable" in r.message and "bytes" in r.message for r in caplog.records)
    finally:
        shutil.rmtree(repo, ignore_errors=True)


@pytest.mark.skipif(shutil.which("git") is None, reason="git required")
@pytest.mark.skipif(
    not hasattr(os, "geteuid") or os.geteuid() == 0,
    reason="root bypasses file permissions",
)
def test_load_context_falls_back_to_git_on_permission_denied():
    repo = _repo_with_commit()
    path = os.path.join(repo, CONTEXT_FILE)
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write('{"open_prs": []}')
        os.chmod(path, 0o000)  # unreadable -> PermissionError (an OSError) -> git fallback
        ctx = load_context(repo)
        assert ctx["_source"] == "git"
    finally:
        os.chmod(path, 0o644)
        shutil.rmtree(repo, ignore_errors=True)


def test_repo_layout_surfaces_dotfile_trees_and_top_level_files():
    # The objective anchor attributes a changed path to its top-level entry, so a dotfile tree
    # (`.github/workflows/ci.yml` -> `.github`) and a top-level file (`NEWS` -> `news`) are
    # modules a plan can name, exactly like a source package. The layout must therefore surface
    # BOTH -- filtering to non-dot directories would hide the only modules some repos ever
    # change. Freeze/VCS artifacts are not repo structure and stay out.
    repo = tempfile.mkdtemp()
    try:
        os.makedirs(os.path.join(repo, ".ci-workflows", "jobs"))
        os.makedirs(os.path.join(repo, "mylib"))
        os.makedirs(os.path.join(repo, ".git", "objects"))
        for name in ("CHANGES", "LICENSE", ".toolconfig.yaml", CONTEXT_FILE):
            _write(repo, name)
        _write(os.path.join(repo, ".ci-workflows", "jobs"), "build.yml")
        assert repo_layout(repo) == [
            ".ci-workflows/", ".toolconfig.yaml", "CHANGES", "LICENSE", "mylib/",
        ]
    finally:
        shutil.rmtree(repo, ignore_errors=True)


def test_repo_layout_degrades_to_empty_when_the_path_cannot_be_listed():
    # The layout is optional prompt context: an unusable repo_path must omit it, never raise
    # out of solve(). Covers a missing directory, a path that is a FILE (NotADirectoryError),
    # an unreadable directory (PermissionError), a NUL byte (ValueError, which never reaches
    # the OS call), and non-string / empty inputs.
    missing = os.path.join(tempfile.mkdtemp(), "nope")
    assert repo_layout(missing) == []
    handle, as_file = tempfile.mkstemp()
    os.close(handle)
    try:
        assert repo_layout(as_file) == []       # NotADirectoryError, not a crash
    finally:
        os.unlink(as_file)
    locked = tempfile.mkdtemp()
    os.chmod(locked, 0o000)
    try:
        if os.geteuid() != 0:                   # root ignores the mode bits entirely
            assert repo_layout(locked) == []    # PermissionError, not a crash
    finally:
        os.chmod(locked, 0o755)
        shutil.rmtree(locked, ignore_errors=True)
    assert repo_layout("/tmp/a\0b") == []       # ValueError, not a crash
    assert repo_layout("") == []
    assert repo_layout(None) == []
    assert repo_layout(["not", "a", "path"]) == []


def test_repo_layout_caps_the_entry_count():
    # A pathological repo root must not crowd the commit history out of the prompt. The cap is
    # applied BEFORE each entry is taken, so a zero/negative/non-int limit cannot yield one
    # entry off the end of the check.
    repo = tempfile.mkdtemp()
    try:
        for i in range(6):
            _write(repo, f"f{i}.txt")
        assert repo_layout(repo, limit=2) == ["f0.txt", "f1.txt"]
        assert repo_layout(repo, limit=0) == []          # a zero cap yields nothing, not f0
        assert len(repo_layout(repo, limit=-1)) == 6     # negative -> default, never one entry
        assert len(repo_layout(repo, limit=None)) == 6   # non-int -> default, not a TypeError
        assert len(repo_layout(repo)) == 6      # default limit leaves a normal repo intact
    finally:
        shutil.rmtree(repo, ignore_errors=True)


@pytest.mark.skipif(shutil.which("git") is None, reason="git required")
def test_load_context_derives_repo_layout_and_never_trusts_the_context_file():
    # `build_context` never emits `repo_layout`, so a value in the file could only come from a
    # hand-authored or tampered artifact. It must be overwritten by the real checkout listing,
    # or invented paths would reach the plan's `files` from untrusted JSON.
    repo = _repo_with_commit()
    try:
        payload = {"_source": "github-api", "repo_layout": ["invented/", "not-real.py"]}
        with open(os.path.join(repo, CONTEXT_FILE), "w", encoding="utf-8") as f:
            json.dump(payload, f)
        out = load_context(repo)
        assert out["repo_layout"] == ["f.txt"]           # derived from the checkout
        assert "invented/" not in out["repo_layout"]     # the tampered value is discarded
        assert out["_source"] == "github-api"            # the rest of the file still survives
    finally:
        shutil.rmtree(repo, ignore_errors=True)


@pytest.mark.skipif(shutil.which("git") is None, reason="git required")
def test_load_context_reads_a_valid_file_from_the_file_not_git():
    # Happy path: a well-formed context file's GitHub-derived content is returned as written,
    # and it is read from the FILE (its `_source` marker survives) rather than being rebuilt
    # from git. `repo_layout` is derived from the checkout and added on top.
    repo = _repo_with_commit()
    try:
        payload = {"_source": "github-api", "open_prs": [{"number": 1, "title": "x"}]}
        with open(os.path.join(repo, CONTEXT_FILE), "w", encoding="utf-8") as f:
            json.dump(payload, f)
        out = load_context(repo)
        assert {k: v for k, v in out.items() if k != "repo_layout"} == payload
        assert out["_source"] == "github-api"  # from the file, not the git rebuild ("git")
        assert out["repo_layout"] == ["f.txt"]  # .git and the freeze artifact stay out
    finally:
        shutil.rmtree(repo, ignore_errors=True)


@pytest.mark.skipif(shutil.which("git") is None, reason="git required")
@pytest.mark.parametrize("payload", ["[]", '"a string"', "7", "null"])
def test_load_context_passes_through_valid_json_that_is_not_an_object(payload):
    # A context file holding well-formed JSON that is not an object parses fine, so it never
    # reaches the JSONDecodeError fallback. Attaching the layout must not assume a dict and
    # `**`-explode a list/str/int (TypeError) -- the value passes through untouched, exactly as
    # before, and `context_for_agent` remains the guard that normalizes it to {}.
    repo = _repo_with_commit()
    try:
        with open(os.path.join(repo, CONTEXT_FILE), "w", encoding="utf-8") as f:
            f.write(payload)
        out = load_context(repo)  # no raise
        assert out == json.loads(payload)
        assert context_for_agent(out) == {}
    finally:
        shutil.rmtree(repo, ignore_errors=True)


@pytest.mark.skipif(shutil.which("git") is None, reason="git required")
def test_load_context_attaches_repo_layout_on_the_git_fallback_path_too():
    # The fallback rebuilds context from git when the file is absent; the plan still needs the
    # layout there, so both load paths must attach it.
    repo = _repo_with_commit()
    try:
        out = load_context(repo)
        assert out["_source"] == "git"
        assert out["repo_layout"] == ["f.txt"]
    finally:
        shutil.rmtree(repo, ignore_errors=True)


@pytest.mark.skipif(shutil.which("git") is None, reason="git required")
def test_context_from_git_sets_frozen_at_date():
    repo = tempfile.mkdtemp()
    try:
        _init_repo(repo)
        freeze_date = "2024-01-10T12:00:00+00:00"
        _write(repo, "f.txt")
        _git(repo, "add", "-A", date=freeze_date)
        _git(repo, "commit", "-q", "-m", "c1", date=freeze_date)

        ctx = _context_from_git(repo)
        assert ctx["frozen_at"]["commit"]
        assert ctx["frozen_at"]["date"]
        assert gc._frozen_at_date(ctx) is not None
        assert ctx["frozen_at"]["date"] == build_context(repo, "HEAD")["frozen_at"]["date"]
    finally:
        shutil.rmtree(repo, ignore_errors=True)


@pytest.mark.skipif(shutil.which("git") is None, reason="git required")
def test_context_from_git_sets_forward_signal_scrubbed_flag():
    # The fallback masks forward refs inline (_mask_forward_refs) exactly like
    # benchmark/leakage.py::scrub_context does for the frozen path, but never recorded that
    # provenance flag -- so a consumer reading the artifact would wrongly conclude it was
    # never scrubbed (#1307).
    repo = _repo_with_commit()
    try:
        ctx = _context_from_git(repo)
        assert ctx["_forward_signal_scrubbed"] is True
        # parity: scrub_context's own output carries the identical flag/value
        scrubbed = scrub_context(build_context(repo, "HEAD"))
        assert ctx["_forward_signal_scrubbed"] == scrubbed["_forward_signal_scrubbed"]
    finally:
        shutil.rmtree(repo, ignore_errors=True)


@pytest.mark.skipif(shutil.which("git") is None, reason="git required")
def test_context_from_git_raises_clean_error_on_empty_repo():
    # A plain `git rev-parse HEAD` on an empty repo exits 128 but prints the literal string
    # "HEAD" to stdout -- _git's check=False would otherwise silently accept that as a bogus
    # 4-char "commit id" (frozen_at.commit == "HEAD"). --verify --quiet yields empty stdout
    # instead, so the fallback can degrade to a clean RuntimeError, matching build_context's
    # own RuntimeError on the same input (#1307).
    repo = tempfile.mkdtemp()
    try:
        _init_repo(repo)  # init only -- deliberately zero commits
        with pytest.raises(RuntimeError):
            _context_from_git(repo)
        with pytest.raises(RuntimeError):
            build_context(repo, "HEAD")
    finally:
        shutil.rmtree(repo, ignore_errors=True)


@pytest.mark.skipif(shutil.which("git") is None, reason="git required")
def test_enrich_context_proceeds_for_git_fallback_context(monkeypatch):
    repo = tempfile.mkdtemp()
    try:
        _init_repo(repo)
        freeze_date = "2024-01-10T12:00:00+00:00"
        _write(repo, "f.txt")
        _git(repo, "add", "-A", date=freeze_date)
        _git(repo, "commit", "-q", "-m", "c1", date=freeze_date)

        def fake_fetch(*a, **k):
            return {
                "repo": "foo/bar",
                "open_issues": [],
                "open_prs": [],
                "milestones": [],
                "releases": [],
                "_source": "github-api",
            }

        monkeypatch.setattr(gc, "fetch_context_at", fake_fetch)
        monkeypatch.setattr("benchmark.freeze.origin_url", lambda p: "https://github.com/foo/bar")
        out = gc.enrich_context(_context_from_git(repo), repo)
        assert out.get("_github_enriched") is True
    finally:
        shutil.rmtree(repo, ignore_errors=True)


@pytest.mark.skipif(shutil.which("git") is None, reason="git required")
def test_context_from_git_excludes_tags_created_after_head():
    # A retroactive annotated tag on a commit already at T leaks a future release unless
    # filtered by tagger/creator date — must match benchmark/freeze.build_context (#749).
    repo = tempfile.mkdtemp()
    try:
        _init_repo(repo)
        freeze_date = "2024-01-10T12:00:00"
        _write(repo, "f.txt")
        _git(repo, "add", "-A", date=freeze_date)
        _git(repo, "commit", "-q", "-m", "c1", date=freeze_date)
        _git(repo, "tag", "-a", "v1.0.0", "-m", "rel", date=freeze_date)
        _git(repo, "tag", "-a", "v9.9.9", "-m", "future", date="2024-09-01T12:00:00")

        fallback = [r["tag"] for r in _context_from_git(repo)["releases"]]
        harness = [r["tag"] for r in build_context(repo, "HEAD")["releases"]]
        assert fallback == ["v1.0.0"]
        assert harness == ["v1.0.0"]
    finally:
        shutil.rmtree(repo, ignore_errors=True)


@pytest.mark.skipif(shutil.which("git") is None, reason="git required")
@pytest.mark.parametrize("readme_path,content", [
    ("README.txt", "Plain-text project overview.\n"),
    ("docs/README.md", "Monorepo docs overview.\n"),
])
def test_context_from_git_readme_probe_matches_build_context(readme_path, content):
    # Both git-only context builders must search the same README filenames so philosophy/plan
    # prompts see the same excerpt whether context came from freeze or the agent fallback.
    assert readme_path in README_PROBE_NAMES
    repo = tempfile.mkdtemp()
    try:
        _init_repo(repo)
        freeze_date = "2024-01-10T12:00:00+00:00"
        _write(repo, readme_path, content)
        _write(repo, "f.txt")
        _git(repo, "add", "-A", date=freeze_date)
        _git(repo, "commit", "-q", "-m", "c1", date=freeze_date)

        fallback = _context_from_git(repo)["readme_excerpt"]
        harness = build_context(repo, "HEAD")["readme_excerpt"]
        assert fallback == harness
        assert content.strip() in fallback
    finally:
        shutil.rmtree(repo, ignore_errors=True)


@pytest.mark.skipif(shutil.which("git") is None, reason="git required")
@pytest.mark.parametrize("files,expected", [
    # Load-bearing: an empty higher-priority README must not shadow a populated lower-priority
    # one. build_context skips the empty file (truthy check) and surfaces README.rst; the
    # fallback must too, or the two context paths diverge for the same repo.
    ({"README.md": "", "README.rst": "Real overview.\n"}, "Real overview.\n"),
    # Whitespace-only content is still content -- both surface it verbatim, so the fix mirrors
    # the truthy check exactly and never adds a stricter .strip() (which would re-diverge).
    ({"README.md": "  \n"}, "  \n"),
    # Every probe file empty -> both yield "" without crashing or defaulting to a stale file.
    ({"README.md": "", "docs/README.md": ""}, ""),
])
def test_context_from_git_readme_probe_skips_empty_higher_priority_file(files, expected):
    # build_context (benchmark/freeze.py) reads a missing and an empty file alike (git show ->
    # ""), so an empty higher-priority README falls through to the next probe name. The git-only
    # fallback stopped at the first *existing* file, surfacing "" where freeze surfaced the real
    # lower-priority README -- a path-dependent excerpt that skews philosophy/plan/scoring inputs
    # for the same repo. Both builders must agree (the #916/#937 alignment invariant).
    repo = tempfile.mkdtemp()
    try:
        _init_repo(repo)
        for path, text in files.items():
            _write(repo, path, text)
        _write(repo, "f.txt")
        _git(repo, "add", "-A")
        _git(repo, "commit", "-q", "-m", "c1")

        fallback = _context_from_git(repo)["readme_excerpt"]
        harness = build_context(repo, "HEAD")["readme_excerpt"]
        assert fallback == harness     # the two git-only context paths never diverge
        assert fallback == expected
    finally:
        shutil.rmtree(repo, ignore_errors=True)


@pytest.mark.skipif(shutil.which("git") is None, reason="git required")
def test_context_from_git_excludes_tags_unreachable_from_head():
    # A tag that exists only on an unmerged branch isn't an ancestor of HEAD, so it wasn't
    # knowable at T -- the fallback context must not surface it as a "release".
    repo = tempfile.mkdtemp()
    try:
        _init_repo(repo)
        _write(repo, "base.txt")
        _git(repo, "add", "-A")
        _git(repo, "commit", "-q", "-m", "base")
        _git(repo, "tag", "v1.0")

        _git(repo, "checkout", "-q", "-b", "unmerged-branch")
        _write(repo, "side.txt")
        _git(repo, "add", "-A")
        _git(repo, "commit", "-q", "-m", "side work")
        _git(repo, "tag", "v2.0-unreachable")
        _git(repo, "checkout", "-q", "main")

        ctx = _context_from_git(repo)
        assert [r["tag"] for r in ctx["releases"]] == ["v1.0"]
    finally:
        shutil.rmtree(repo, ignore_errors=True)


# --- git-only fallback forward-reference masking (#283) ----------------------------

def test_mask_forward_refs_only_touches_hash_digits():
    assert _mask_forward_refs("see #150 and Fixes #900") == "see #ref and Fixes #ref"
    # A '#' not followed by digits is ordinary prose, not a reference — leave it alone.
    assert _mask_forward_refs("# Heading, C# code, item # 5") == "# Heading, C# code, item # 5"
    assert _mask_forward_refs("") == ""
    assert _mask_forward_refs(None) == ""


def test_mask_forward_refs_tolerates_non_string_input():
    assert _mask_forward_refs(["see #900"]) == ""
    assert _mask_forward_refs(42) == ""
    assert _mask_forward_refs({"title": "Fix #900"}) == ""


def test_mask_forward_refs_masks_github_links_and_shas():
    text = ("Fixes #512; see https://github.com/o/r/pull/900 at commit 1a2b3c4d5e6f7a8b")
    out = _mask_forward_refs(text)
    assert "#512" not in out and "#ref" in out
    assert "github.com" not in out and "<link>" in out
    assert "1a2b3c4d5e6f7a8b" not in out and "<sha>" in out


def test_mask_forward_refs_masks_scheme_less_github_links():
    # A scheme-less github.com deep-link is still a forward-reference and must be masked (regression
    # for #996); a look-alike host must not be, and an explicit-scheme link keeps working.
    assert _mask_forward_refs("see github.com/o/r/pull/900 now") == "see <link> now"
    assert _mask_forward_refs("www.github.com/o/r/issues/512") == "<link>"
    assert "<link>" in _mask_forward_refs("https://github.com/o/r/commit/abcd123")
    assert _mask_forward_refs("visit notgithub.com/o/r/pull/900") == "visit notgithub.com/o/r/pull/900"


def test_mask_forward_refs_preserves_plain_numbers():
    text = "supports 2500000 requests per second, up from 1200000 last year"
    out = _mask_forward_refs(text)
    assert out == text
    assert "<sha>" not in out


def test_mask_forward_refs_masks_full_sha256_hash():
    # Git supports the SHA-256 object format; a full 64-char hash referencing a future commit
    # is as much a forward-reference leak as a 40-char SHA-1 and must be masked too.
    sha256 = "abc123" + "0" * 58  # 64 hex chars, contains a hex letter
    assert len(sha256) == 64
    assert _SHA.fullmatch(sha256) is not None
    assert _looks_like_sha(sha256) is True
    out = _mask_forward_refs(f"regressed by commit {sha256} upstream")
    assert sha256 not in out and "<sha>" in out
    assert _mask_forward_refs("see " + "a" * 40) == "see <sha>"
    assert _mask_forward_refs("see " + "a" * 7) == "see <sha>"


def test_mask_forward_refs_leaves_non_hash_length_hex_runs_untouched():
    # Only real hash lengths (7-40 SHA-1, exactly 64 SHA-256 with a hex letter) are masked;
    # 41-63 char hex runs are not valid full hashes, and a 64-char all-numeric token is
    # excluded by the 64-char regex branch (not merely deferred to _looks_like_sha).
    hex41 = "a" * 41
    hex63 = "b" * 63
    num64 = "1" * 64
    assert _SHA.fullmatch(hex41) is None
    assert _SHA.fullmatch(hex63) is None
    assert _SHA.fullmatch(num64) is None
    assert _looks_like_sha(num64) is False
    out = _mask_forward_refs(f"blob {hex41} and {hex63} and count {num64}")
    assert hex41 in out and hex63 in out and num64 in out
    assert "<sha>" not in out


def test_looks_like_sha_preserves_numeric_tokens_and_masks_real_hashes():
    # Mirror the boundary contract exercised for benchmark/leakage.py (spec 003).
    assert _looks_like_sha("1a2b3c4") is True
    assert _looks_like_sha("deadbeef1234") is True
    assert _looks_like_sha("1234567") is False
    assert _looks_like_sha("2024") is False
    assert _looks_like_sha("a1b2c") is False           # 5 chars — below minimum
    assert _looks_like_sha("a" * 41) is False          # 41 chars — not a real hash length
    assert _looks_like_sha("b" * 63) is False          # 63 chars
    assert _looks_like_sha("c" * 65) is False          # 65 chars
    assert _looks_like_sha("abc123" + "0" * 58) is True   # 64-char SHA-256
    assert _looks_like_sha("1" * 64) is False             # 64-char all-numeric


@pytest.mark.skipif(shutil.which("git") is None, reason="git required")
def test_context_from_git_masks_sha256_in_subjects():
    # SHA-256 object hashes (64 hex chars) must be scrubbed in the git-only path, not just SHA-1.
    repo = tempfile.mkdtemp()
    try:
        _init_repo(repo)
        sha256 = "abc123" + "0" * 58
        _git(repo, "commit", "-q", "--allow-empty", "-m", f"Fix parser (regressed by {sha256})")
        ctx = _context_from_git(repo)
        subject = ctx["recent_commits"][0]["subject"]
        assert sha256 not in subject and "<sha>" in subject
    finally:
        shutil.rmtree(repo, ignore_errors=True)


@pytest.mark.skipif(shutil.which("git") is None, reason="git required")
def test_context_from_git_masks_github_links_in_subjects_and_readme():
    repo = tempfile.mkdtemp()
    try:
        _init_repo(repo)
        _write(
            repo,
            "README.md",
            "Roadmap: see https://github.com/o/r/pull/900 for the plan.\n",
        )
        _git(repo, "add", "-A")
        _git(repo, "commit", "-q", "-m", "Fix parser (part of #150, commit deadBEEF1234)")

        ctx = _context_from_git(repo)
        subject = ctx["recent_commits"][0]["subject"]
        assert "#150" not in subject and "#ref" in subject
        assert "deadBEEF1234" not in subject and "<sha>" in subject
        readme = ctx["readme_excerpt"]
        assert "#900" not in readme and "github.com/o/r/pull/900" not in readme
        assert "<link>" in readme
        assert "Roadmap" in readme
    finally:
        shutil.rmtree(repo, ignore_errors=True)


@pytest.mark.skipif(shutil.which("git") is None, reason="git required")
def test_context_from_git_masks_forward_refs_in_subjects_and_readme():
    # The scored path scrubs #N back-references from subjects/README before the agent sees
    # them; the git-only fallback must do the same or it leaks where the repo went next.
    repo = tempfile.mkdtemp()
    try:
        _init_repo(repo)
        _write(repo, "README.md", "Roadmap: see #900 for the plan.\n")
        _git(repo, "add", "-A")
        _git(repo, "commit", "-q", "-m", "Fix parser (part of #150)")

        ctx = _context_from_git(repo)
        subject = ctx["recent_commits"][0]["subject"]
        assert "#150" not in subject and "#ref" in subject
        assert "#900" not in ctx["readme_excerpt"] and "#ref" in ctx["readme_excerpt"]
        assert "Roadmap" in ctx["readme_excerpt"]           # substantive prose preserved
    finally:
        shutil.rmtree(repo, ignore_errors=True)
