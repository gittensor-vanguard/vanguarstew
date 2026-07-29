"""Locks for the objective-anchor alignment changes — deterministic, offline.

Three seams, one theme: the plan/decision the agent emits should be exactly as scoreable as
the model's own answer supports, never less.

- ``_normalize_plan_item`` keeps a Conventional-Commit-spelled ``kind`` ("fix", "feat",
  "chore") instead of degrading it to "triage", which names no commit kind.
- ``_backfill_files_from_layout`` attaches ``files`` only when the item's own text names a
  real top-level layout entry — token-gated, capped, and inert for triage/release items.
- ``decide()`` backfills ``version_bump`` on planning requests from the repo's own release
  cadence (modal historical bump class); the local ``_base_from_releases`` mirror stays
  equivalent to the anchor's resolver so ``agent/`` needs no ``benchmark/`` import.
"""

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

os.environ["VANGUARSTEW_OFFLINE"] = "1"

import pytest  # noqa: E402

from agent.decider import (  # noqa: E402
    _base_from_releases,
    _parse_semver,
    _recent_bump_class,
    decide,
)
from agent.planner import (  # noqa: E402
    _JUDGE_PLAN_COMPACT_BUDGET,
    _backfill_files_from_layout,
    _normalize_plan_item,
    plan_next_actions,
)
from benchmark.score import base_from_releases, parse_semver  # noqa: E402

# ── kind: Conventional-Commit spellings keep their intended kind ──────────────────────────


@pytest.mark.parametrize("raw,expected", [
    ("fix", "bugfix"),
    ("FIX", "bugfix"),
    ("bug", "bugfix"),
    ("feat", "feature"),
    ("doc", "docs"),
    ("chore", "dep"),
    ("deps", "dep"),
    ("tests", "test"),
])
def test_cc_spelled_kind_keeps_intended_kind(raw, expected):
    assert _normalize_plan_item({"title": "work", "kind": raw})["kind"] == expected


@pytest.mark.parametrize("bad_kind", [None, "", "  ", "mystery", 42, ["feature"]])
def test_unknown_kind_still_defaults_to_triage(bad_kind):
    assert _normalize_plan_item({"title": "work", "kind": bad_kind})["kind"] == "triage"


# ── files backfill: token-gated against the frozen repo layout ────────────────────────────


def test_backfill_attaches_entry_named_by_the_item_itself():
    plan = [{"title": "Harden the loader in src", "kind": "bugfix"}]
    out = _backfill_files_from_layout(plan, {"repo_layout": ["src", "tests", "README.md"]})
    assert out[0]["files"] == ["src"]


def test_backfill_reads_theme_and_rationale_too():
    plan = [{
        "title": "Stabilize flaky suite",
        "kind": "test",
        "rationale": "the tests directory has intermittent failures",
    }]
    out = _backfill_files_from_layout(plan, {"repo_layout": ["src", "tests"]})
    assert out[0]["files"] == ["tests"]


def test_backfill_never_attaches_unmentioned_modules():
    plan = [{"title": "Improve error messages", "kind": "bugfix"}]
    out = _backfill_files_from_layout(plan, {"repo_layout": ["src", "tests"]})
    assert "files" not in out[0]


def test_backfill_caps_at_two_entries_in_layout_order():
    plan = [{"title": "Modernize tox, src and setup packaging", "kind": "refactor"}]
    out = _backfill_files_from_layout(
        plan, {"repo_layout": ["tox.ini", "src", "setup.py"]},
    )
    assert out[0]["files"] == ["tox.ini", "src"]


def test_backfill_skips_triage_and_already_filed_items():
    plan = [
        {"title": "Review pull request #7: src cleanup", "kind": "triage"},
        {"title": "Refactor src loader", "kind": "refactor", "files": ["src/loader.py"]},
    ]
    out = _backfill_files_from_layout(plan, {"repo_layout": ["src"]})
    assert "files" not in out[0]
    assert out[1]["files"] == ["src/loader.py"]


def test_backfill_release_item_earns_changelog_by_its_own_words():
    plan = [{"title": "Cut the next release and update the changelog", "kind": "release"}]
    out = _backfill_files_from_layout(plan, {"repo_layout": ["CHANGELOG.rst", "src/"]})
    assert out[0]["files"] == ["CHANGELOG.rst"]


def test_backfill_release_item_without_surface_tokens_gets_nothing():
    # "release" is a stopword for token matching, so a bare release title attaches nothing.
    plan = [{"title": "Prepare the next release", "kind": "release"}]
    out = _backfill_files_from_layout(plan, {"repo_layout": ["CHANGELOG.rst", "src/"]})
    assert "files" not in out[0]


# ── files backfill: judge render-budget guard ─────────────────────────────────────────────


def test_backfill_skips_attachment_that_would_cross_the_judge_budget():
    # A plan already near the judge renderer's compact per-field budget must pass through
    # verbatim: growing it past the truncation cliff would degrade the WHOLE plan to a
    # mangled prefix blob in the judge's view, a strictly worse outcome than a missing
    # files field. Content is never trimmed to make room.
    bulky = {
        "title": "Harden the loader in src",
        "kind": "bugfix",
        "rationale": "x" * _JUDGE_PLAN_COMPACT_BUDGET,
    }
    out = _backfill_files_from_layout([bulky], {"repo_layout": ["src"]})
    assert "files" not in out[0]
    assert out[0]["rationale"] == bulky["rationale"]


def test_backfill_attaches_normally_under_the_judge_budget():
    plan = [{"title": "Harden the loader in src", "kind": "bugfix", "rationale": "short"}]
    out = _backfill_files_from_layout(plan, {"repo_layout": ["src"]})
    assert out[0]["files"] == ["src"]


def test_backfill_no_ops_on_missing_or_malformed_layout():
    plan = [{"title": "Harden the loader in src", "kind": "bugfix"}]
    assert _backfill_files_from_layout(plan, {}) == plan
    assert _backfill_files_from_layout(plan, {"repo_layout": "src"}) == plan


class _PlanLLM:
    offline = False

    def __init__(self, plan):
        self.plan = plan

    def chat_json(self, system, user, stub=None):
        self.last_user = user
        return [dict(item) for item in self.plan]


def test_plan_next_actions_backfills_end_to_end():
    ctx = {"repo_layout": ["src", "docs", "tests"], "recent_commits": [{"subject": "init"}]}
    llm = _PlanLLM([{"title": "Harden the loader in src", "kind": "bugfix"}])
    out = plan_next_actions(ctx, {}, 3, llm)
    assert out[0]["files"] == ["src"]


# ── decider: local release-base mirror stays equivalent to the anchor's resolver ──────────


@pytest.mark.parametrize("text", [
    "v1.2.3", "1.2", "release 1.4.0", "v2.0.0-rc1", "no version here", None, 42,
])
def test_parse_semver_mirror_matches_anchor(text):
    assert _parse_semver(text) == parse_semver(text)


@pytest.mark.parametrize("releases", [
    [{"tag": "v1.2.0"}, {"tag": "v1.10.0"}, {"tag": "v1.3.0"}],
    [{"name": "Preview of 9.0"}, {"tag": "v2.0.0"}],
    [{"tag": None, "name": "1.4"}],
    [{"tag": "not-semver", "name": "also not"}],
    [{"tag": "v1.0.0"}, "corrupt-row", {"tag": "v1.1.0"}],
    [],
    "not-a-list",
    None,
])
def test_base_from_releases_mirror_matches_anchor(releases):
    assert _base_from_releases(releases) == base_from_releases(releases)


# ── decider: most-recent-pair bump class ──────────────────────────────────────────────────


def test_recent_bump_class_tracks_latest_step():
    ctx = {"releases": [
        {"tag": "v1.0.0"}, {"tag": "v1.0.1"}, {"tag": "v1.0.2"}, {"tag": "v1.1.0"},
    ]}
    assert _recent_bump_class(ctx) == "minor"

    ctx = {"releases": [{"tag": "v1.0.0"}, {"tag": "v1.1.0"}, {"tag": "v2.0.0"}]}
    assert _recent_bump_class(ctx) == "major"


def test_recent_bump_class_tracks_regime_change_over_history_mode():
    # Minor-heavy history whose latest step is a patch: the next cut is asked about the
    # CURRENT cadence regime, and the latest step tracks it where an all-history mode lags.
    ctx = {"releases": [
        {"tag": "v1.0.0"}, {"tag": "v1.1.0"}, {"tag": "v1.2.0"}, {"tag": "v1.2.1"},
    ]}
    assert _recent_bump_class(ctx) == "patch"


def test_recent_bump_class_order_independent():
    oldest_first = {"releases": [{"tag": "v1.0.0"}, {"tag": "v1.1.0"}, {"tag": "v1.2.0"}]}
    newest_first = {"releases": [{"tag": "v1.2.0"}, {"tag": "v1.1.0"}, {"tag": "v1.0.0"}]}
    assert _recent_bump_class(oldest_first) == _recent_bump_class(newest_first) == "minor"


def test_recent_bump_class_single_release_defaults_to_patch():
    assert _recent_bump_class({"releases": [{"tag": "v1.2.0"}]}) == "patch"


def test_recent_bump_class_none_without_versioned_releases():
    assert _recent_bump_class({"releases": []}) is None
    assert _recent_bump_class({"releases": [{"tag": "nope"}]}) is None
    assert _recent_bump_class({}) is None
    assert _recent_bump_class(None) is None


# ── decider: version_bump backfill on planning requests ───────────────────────────────────


class _DecisionLLM:
    offline = False

    def __init__(self, payload):
        self.payload = payload

    def chat_json(self, system, user, stub=None):
        return dict(self.payload)


_PLANNING_REQUEST = "plan the next 5 maintainer actions"
_CADENCE_CTX = {
    "recent_commits": [{"subject": "improve parser"}],
    "releases": [{"tag": "v1.0.0"}, {"tag": "v1.0.1"}, {"tag": "v1.0.2"}],
}


def test_decide_backfills_bump_on_planning_request():
    out = decide(_CADENCE_CTX, {}, _PLANNING_REQUEST, _DecisionLLM({"action": "plan"}))
    assert out["version_bump"] == "patch"


def test_decide_llm_bump_takes_precedence_over_backfill():
    out = decide(
        _CADENCE_CTX, {}, _PLANNING_REQUEST,
        _DecisionLLM({"action": "plan", "version_bump": "minor"}),
    )
    assert out["version_bump"] == "minor"


def test_decide_no_backfill_on_non_planning_request():
    out = decide(_CADENCE_CTX, {}, "should we merge PR 5?", _DecisionLLM({"action": "merge"}))
    assert out["version_bump"] is None


def test_decide_no_backfill_just_after_a_cut():
    just_cut = {
        "recent_commits": [{"subject": "chore(release): 1.0.2"}],
        "releases": [{"tag": "v1.0.0"}, {"tag": "v1.0.1"}, {"tag": "v1.0.2"}],
    }
    out = decide(just_cut, {}, _PLANNING_REQUEST, _DecisionLLM({"action": "plan"}))
    assert out["version_bump"] is None


def test_decide_no_backfill_without_release_history():
    ctx = {"recent_commits": [{"subject": "improve parser"}]}
    out = decide(ctx, {}, _PLANNING_REQUEST, _DecisionLLM({"action": "plan"}))
    assert out["version_bump"] is None


# ── decider: recent-version-step evidence in the release context note ─────────────────────


def test_release_context_note_states_the_most_recent_version_step():
    from agent.decider import _release_context_note

    note = _release_context_note(_CADENCE_CTX)
    assert "Current release at freeze" in note
    assert "Most recent version step: 1.0.1 -> 1.0.2 (a patch bump)." in note


def test_release_context_note_omits_step_with_a_single_version():
    from agent.decider import _release_context_note

    note = _release_context_note({"releases": [{"tag": "v1.2.0"}]})
    assert "Current release at freeze" in note
    assert "Most recent version step" not in note
