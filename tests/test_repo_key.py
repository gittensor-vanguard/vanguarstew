"""Tests for shared per-repo row identity (benchmark.repo_key)."""

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from benchmark.repo_key import repo_key  # noqa: E402


def test_repo_key_prefers_repo_path_then_url_then_repo_then_name():
    assert repo_key({"repo_path": "/a", "url": "u", "repo": "r", "name": "n"}) == "/a"
    assert repo_key({"url": "https://example.com/r", "repo": "alpha", "name": "beta"}) == (
        "https://example.com/r"
    )
    assert repo_key({"repo": "alpha", "name": "beta"}) == "alpha"
    assert repo_key({"name": "beta"}) == "beta"


def test_repo_key_includes_repo_name_in_precedence():
    assert repo_key({"repo_name": "display", "freeze_commit": "abc123def456"}) == "display"
    assert repo_key({"repo": "canonical", "repo_name": "display"}) == "canonical"


def test_repo_key_falls_back_to_freeze_commit_prefix():
    assert repo_key({"freeze_commit": "abc123def456"}) == "abc123def4"
    assert repo_key({"freeze_commit": "deadbeef1234567890"}) == "deadbeef12"


def test_repo_key_explicit_null_freeze_commit_uses_keys_repr():
    assert repo_key({"freeze_commit": None}) == repr(sorted(["freeze_commit"]))


def test_repo_key_empty_entry_uses_empty_keys_repr():
    assert repo_key({}) == repr([])


def test_all_consumers_import_shared_repo_key():
    from benchmark.comparability import _repo_key as comparability_key
    from benchmark.freeze_digest import _repo_key as freeze_digest_key
    from scripts.compare_eval import _repo_key as compare_eval_key

    row = {"repo_name": "my-repo", "tasks": 1}
    assert comparability_key(row) == "my-repo"
    assert freeze_digest_key(row) == "my-repo"
    assert compare_eval_key(row) == "my-repo"
