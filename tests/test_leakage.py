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


def test_scrub_context_scrubs_nested_fields_only():
    ctx = {
        "readme_excerpt": "roadmap toward plugins; tracked in #101",
        "recent_commits": [{"sha": "x", "subject": "start work, part of #200"}],
        "open_issues": [{"number": 1, "title": "bug, dup of #300"}],
        "releases": [
            {"tag": "v1.0"},
            {"tag": "v1.1", "name": "Release v1.1 — fixes #512, see https://github.com/o/r/pull/900"},
        ],
    }
    out = scrub_context(ctx)
    assert "#101" not in out["readme_excerpt"]
    assert "#200" not in out["recent_commits"][0]["subject"]
    assert "#300" not in out["open_issues"][0]["title"]
    assert out["releases"][0] == {"tag": "v1.0"}  # tag-only entries unchanged
    name = out["releases"][1]["name"]
    assert "#512" not in name and "github.com" not in name and "#ref" in name and "<link>" in name
    assert out["releases"][1]["tag"] == "v1.1"
    assert out["_forward_signal_scrubbed"] is True
    assert ctx.get("_forward_signal_scrubbed") is None  # original not mutated


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
