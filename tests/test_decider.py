"""Tests for the concrete-decision step, focused on the version_bump contract (#164)."""

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

os.environ["VANGUARSTEW_OFFLINE"] = "1"

from agent.decider import decide, normalize_version_bump  # noqa: E402


class _FakeLLM:
    """Returns a fixed decision dict, ignoring the prompt — to drive decide() in tests."""

    def __init__(self, out):
        self.offline = True
        self._out = out

    def chat_json(self, system, user, stub=None):
        return self._out


def test_normalize_version_bump_canonicalizes_near_misses():
    assert normalize_version_bump("major") == "major"
    assert normalize_version_bump("MINOR") == "minor"       # case
    assert normalize_version_bump(" patch ") == "patch"     # whitespace
    assert normalize_version_bump("bump major version") == "major"   # embedded in a phrase
    assert normalize_version_bump("MAJOR release") == "major"


def test_normalize_version_bump_rejects_non_levels():
    for value in ("none", "null", "", "1.2.0", "bump", "majorish", None, 3, ["minor"]):
        assert normalize_version_bump(value) is None


def test_decide_normalizes_version_bump_from_model():
    # The issue's repro: a near-miss level must be canonicalized in the returned decision.
    out = decide({}, {}, "cut a release?", _FakeLLM({"version_bump": "MINOR"}))
    assert out["version_bump"] == "minor"
    # A junk value collapses to None (no bump) rather than leaking through.
    out = decide({}, {}, "cut a release?", _FakeLLM({"version_bump": "soon"}))
    assert out["version_bump"] is None
    # A clean level is preserved; action still defaults.
    out = decide({}, {}, "cut a release?", _FakeLLM({"action": "release", "version_bump": "patch"}))
    assert out["version_bump"] == "patch" and out["action"] == "release"


def test_decide_handles_missing_version_bump_and_bad_output():
    # Missing field -> None (not KeyError).
    out = decide({}, {}, "triage?", _FakeLLM({"action": "triage"}))
    assert out["version_bump"] is None
    # Non-dict model output falls back to the stub, which normalizes to None.
    out = decide({}, {}, "plan?", _FakeLLM("not a dict"))
    assert out["version_bump"] is None and out["action"] == "plan"
