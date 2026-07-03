"""Tests for the concrete-decision step (agent/decider.py)."""

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from agent.decider import decide, normalize_version_bump  # noqa: E402


class _FakeLLM:
    def __init__(self, out):
        self._out = out

    def chat_json(self, system, user, stub=None):
        return self._out


def test_normalize_version_bump_accepts_canonical_levels():
    for level in ("major", "minor", "patch"):
        assert normalize_version_bump(level) == level
    assert normalize_version_bump("  MINOR ") == "minor"
    assert normalize_version_bump("PATCH") == "patch"


def test_normalize_version_bump_maps_nullish_and_unknown_to_none():
    assert normalize_version_bump(None) is None
    assert normalize_version_bump("") is None
    assert normalize_version_bump("none") is None
    assert normalize_version_bump("null") is None
    assert normalize_version_bump("n/a") is None
    assert normalize_version_bump("micro") is None
    for bad in (123, True, ["minor"], {"level": "patch"}):
        assert normalize_version_bump(bad) is None


def test_decide_normalizes_version_bump_from_llm_output():
    ctx = {"recent_commits": [{"subject": "init"}]}
    out = decide(ctx, {}, "should we cut a release?", _FakeLLM({"version_bump": "MINOR"}))
    assert out["version_bump"] == "minor"

    cleared = decide(ctx, {}, "no release", _FakeLLM({"version_bump": "none"}))
    assert cleared["version_bump"] is None

    junk = decide(ctx, {}, "decide", _FakeLLM({"version_bump": "yolo"}))
    assert junk["version_bump"] is None

    non_string = decide(ctx, {}, "decide", _FakeLLM({"version_bump": 2}))
    assert non_string["version_bump"] is None
