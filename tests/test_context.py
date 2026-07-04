"""Tests for the agent-facing frozen-context view."""

import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from agent.context import context_for_agent  # noqa: E402
from agent.decider import _render as render_decider_context  # noqa: E402
from agent.philosophy import _render as render_philosophy_context  # noqa: E402
from agent.planner import _render as render_planner_context  # noqa: E402


def test_context_for_agent_omits_unknown_issue_labels():
    ctx = {
        "open_issues": [{
            "number": 1,
            "title": "bug",
            "labels": [],
            "labels_as_of_t": False,
        }],
        "open_prs": [{
            "number": 2,
            "title": "fix bug",
            "labels": [],
            "labels_as_of_t": False,
        }],
    }
    out = context_for_agent(ctx)
    assert "labels" not in out["open_issues"][0]
    assert out["open_issues"][0]["labels_as_of_t"] is False
    assert "labels" not in out["open_prs"][0]
    assert out["open_prs"][0]["labels_as_of_t"] is False


def test_context_for_agent_keeps_reconstructed_labels():
    ctx = {
        "open_issues": [{
            "number": 1,
            "title": "bug",
            "labels": ["bug"],
            "labels_as_of_t": True,
        }],
    }
    out = context_for_agent(ctx)
    assert out["open_issues"][0]["labels"] == ["bug"]
    assert out["open_issues"][0]["labels_as_of_t"] is True


def test_prompt_renderers_do_not_serialize_unknown_labels_as_empty_history():
    ctx = {
        "frozen_at": {"commit": "abc"},
        "recent_commits": [{"sha": "1", "subject": "init"}],
        "open_issues": [{
            "number": 1,
            "title": "bug",
            "labels": [],
            "labels_as_of_t": False,
        }],
        "open_prs": [{
            "number": 2,
            "title": "fix bug",
            "labels": [],
            "labels_as_of_t": False,
        }],
        "labels": [],
        "milestones": [],
        "releases": [],
        "readme_excerpt": "",
    }
    for render in (render_philosophy_context, render_planner_context, render_decider_context):
        payload = json.loads(render(ctx))
        assert "labels" not in payload["open_issues"][0]
        assert payload["open_issues"][0]["labels_as_of_t"] is False
        assert "labels" not in payload["open_prs"][0]
        assert payload["open_prs"][0]["labels_as_of_t"] is False
