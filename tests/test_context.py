"""Tests for agent-side context loading and its git-only fallback masking (#283).

The scored replay path masks forward references in free text before the agent sees them
(`benchmark.freeze.build_context` -> `scrub_context`). When `.vanguarstew_context.json` is
absent, `agent.context` falls back to git alone — and must still not leak `#N` back-references
in commit subjects or the README, per the knowable-at-T contract.
"""

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

from agent.context import _mask_forward_refs, load_context  # noqa: E402


def _git(repo, *args):
    subprocess.run(["git", "-C", repo, *args], check=True, capture_output=True, text=True)


def test_mask_forward_refs_only_touches_hash_digits():
    assert _mask_forward_refs("see #150 and Fixes #900") == "see #ref and Fixes #ref"
    # A '#' not followed by digits is ordinary prose, not a reference — leave it alone.
    assert _mask_forward_refs("# Heading, C# code, item # 5") == "# Heading, C# code, item # 5"
    assert _mask_forward_refs("") == ""
    assert _mask_forward_refs(None) == ""


@pytest.mark.skipif(shutil.which("git") is None, reason="git required")
def test_git_fallback_masks_forward_refs_in_subjects_and_readme():
    repo = tempfile.mkdtemp()
    try:
        _git(repo, "init", "-q")
        _git(repo, "config", "user.email", "t@t")
        _git(repo, "config", "user.name", "t")
        with open(os.path.join(repo, "README.md"), "w", encoding="utf-8") as f:
            f.write("Roadmap: see #900 for the plan.\n")
        _git(repo, "add", "-A")
        _git(repo, "commit", "-q", "-m", "Fix parser (part of #150)")

        ctx = load_context(repo)  # no .vanguarstew_context.json -> git-only fallback
        assert ctx["_source"] == "git"

        subject = ctx["recent_commits"][0]["subject"]
        assert "#150" not in subject and "#ref" in subject          # subject masked
        assert "#900" not in ctx["readme_excerpt"] and "#ref" in ctx["readme_excerpt"]
        assert "Roadmap" in ctx["readme_excerpt"]                    # substance preserved
    finally:
        shutil.rmtree(repo, ignore_errors=True)


def test_load_context_uses_frozen_file_verbatim_when_present():
    # When the harness-written context file exists it is already scrubbed; the fallback
    # masking must not apply to (or alter) it.
    d = tempfile.mkdtemp()
    try:
        payload = {"_source": "frozen", "recent_commits": [{"subject": "already scrubbed #ref"}]}
        with open(os.path.join(d, ".vanguarstew_context.json"), "w", encoding="utf-8") as f:
            json.dump(payload, f)
        ctx = load_context(d)
        assert ctx == payload  # returned verbatim, not rebuilt from git
    finally:
        shutil.rmtree(d, ignore_errors=True)
