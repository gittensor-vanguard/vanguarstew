"""The planner must plan for the window the runner actually asked about.

``run_replay`` asks either ``plan the next N maintainer actions`` (commit-horizon) or
``plan the maintainer actions for the next N days`` (curated ``horizon_days``, #1740). The
decider learned the second template in #1768; the planner did not, so it kept asking the model
for a bare count. These tests pin the horizon parsing, the prompt phrasing in both directions,
backward compatibility for count-scoped callers, and the shared-helper delegation that keeps
the planner and decider from diverging again. Offline, deterministic.
"""

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import agent.decider as decider  # noqa: E402
from agent.planner import (  # noqa: E402
    is_planning_request,
    plan_next_actions,
    planning_horizon_days,
)

_CONTEXT = {
    "frozen_at": "2019-04-02",
    "recent_commits": [{"sha": "a1", "date": "2019-03-01", "subject": "fix: parse edge case"}],
    "releases": [{"tag": "v0.8.1"}],
    "open_issues": [], "open_prs": [], "labels": [], "milestones": [],
    "readme_excerpt": "a small library",
}


class _SpyLLM:
    """Captures the rendered user prompt and returns the caller's offline stub."""

    def __init__(self):
        self.user = None

    def chat_json(self, system, user, stub=None):
        self.user = user
        return stub


def _prompt(request, n=3):
    llm = _SpyLLM()
    plan_next_actions(_CONTEXT, {"north_star": "stability"}, n, llm, request)
    return llm.user


def _ask_line(prompt):
    return next(line for line in prompt.splitlines() if line.startswith("Plan the"))


# --- The prompt follows the request ---------------------------------------------------------


def test_time_horizon_request_asks_for_the_window():
    line = _ask_line(_prompt("plan the maintainer actions for the next 51 days"))
    assert line.startswith(
        "Plan the 3 maintainer actions/PRs most likely to land in the next 51 days."
    )
    # The window, not just the count, reaches the model.
    assert "51 days" in line


def test_time_horizon_prompt_still_asks_for_n_items():
    # Module recall carries no precision penalty, so a shorter plan can only lose points.
    # The window must be added WITHOUT licensing fewer items ("at most N") or hinting at
    # prioritization, either of which would shrink the plan.
    line = _ask_line(_prompt("plan the maintainer actions for the next 51 days", n=5))
    assert "5 maintainer actions/PRs" in line
    for weakening in ("at most", "most important first", "up to", "as many as"):
        assert weakening not in line.lower()


class _OverlongLLM(_SpyLLM):
    """Returns far more items than requested, so the item cap is actually exercised."""

    def chat_json(self, system, user, stub=None):
        self.user = user
        return [{"title": f"item {i}", "kind": "bugfix", "rationale": "r",
                 "theme": "t", "files": [f"mod{i}/"]} for i in range(12)]


def test_time_horizon_request_still_honors_the_item_cap():
    # The new code path must keep passing `n` (not the horizon) to reconcile_plan_with_queue.
    # The LLM deliberately returns 12 items so a broken cap is visible; with the horizon (51)
    # used as the cap instead of n, this would return 12.
    for n in (1, 3, 5):
        plan = plan_next_actions(_CONTEXT, {"north_star": "stability"}, n, _OverlongLLM(),
                                 "plan the maintainer actions for the next 51 days")
        assert isinstance(plan, list)
        assert len(plan) == n, f"expected the plan capped at {n}, got {len(plan)}"

    # The count-scoped path caps identically — the two must not diverge.
    assert len(plan_next_actions(_CONTEXT, {"north_star": "stability"}, 3, _OverlongLLM(),
                                 "plan the next 3 maintainer actions")) == 3


def test_count_scoped_request_keeps_the_original_phrasing():
    for request in ("plan the next 5 maintainer actions", None, "", 5, ["not", "a", "string"]):
        assert _ask_line(_prompt(request)).startswith("Plan the next 3 maintainer actions/PRs.")


def test_omitting_request_is_byte_identical_to_the_previous_prompt():
    # Backward compatibility for every existing caller: the 4-argument form must not change.
    llm_old, llm_new = _SpyLLM(), _SpyLLM()
    plan_next_actions(_CONTEXT, {"north_star": "stability"}, 3, llm_old)
    plan_next_actions(_CONTEXT, {"north_star": "stability"}, 3, llm_new, None)
    assert llm_old.user == llm_new.user
    assert "Plan the next 3 maintainer actions/PRs." in llm_old.user


# --- Horizon parsing --------------------------------------------------------------------------


def test_planning_horizon_days_parses_the_window():
    assert planning_horizon_days("plan the maintainer actions for the next 51 days") == 51
    assert planning_horizon_days("PLAN THE MAINTAINER ACTIONS FOR THE NEXT 7 DAYS") == 7
    assert planning_horizon_days("plan the maintainer actions for the next 1 day") == 1


def test_planning_horizon_days_rejects_unusable_windows():
    # A non-positive count would render a nonsensical "next 0 days"; fall back to the count.
    for request in ("plan the maintainer actions for the next 0 days",
                    "plan the maintainer actions for the next -3 days",
                    "plan the maintainer actions for the next many days",
                    "plan the next 5 maintainer actions",
                    "for the next 14 days",
                    None, 5, "", [], {"days": 5}):
        assert planning_horizon_days(request) is None


# --- The shared helper the decider delegates to ------------------------------------------------


def test_is_planning_request_covers_both_templates():
    assert is_planning_request("plan the next 5 maintainer actions") is True
    assert is_planning_request("plan the maintainer actions for the next 51 days") is True
    # Still a planning request even when the count is unusable — it just carries no window.
    assert is_planning_request("plan the maintainer actions for the next 0 days") is True
    for bad in ("review the open queue", "", None, 5, [], {"request": "plan"}):
        assert is_planning_request(bad) is False


def test_decider_delegates_to_the_shared_helper():
    # The two modules must recognize the same templates; inlining the check in both is what let
    # them diverge (#1768 fixed the decider in #1772, not the planner). Pin the decider against
    # LITERALS, not against the shared helper — comparing it to what it calls would pass even if
    # both were broken together.
    expected = {
        "plan the next 5 maintainer actions": True,
        "plan the maintainer actions for the next 51 days": True,
        "plan the maintainer actions for the next 0 days": True,
        "review the open queue": False,
        "": False,
    }
    for request, want in expected.items():
        assert decider._is_planning_request(request) is want
        assert is_planning_request(request) is want
    for bad in (None, 5, [], {"request": "plan"}):
        assert decider._is_planning_request(bad) is False
        assert is_planning_request(bad) is False


def _load_entry():
    """Load ``agent.py`` the way ``benchmark/runner.py::load_solve`` loads it."""
    import importlib.util

    path = os.path.join(ROOT, "agent.py")
    spec = importlib.util.spec_from_file_location("vanguarstew_entry_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_solve_forwards_the_request_to_the_planner(monkeypatch):
    # End-to-end on the real entry point: the runner's request must reach the planner, not
    # stop at the decider. This is the wiring that was missing.
    entry = _load_entry()
    seen = {}

    def fake_plan(context, philosophy, n, llm, request=None):
        seen["request"] = request
        return []

    monkeypatch.setattr(entry, "plan_next_actions", fake_plan)
    monkeypatch.setattr(entry, "load_context", lambda path: dict(_CONTEXT))
    monkeypatch.setattr(entry, "infer_philosophy", lambda ctx, llm: {"north_star": "s"})
    monkeypatch.setattr(entry, "decide", lambda ctx, phil, req, llm: {})

    entry.solve(repo_path="/tmp/x", request="plan the maintainer actions for the next 51 days")
    assert seen["request"] == "plan the maintainer actions for the next 51 days"
