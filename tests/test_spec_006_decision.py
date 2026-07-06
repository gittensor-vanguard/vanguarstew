"""Contract tests for specs/006-agent-decision — assert decide() and its normalizers satisfy the
spec: canonical action mapping (synonym/non-string/unknown → plan), label/reviewer/patch/bump
coercion, and a fixed-shape decision over malformed model output. Deterministic, offline.
"""

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from agent.decider import (  # noqa: E402
    VALID_ACTIONS,
    _normalize_action,
    _normalize_labels,
    _normalize_reviewer,
    _normalize_version_bump,
    decide,
)

_KEYS = {"action", "labels", "reviewer", "version_bump", "patch", "rationale"}


# --- Field normalization --------------------------------------------------------------------

def test_action_maps_synonyms_and_defaults_to_plan():
    for act in VALID_ACTIONS:
        assert _normalize_action(act) == act
    assert _normalize_action("assign reviewer") == "assign-reviewer"
    assert _normalize_action("assign_reviewer") == "assign-reviewer"
    assert _normalize_action("MERGE") == "merge"
    assert _normalize_action("frobnicate") == "plan"      # unknown → plan
    assert _normalize_action(["merge"]) == "plan"         # non-string → plan
    assert _normalize_action(None) == "plan"


def test_labels_coerce_to_list_of_str():
    assert _normalize_labels("bug") == ["bug"]
    assert _normalize_labels(["a", None, "", 7]) == ["a", "7"]
    assert _normalize_labels(None) == []
    assert _normalize_labels(42) == []


def test_reviewer_and_bump_coercion():
    assert _normalize_reviewer("  alice ") == "alice"
    assert _normalize_reviewer("") is None
    assert _normalize_reviewer(None) is None
    assert _normalize_version_bump("Major") == "major"
    assert _normalize_version_bump("patch") == "patch"
    assert _normalize_version_bump("huge") is None        # unknown → None
    assert _normalize_version_bump(None) is None
    assert _normalize_version_bump(3) is None              # non-string → None


# --- End-to-end fixed shape over malformed model output -------------------------------------

class _MalformedLLM:
    offline = False

    def chat_json(self, system, user, stub=None):
        return {
            "action": "assign reviewer",     # synonym
            "labels": "bug",                  # bare string
            "reviewer": "   ",                # blank → None
            "version_bump": "MINOR",          # miscased
            "patch": "",                      # blank → None
            "rationale": None,                # None → ""
            "junk": object(),                 # ignored
        }


def test_decide_returns_fixed_shape_and_normalizes_every_field():
    out = decide({}, {}, "review the PR", _MalformedLLM())
    # The six documented keys are always present and normalized...
    assert _KEYS <= set(out)
    assert out["action"] == "assign-reviewer"
    assert out["labels"] == ["bug"]
    assert out["reviewer"] is None
    assert out["version_bump"] == "minor"
    assert out["patch"] is None
    assert out["rationale"] == ""
    # ...and any extra model key passes through unnormalized (documented, not part of the contract).
    assert "junk" in out


class _OfflineLLM:
    offline = True

    def chat_json(self, system, user, stub=None):
        return stub


def test_decide_offline_returns_normalized_stub_shape():
    out = decide({}, {}, "plan next steps", _OfflineLLM())
    assert set(out) == _KEYS
    assert out["action"] == "plan"
    assert out["labels"] == [] and out["patch"] is None and out["reviewer"] is None
