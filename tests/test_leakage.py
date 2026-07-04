"""Tests for leakage defenses: forward-reference scrubbing and freeze-point selection."""

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import benchmark.taskgen as taskgen  # noqa: E402
from benchmark.leakage import scrub_context, strip_forward_refs  # noqa: E402


def test_strip_forward_refs_masks_refs_links_and_shas():
    text = ("Fixes #512 and closes #7; see "
            "https://github.com/o/r/pull/900 at commit 1a2b3c4d5e6f7a8b")
    out = strip_forward_refs(text)
    assert "#512" not in out and "#7" not in out and "#ref" in out
    assert "github.com" not in out and "<link>" in out
    assert "1a2b3c4d5e6f7a8b" not in out and "<sha>" in out


def test_strip_forward_refs_preserves_plain_numbers():
    # 0-9a-f matches bare digits too (0-9 is a subset) -- a plain count/stat/year
    # is not a SHA and must survive the scrub.
    text = "supports 2500000 requests per second, up from 1200000 last year"
    out = strip_forward_refs(text)
    assert "2500000" in out and "1200000" in out
    assert "<sha>" not in out


def test_strip_forward_refs_still_masks_hex_shas_among_plain_numbers():
    text = "supports 2500000 requests per second; see commit 1a2b3c4d5e6f7a8b"
    out = strip_forward_refs(text)
    assert "2500000" in out
    assert "1a2b3c4d5e6f7a8b" not in out and "<sha>" in out


def test_strip_forward_refs_preserves_bare_numeric_tokens_at_sha_length():
    text = "Supports 123456 requests/s, 1234567 active users, and 2500000 cached rows."
    out = strip_forward_refs(text)
    assert out == text
    assert "<sha>" not in out


def test_strip_forward_refs_masks_mixed_case_sha_like_tokens_only():
    text = "See AbC1234 and deadBEEF1234, but keep incident 1234567 visible."
    out = strip_forward_refs(text)
    assert "AbC1234" not in out and "deadBEEF1234" not in out
    assert out.count("<sha>") == 2
    assert "1234567" in out


def test_scrub_context_scrubs_nested_fields_only():
    ctx = {
        "readme_excerpt": "roadmap toward plugins; tracked in #101 after commit aBc1234; "
                          "supports 2500000 requests/s",
        "recent_commits": [{"sha": "x", "subject": "start work, part of #200 via deadBEEF"}],
        "open_issues": [{"number": 1, "title": "bug, dup of #300 after a1b2c3d4"}],
        "releases": [
            {"tag": "v1.0"},
            {"tag": "v1.1", "name": "Release v1.1 — fixes #512, see "
                                   "https://github.com/o/r/pull/900 at f00ba47"},
        ],
    }
    out = scrub_context(ctx)
    assert "#101" not in out["readme_excerpt"]
    assert "aBc1234" not in out["readme_excerpt"] and "<sha>" in out["readme_excerpt"]
    assert "2500000" in out["readme_excerpt"]  # numeric prose is intentionally preserved
    assert "#200" not in out["recent_commits"][0]["subject"]
    assert "deadBEEF" not in out["recent_commits"][0]["subject"]
    assert "#300" not in out["open_issues"][0]["title"]
    assert "a1b2c3d4" not in out["open_issues"][0]["title"]
    assert out["releases"][0] == {"tag": "v1.0"}  # tag-only entries unchanged
    name = out["releases"][1]["name"]
    assert "#512" not in name and "github.com" not in name and "#ref" in name and "<link>" in name
    assert "f00ba47" not in name and "<sha>" in name
    assert out["releases"][1]["tag"] == "v1.1"
    assert out["_forward_signal_scrubbed"] is True
    assert ctx.get("_forward_signal_scrubbed") is None  # original not mutated


def test_strip_forward_refs_preserves_surrounding_punctuation():
    # Trailing sentence punctuation must stay in the prose, not vanish into <link>.
    assert strip_forward_refs("see https://github.com/o/r/issues/5, next") == "see <link>, next"
    assert strip_forward_refs("see https://github.com/o/r/issues/5.") == "see <link>."
    assert strip_forward_refs("see https://github.com/o/r/pull/9; done") == "see <link>; done"
    assert strip_forward_refs("see https://github.com/o/r/pull/9!") == "see <link>!"


def test_strip_forward_refs_preserves_markdown_and_bracket_delimiters():
    # Parentheses, square brackets, and angle brackets around a link survive.
    assert strip_forward_refs("(https://github.com/o/r/issues/3)") == "(<link>)"
    assert strip_forward_refs("[x](https://github.com/o/r/pull/7)") == "[x](<link>)"
    # An inline #N backref inside the label is scrubbed too, independently.
    assert strip_forward_refs("[see #1](https://github.com/o/r/commit/abc1234)") == (
        "[see #ref](<link>)"
    )
    # Angle-bracketed: the enclosing brackets are preserved as a pair around the mask.
    assert strip_forward_refs("<https://github.com/o/r/issues/5>") == "<<link>>"


def test_strip_forward_refs_masks_query_strings_and_fragments():
    # Query strings and fragments are part of the URL and must be masked with it.
    for url in (
        "https://github.com/o/r/issues/5?foo=bar",
        "https://github.com/o/r/pull/9#discussion_r123",
        "https://github.com/o/r/commit/abc1234?diff=split",
        "https://github.com/o/r/compare/v1.0...v2.0",
    ):
        out = strip_forward_refs(f"see {url} now")
        assert "github.com" not in out
        assert "<link>" in out
        assert out.startswith("see ") and out.endswith(" now")  # prose intact


def test_strip_forward_refs_keeps_bare_owner_and_repo_urls():
    # A bare owner/repo URL carries no specific forward reference and must survive.
    for url in (
        "https://github.com/o/r",
        "https://github.com/o",
        "https://github.com/o/r/tree-sitter",   # a repo literally named tree-sitter
        "https://github.com/o/r/graphs",         # an insights tab, not a deep-link
        "https://github.com/o/r/issues",         # the issue list, not a specific issue
    ):
        assert strip_forward_refs(url) == url, url


def _fake_history(n):
    return [f"sha{i:03d}" for i in range(n)]


def test_recent_bias_selects_from_recent_window(monkeypatch):
    monkeypatch.setattr(taskgen, "linear_history", lambda repo: _fake_history(100))
    monkeypatch.setattr(taskgen, "revealed_window", lambda *a, **k: [])
    tasks = taskgen.generate_tasks("x", num_tasks=3, horizon=5, min_history=10, recent_bias=True)
    # recent window = last max(9,3)=9 usable indices; usable maxes at 94 (i+5<100)
    assert all(t["freeze_index"] >= 80 for t in tasks)
    assert len(tasks) == 3


def test_rotation_seed_is_deterministic(monkeypatch):
    monkeypatch.setattr(taskgen, "linear_history", lambda repo: _fake_history(100))
    monkeypatch.setattr(taskgen, "revealed_window", lambda *a, **k: [])
    a = taskgen.generate_tasks("x", num_tasks=4, horizon=5, rotation_seed=42)
    b = taskgen.generate_tasks("x", num_tasks=4, horizon=5, rotation_seed=42)
    c = taskgen.generate_tasks("x", num_tasks=4, horizon=5, rotation_seed=99)
    assert [t["freeze_index"] for t in a] == [t["freeze_index"] for t in b]
    assert [t["freeze_index"] for t in a] != [t["freeze_index"] for t in c]
