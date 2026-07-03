"""Tests for prompt-safe context rendering."""

import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from agent.context import prompt_context  # noqa: E402
from agent.decider import _render as render_decider  # noqa: E402
from agent.philosophy import _render as render_philosophy  # noqa: E402
from agent.planner import _render as render_planner  # noqa: E402


def test_prompt_context_marks_unavailable_issue_labels_as_unknown():
    ctx = {
        "open_issues": [
            {"number": 1, "title": "Unavailable label history", "labels": [],
             "labels_as_of_t": False},
            {"number": 2, "title": "Known labels", "labels": ["bug"],
             "labels_as_of_t": True},
        ],
        "open_prs": [
            {"number": 3, "title": "Unavailable PR labels", "labels": [],
             "labels_as_of_t": False},
        ],
        "labels": [],
    }
    out = prompt_context(ctx)
    assert out["open_issues"][0]["labels"] is None
    assert out["open_issues"][0]["labels_as_of_t"] is False
    assert out["open_issues"][1]["labels"] == ["bug"]
    assert out["open_prs"][0]["labels"] is None
    assert out["labels"] == []


def test_prompt_renderers_do_not_present_unavailable_labels_as_empty_history():
    ctx = {
        "open_issues": [{"number": 1, "title": "Unavailable", "labels": [],
                         "labels_as_of_t": False}],
        "open_prs": [{"number": 2, "title": "Known", "labels": ["benchmark"],
                      "labels_as_of_t": True}],
        "labels": [],
    }
    for render in (render_philosophy, render_planner, render_decider):
        rendered = json.loads(render(ctx))
        assert rendered["open_issues"][0]["labels"] is None
        assert rendered["open_issues"][0]["labels_as_of_t"] is False
        assert rendered["open_prs"][0]["labels"] == ["benchmark"]
