"""Tests for the maintainer decider (offline, deterministic)."""

import logging
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

os.environ["VANGUARSTEW_OFFLINE"] = "1"

from agent.decider import (  # noqa: E402
    _LENS_SYSTEMS,
    SYSTEM,
    VALID_ACTIONS,
    _is_planning_request,
    _normalize_action,
    _normalize_labels,
    _normalize_lens_verdict,
    _normalize_patch,
    _normalize_rationale,
    _normalize_reviewer,
    _normalize_version_bump,
    _planning_version_bump_note,
    _release_context_note,
    _run_lens,
    decide,
)
from agent.llm import LLM  # noqa: E402


def test_normalize_action_passes_valid_actions_through():
    for action in VALID_ACTIONS:
        assert _normalize_action(action) == action
        assert _normalize_action(action.upper()) == action  # case-insensitive
        assert _normalize_action(f"  {action}  ") == action  # whitespace-tolerant


def test_normalize_action_maps_common_synonyms():
    assert _normalize_action("approve") == "merge"
    assert _normalize_action("LGTM") == "merge"
    assert _normalize_action("request changes") == "request-changes"
    assert _normalize_action("request_changes") == "request-changes"
    assert _normalize_action("closed") == "close"
    assert _normalize_action("triaged") == "triage"
    assert _normalize_action("labeled") == "label"


def test_normalize_action_falls_back_to_plan_for_unknown_or_missing():
    assert _normalize_action("do-the-thing") == "plan"
    assert _normalize_action("") == "plan"
    assert _normalize_action(None) == "plan"


def test_normalize_action_tolerates_empty_and_whitespace_strings():
    assert _normalize_action("") == "plan"
    assert _normalize_action("   ") == "plan"
    assert _normalize_action("\t\n") == "plan"


def test_normalize_action_tolerates_non_string_input():
    assert _normalize_action(["merge"]) == "plan"
    assert _normalize_action({"value": "merge"}) == "plan"
    assert _normalize_action(42) == "plan"
    assert _normalize_action(4.2) == "plan"
    assert _normalize_action(True) == "plan"
    assert _normalize_action(b"merge") == "plan"


def test_normalize_action_logs_a_warning_for_non_string_input(caplog):
    with caplog.at_level(logging.WARNING, logger="agent.decider"):
        assert _normalize_action(["merge"]) == "plan"
    assert any("non-string action" in r.message for r in caplog.records)
    caplog.clear()
    with caplog.at_level(logging.WARNING, logger="agent.decider"):
        assert _normalize_action("approve") == "merge"
    assert not caplog.records


def test_decide_offline_returns_a_valid_action():
    llm = LLM(api_key="offline")
    out = decide({}, {}, "review PR #1", llm)
    assert out["action"] in VALID_ACTIONS
    assert out["action"] == "plan"  # the offline stub's default


def test_decide_tolerates_non_dict_llm_output():
    class _FakeLLM:
        offline = False

        def chat_json(self, system, user, stub=None):
            return "not a dict"

    out = decide({}, {}, "review PR #1", _FakeLLM())
    assert out["action"] in VALID_ACTIONS


def test_normalize_labels_coerces_to_string_list():
    assert _normalize_labels(None) == []
    assert _normalize_labels("bug") == ["bug"]
    assert _normalize_labels("  enhancement  ") == ["enhancement"]
    assert _normalize_labels(["bug", "", None, "  docs  "]) == ["bug", "docs"]
    assert _normalize_labels(42) == []


def test_normalize_reviewer_coerces_to_string_or_none():
    assert _normalize_reviewer(None) is None
    assert _normalize_reviewer("alice") == "alice"
    assert _normalize_reviewer("  ") is None
    assert _normalize_reviewer(123) == "123"
    assert _normalize_reviewer(["alice"]) is None


def test_normalize_rationale_never_returns_none():
    assert _normalize_rationale(None) == ""
    assert _normalize_rationale("ship it") == "ship it"
    assert _normalize_rationale(7) == "7"


def test_normalize_patch_accepts_string_or_none():
    assert _normalize_patch(None) is None
    assert _normalize_patch("diff --git a/x b/x") == "diff --git a/x b/x"
    assert _normalize_patch("  ") is None
    assert _normalize_patch({"not": "a diff"}) is None


def test_decide_normalizes_malformed_structured_fields():
    class _FakeLLM:
        offline = False

        def chat_json(self, system, user, stub=None):
            return {
                "action": "label",
                "labels": "bug",
                "reviewer": 123,
                "version_bump": None,
                "patch": {"bad": True},
                "rationale": None,
            }

    out = decide({}, {}, "triage issue #1", _FakeLLM())
    assert out["labels"] == ["bug"]
    assert out["reviewer"] == "123"
    assert out["rationale"] == ""
    assert out["patch"] is None


class _NonStringActionLLM:
    offline = False

    def chat_json(self, system, user, stub=None):
        return {
            "action": ["merge", "reject"],
            "labels": ["bug", "core"],
            "reviewer": "alice",
            "version_bump": "minor",
            "patch": None,
            "rationale": "needs a regression test",
        }


def test_decide_survives_non_string_action_field():
    out = decide({}, {}, "triage issue #1", _NonStringActionLLM())
    # the malformed field degrades safely...
    assert out["action"] == "plan"
    # ...and every other field is still normalized correctly, unaffected by the bad action.
    assert out["labels"] == ["bug", "core"]
    assert out["reviewer"] == "alice"
    assert out["version_bump"] == "minor"
    assert out["patch"] is None
    assert out["rationale"] == "needs a regression test"


class _RejectingLLM:
    offline = False

    def chat_json(self, system, user, stub=None):
        return {
            "action": "reject",
            "labels": [],
            "reviewer": None,
            "version_bump": None,
            "patch": None,
            "rationale": "out of scope: this repo only accepts code changes",
        }


def test_planning_request_is_never_rejected_as_out_of_scope():
    # #1562: the identical planning request returned "plan" on one repo and "reject" on another
    # (the LLM read a repo's "only merges code changes" philosophy as grounds to reject the
    # planning request itself). A planning request asks for a plan; it is never a contribution to
    # reject, so a "reject" verdict is coerced back to "plan".
    out = decide({}, {}, "plan the next 5 maintainer actions", _RejectingLLM())
    assert out["action"] == "plan"
    # the other fields are untouched by the coercion
    assert "out of scope" in out["rationale"]


def test_non_planning_request_may_still_be_rejected():
    # The coercion is scoped to planning requests only — a real reject verdict on a concrete
    # contribution review must survive.
    out = decide({}, {}, "review PR #42", _RejectingLLM())
    assert out["action"] == "reject"


def test_normalize_version_bump_accepts_canonical_levels():
    for level in ("major", "minor", "patch"):
        assert _normalize_version_bump(level) == level
    assert _normalize_version_bump("  MINOR ") == "minor"
    assert _normalize_version_bump("PATCH") == "patch"


def test_normalize_version_bump_maps_nullish_and_unknown_to_none():
    assert _normalize_version_bump(None) is None
    assert _normalize_version_bump("") is None
    assert _normalize_version_bump("none") is None
    assert _normalize_version_bump("null") is None
    assert _normalize_version_bump("n/a") is None
    assert _normalize_version_bump("micro") is None
    for bad in (123, True, ["minor"], {"level": "patch"}):
        assert _normalize_version_bump(bad) is None


class _VersionBumpLLM:
    offline = False

    def __init__(self, payload):
        self.payload = payload

    def chat_json(self, system, user, stub=None):
        return dict(self.payload)


def test_decide_normalizes_version_bump_from_llm_output():
    ctx = {"recent_commits": [{"subject": "init"}]}
    out = decide(ctx, {}, "should we cut a release?", _VersionBumpLLM({"version_bump": "MINOR"}))
    assert out["version_bump"] == "minor"

    cleared = decide(ctx, {}, "no release", _VersionBumpLLM({"version_bump": "none"}))
    assert cleared["version_bump"] is None

    junk = decide(ctx, {}, "decide", _VersionBumpLLM({"version_bump": "yolo"}))
    assert junk["version_bump"] is None

    non_string = decide(ctx, {}, "decide", _VersionBumpLLM({"version_bump": 2}))
    assert non_string["version_bump"] is None


# ── specialist lenses: correctness / direction / risk, synthesized into one call ──────────

def test_normalize_lens_verdict_defaults_and_coerces():
    assert _normalize_lens_verdict({"verdict": "sound", "reasoning": "tests pass"}) == {
        "verdict": "sound", "reasoning": "tests pass",
    }
    # missing/malformed verdict never raises and never returns None
    assert _normalize_lens_verdict({}) == {"verdict": "unclear", "reasoning": ""}
    assert _normalize_lens_verdict("not a dict") == {"verdict": "unclear", "reasoning": ""}
    assert _normalize_lens_verdict({"verdict": None, "reasoning": 7}) == {
        "verdict": "unclear", "reasoning": "7",
    }


def test_run_lens_covers_all_three_named_lenses():
    # every lens named in _LENS_SYSTEMS must be runnable and return the same normalized shape
    llm = LLM(api_key="offline")
    for name in _LENS_SYSTEMS:
        out = _run_lens(name, {}, {}, "review PR #1", llm)
        assert set(out) == {"verdict", "reasoning"}
        assert isinstance(out["verdict"], str) and out["verdict"]


class _LensCountingLLM:
    """Records every system prompt it's asked, so a test can prove decide() actually
    consults each specialist lens (not just the final synthesis) before deciding."""

    offline = False

    def __init__(self):
        self.systems_seen = []

    def chat_json(self, system, user, stub=None):
        self.systems_seen.append(system)
        if system == SYSTEM:  # the final synthesis call
            return {
                "action": "merge", "labels": [], "reviewer": None,
                "version_bump": None, "patch": None,
                "rationale": "correctness and direction agreed; risk lens flagged timing "
                             "but the fix is small enough to land now",
            }
        # each lens gets a distinguishable verdict so we can confirm all 3 ran
        return {"verdict": f"{system[:20]}-verdict", "reasoning": "because"}


def test_decide_consults_every_specialist_lens_before_synthesizing():
    llm = _LensCountingLLM()
    out = decide({}, {}, "merge PR #9", llm)

    # all 3 lenses were asked (their system prompts are the 3 distinct _LENS_SYSTEMS values)
    lens_calls = [s for s in llm.systems_seen if s in _LENS_SYSTEMS.values()]
    assert len(lens_calls) == 3
    assert len(set(lens_calls)) == 3  # each lens's system prompt is genuinely distinct

    # the final synthesis call happened AFTER all 3 lenses (last in call order)
    assert llm.systems_seen[-1] == SYSTEM

    # the final decision is still shaped exactly like every other decide() call
    assert out["action"] == "merge"
    assert "risk" in out["rationale"] or "timing" in out["rationale"]


def test_decide_offline_runs_lenses_without_network_and_keeps_stub_shape():
    # offline: every chat_json call (3 lenses + synthesis) must short-circuit to its stub,
    # and the FINAL decision shape must be byte-for-byte what it was before the lens split.
    llm = LLM(api_key="offline")
    out = decide({}, {}, "review PR #1", llm)
    assert out == {
        "action": "plan",
        "labels": [],
        "reviewer": None,
        "version_bump": None,
        "patch": None,
        "rationale": "offline stub decision",
    }


def test_release_context_note_surfaces_highest_frozen_tag():
    # Highest semver among frozen releases, regardless of list order (git is oldest-first;
    # the GitHub path is newest-first — see #1635).
    note = _release_context_note({"releases": [{"tag": "v2.0.3"}, {"tag": "v2.1.0"}]})
    assert "v2.1.0" in note
    assert "version_bump" in note
    assert "newest first" not in note.lower()


def test_release_context_note_uses_anchor_base_not_list_head():
    # Git builders store releases oldest-first; slicing [:3] previously labeled the three
    # OLDEST tags "newest first", pointing version_bump at a stale base (e.g. 0.13.0 when
    # the objective anchor's base_from_releases is 1.6.0).
    releases = [
        {"tag": "0.13.0"},
        {"tag": "0.13.1"},
        {"tag": "1.0.0.dev0"},
        {"tag": "1.5.0"},
        {"tag": "1.6.0"},
    ]
    note = _release_context_note({"releases": releases})
    assert "1.6.0" in note
    assert "0.13.0" not in note
    assert "0.13.1" not in note
    # Newest-first order (GitHub API path) must resolve to the same base.
    note_rev = _release_context_note({"releases": list(reversed(releases))})
    assert "1.6.0" in note_rev
    assert "0.13.0" not in note_rev


def test_release_context_note_empty_when_no_releases():
    assert _release_context_note({}) == ""
    assert _release_context_note({"releases": []}) == ""
    assert _release_context_note({"releases": [{"tag": ""}]}) == ""
    assert _release_context_note({"releases": [{"tag": "nightly"}]}) == ""  # no parseable semver


def test_is_planning_request():
    assert _is_planning_request("plan the next 5 maintainer actions") is True
    assert _is_planning_request("Plan The Next 3 actions") is True
    assert _is_planning_request("review PR #1") is False
    assert _is_planning_request(None) is False


def test_planning_version_bump_note_on_planning_request_with_tags():
    ctx = {"releases": [{"tag": "v1.2.0"}], "recent_commits": [{"subject": "fix: a"}]}
    note = _planning_version_bump_note(ctx, "plan the next 5 maintainer actions")
    assert "version_bump" in note
    assert _planning_version_bump_note(ctx, "merge PR #9") == ""
    assert _planning_version_bump_note({}, "plan the next 5 maintainer actions") == ""


def test_planning_version_bump_note_on_cadence_without_tags():
    ctx = {"recent_commits": [{"subject": "chore(release): 2.0.0"}]}
    note = _planning_version_bump_note(ctx, "plan the next 3 maintainer actions")
    assert "version_bump" in note


def test_decide_prompt_surfaces_planning_bump_note():
    captured = {}

    class CapturingLLM:
        offline = False

        def chat_json(self, system, user, stub=None):
            captured.setdefault("users", []).append(user)
            if system == SYSTEM:
                return {
                    "action": "plan", "labels": [], "reviewer": None,
                    "version_bump": "minor", "patch": None, "rationale": "cadence",
                }
            return {"verdict": "ok", "reasoning": "because"}

    ctx = {"releases": [{"tag": "v2.0.0"}], "recent_commits": [{"subject": "feat: x"}]}
    decide(ctx, {}, "plan the next 5 maintainer actions", CapturingLLM())
    synthesis = captured["users"][-1]
    assert "forward planning" in synthesis and "version_bump" in synthesis
