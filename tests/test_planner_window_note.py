"""Tests for the planner's time-horizon window note (#1891) — deterministic, offline.

The runner asks either ``plan the next N maintainer actions`` (commit-horizon) or
``plan the maintainer actions for the next N days`` (curated time-horizon, #1740). The
decider was taught both templates in #1772; the planner never received the request at all,
so the plan prompt could not surface the window the run asked about. These tests lock:

- the window parser and the shared planning-request recognizer (single source for both
  the planner and the decider's guards);
- the note is information-only: the ask line stays byte-for-byte unchanged on every
  template, and no wording that licenses filtering or shortening the plan is introduced;
- a request without a parseable window renders the previous prompt byte-for-byte;
- ``solve`` actually forwards the runner's request to the planner.
"""

import json
import os
import shutil
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

os.environ["VANGUARSTEW_OFFLINE"] = "1"

from agent.decider import _is_planning_request  # noqa: E402
from agent.planner import (  # noqa: E402
    _planning_window_note,
    is_planning_request,
    plan_next_actions,
    planning_horizon_days,
)
from benchmark.runner import load_solve  # noqa: E402

# Pinned literals — the runner's two request templates and the exact prompt fragments the
# planner must (and must not) emit. Deliberately NOT derived from the code under test.
TIME_HORIZON_REQUEST = "plan the maintainer actions for the next 30 days"
COMMIT_HORIZON_REQUEST = "plan the next 5 maintainer actions"
WINDOW_NOTE_30 = "\nThe planning window is the next 30 days.\n"
ASK_LINE = "Plan the next 5 maintainer actions/PRs. Return a JSON list; each item:"

# Neutral context — no benchmark-repo names anywhere in the fixture.
CTX = {
    "frozen_at": {"commit": "abc123"},
    "recent_commits": [{"sha": "1", "subject": "fix: handle empty input"}],
    "open_prs": [],
}


class _CapturingLLM:
    """Records every (system, user) prompt and answers with the offline stub."""

    offline = True
    api_key = "offline"
    model = "capture"

    def __init__(self, *args, **kwargs):
        pass

    calls = []  # class-level: survives solve() constructing its own instance

    def chat_json(self, system, user, stub=None):
        _CapturingLLM.calls.append((system, user))
        return stub


def _planner_prompt(request=..., n=5):
    """The exact user prompt plan_next_actions sends for CTX and the given request."""
    llm = _CapturingLLM()
    _CapturingLLM.calls = []
    if request is ...:  # backwards-compat call shape: no request argument at all
        plan_next_actions(CTX, {}, n, llm)
    else:
        plan_next_actions(CTX, {}, n, llm, request)
    assert len(_CapturingLLM.calls) == 1
    return _CapturingLLM.calls[0][1]


# ---------------------------------------------------------------- window parsing


def test_horizon_days_parses_the_time_horizon_template():
    assert planning_horizon_days(TIME_HORIZON_REQUEST) == 30
    assert planning_horizon_days("plan the maintainer actions for the next 7 days") == 7
    assert planning_horizon_days("plan the maintainer actions for the next 1 day") == 1


def test_horizon_days_is_case_insensitive_and_searches_within_text():
    assert planning_horizon_days("Plan The Maintainer Actions For The Next 14 Days") == 14
    assert planning_horizon_days(
        "please plan the maintainer actions for the next 21 days, thanks") == 21


def test_horizon_days_none_for_commit_horizon_and_junk():
    assert planning_horizon_days(COMMIT_HORIZON_REQUEST) is None
    assert planning_horizon_days("review PR #7") is None
    assert planning_horizon_days("") is None
    assert planning_horizon_days(None) is None
    assert planning_horizon_days(42) is None
    assert planning_horizon_days(["plan the maintainer actions for the next 30 days"]) is None


def test_horizon_days_rejects_degenerate_counts():
    assert planning_horizon_days("plan the maintainer actions for the next 0 days") is None
    assert planning_horizon_days("plan the maintainer actions for the next -3 days") is None
    assert planning_horizon_days("plan the maintainer actions for the next few days") is None


# ---------------------------------------------------------------- shared recognizer


def test_is_planning_request_accepts_both_runner_templates():
    assert is_planning_request(TIME_HORIZON_REQUEST) is True
    assert is_planning_request(COMMIT_HORIZON_REQUEST) is True
    assert is_planning_request("Plan the next 3 maintainer actions") is True


def test_is_planning_request_is_looser_than_the_window_parser():
    # A windowless time-horizon phrasing is still a planning request — it just carries no
    # usable window for the prompt note.
    windowless = "plan the maintainer actions for the next few days"
    assert is_planning_request(windowless) is True
    assert planning_horizon_days(windowless) is None


def test_is_planning_request_rejects_non_planning_requests():
    assert is_planning_request("review PR #7") is False
    assert is_planning_request("merge the release branch") is False
    assert is_planning_request(None) is False
    assert is_planning_request(7) is False


def test_decider_guard_agrees_with_the_shared_recognizer():
    # The decider's reject→plan guard and version_bump note must recognize exactly the same
    # templates as the planner (#1768 was the two drifting apart). Pinned expectations, both
    # templates and a non-planning request.
    assert _is_planning_request(TIME_HORIZON_REQUEST) is True
    assert _is_planning_request(COMMIT_HORIZON_REQUEST) is True
    assert _is_planning_request("review PR #7") is False


# ---------------------------------------------------------------- the note itself


def test_window_note_literal_for_a_time_horizon_request():
    assert _planning_window_note(TIME_HORIZON_REQUEST) == WINDOW_NOTE_30


def test_window_note_empty_without_a_parseable_window():
    assert _planning_window_note(COMMIT_HORIZON_REQUEST) == ""
    assert _planning_window_note(None) == ""
    assert _planning_window_note("plan the maintainer actions for the next 0 days") == ""


# ---------------------------------------------------------------- prompt rendering


def test_time_horizon_prompt_carries_the_window_note_before_the_ask():
    prompt = _planner_prompt(TIME_HORIZON_REQUEST)
    assert WINDOW_NOTE_30 in prompt
    assert ASK_LINE in prompt
    assert prompt.index(WINDOW_NOTE_30) < prompt.index(ASK_LINE)


def test_ask_line_is_unchanged_on_every_template():
    # The ask line is byte-identical whether or not a window is present — the note only adds
    # information, it never rewords the ask.
    for request in (TIME_HORIZON_REQUEST, COMMIT_HORIZON_REQUEST, None):
        assert ASK_LINE in _planner_prompt(request)


def test_no_filtering_language_is_introduced():
    # Module recall carries no precision penalty, so wording that licenses a shorter or
    # filtered plan can only lose recall. Lock out the phrasings that invite it.
    prompt = _planner_prompt(TIME_HORIZON_REQUEST)
    lowered = prompt.lower()
    assert "most likely to land" not in lowered
    assert "at most" not in lowered
    assert "most important" not in lowered


def test_windowless_requests_render_the_previous_prompt_byte_for_byte():
    base = _planner_prompt()  # no request argument: the pre-change call shape
    assert base == _planner_prompt(None)
    assert base == _planner_prompt(COMMIT_HORIZON_REQUEST)
    assert base == _planner_prompt("plan the maintainer actions for the next 0 days")
    assert "planning window" not in base


def test_window_note_scales_with_the_requested_days():
    prompt = _planner_prompt("plan the maintainer actions for the next 45 days")
    assert "\nThe planning window is the next 45 days.\n" in prompt
    assert WINDOW_NOTE_30 not in prompt


# ---------------------------------------------------------------- solve() wiring


def test_solve_forwards_the_runner_request_to_the_planner():
    solve = load_solve(os.path.join(ROOT, "agent.py"))
    solve.__globals__["LLM"] = _CapturingLLM  # fresh module per load_solve; no restore needed
    _CapturingLLM.calls = []
    d = tempfile.mkdtemp()
    try:
        with open(os.path.join(d, ".vanguarstew_context.json"), "w", encoding="utf-8") as f:
            json.dump(CTX, f)
        out = solve(repo_path=d, request="plan the maintainer actions for the next 45 days")
    finally:
        shutil.rmtree(d, ignore_errors=True)
    assert out["success"] is True
    planner_prompts = [user for _, user in _CapturingLLM.calls if ASK_LINE in user]
    assert len(planner_prompts) == 1
    assert "\nThe planning window is the next 45 days.\n" in planner_prompts[0]


def test_solve_commit_horizon_request_leaves_the_planner_prompt_windowless():
    solve = load_solve(os.path.join(ROOT, "agent.py"))
    solve.__globals__["LLM"] = _CapturingLLM
    _CapturingLLM.calls = []
    d = tempfile.mkdtemp()
    try:
        with open(os.path.join(d, ".vanguarstew_context.json"), "w", encoding="utf-8") as f:
            json.dump(CTX, f)
        out = solve(repo_path=d, request=COMMIT_HORIZON_REQUEST)
    finally:
        shutil.rmtree(d, ignore_errors=True)
    assert out["success"] is True
    planner_prompts = [user for _, user in _CapturingLLM.calls if ASK_LINE in user]
    assert len(planner_prompts) == 1
    assert "planning window" not in planner_prompts[0]
