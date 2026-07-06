"""Smoke tests — offline, prove the loop wiring without network. Run:

    VANGUARSTEW_OFFLINE=1 python -m pytest -q
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

os.environ["VANGUARSTEW_OFFLINE"] = "1"

from agent.llm import extract_json  # noqa: E402
from benchmark.runner import load_solve, run_replay  # noqa: E402


def test_extract_json():
    assert extract_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert extract_json('noise {"x": [1, 2]} trailing') == {"x": [1, 2]}


def test_extract_json_multiple_bracket_spans_prefers_longest():
    text = 'first [1] then [2, 3] and finally [4, 5, 6]'
    assert extract_json(text) == [4, 5, 6]


def test_extract_json_multiple_objects_prefers_longest():
    text = 'thought {"a": 1} revised: {"a": 1, "b": 2, "c": 3}'
    assert extract_json(text) == {"a": 1, "b": 2, "c": 3}


def test_extract_json_nested_object():
    text = 'prefix {"a": {"b": [1, 2, 3]}, "c": true} suffix'
    assert extract_json(text) == {"a": {"b": [1, 2, 3]}, "c": True}


def test_extract_json_prefers_object_over_leading_citation():
    text = '[1] the agent decided: {"decision": "approve", "confidence": 0.9}'
    assert extract_json(text) == {"decision": "approve", "confidence": 0.9}


def test_extract_json_invalid_citation_is_skipped():
    text = 'see [Doe, 2020] for background — result: {"ok": true}'
    assert extract_json(text) == {"ok": True}


def test_extract_json_raises_when_no_valid_candidate():
    with pytest.raises(ValueError):
        extract_json('no json here at all, just [Doe, 2020] prose')


def test_extract_json_prefers_later_fenced_object_over_earlier_schema_example():
    text = '''Sure, I will respond in this format:
```json
{"action": "merge", "labels": [], "reviewer": null, "version_bump": null, "patch": null, "rationale": "example"}
```

Given the repo state, my actual decision:
```json
{"action": "reject", "labels": ["needs-tests"], "reviewer": "alice", "version_bump": null, "patch": null, "rationale": "missing tests, high risk change"}
```
'''
    assert extract_json(text) == {
        "action": "reject",
        "labels": ["needs-tests"],
        "reviewer": "alice",
        "version_bump": None,
        "patch": None,
        "rationale": "missing tests, high risk change",
    }


def test_extract_json_equal_rank_prefers_last_fence():
    """When two fences have equal rank (same shape + length), the later one wins."""
    text = 'Example:\n```json\n{"action":"praise","score":1}\n```\n\nReal:\n```json\n{"action":"reject","score":6}\n```'
    result = extract_json(text)
    assert result == {"action": "reject", "score": 6}, (
        f"equal-rank tiebreaker must prefer the last fence, got {result}"
    )


def test_extract_json_single_fenced_block_unchanged():
    assert extract_json('```json\n{"a": 1}\n```') == {"a": 1}


def test_solve_offline_returns_decision():
    d = tempfile.mkdtemp()
    try:
        with open(os.path.join(d, ".vanguarstew_context.json"), "w", encoding="utf-8") as f:
            json.dump({
                "frozen_at": {"commit": "abc"},
                "recent_commits": [{"sha": "1", "subject": "init"}],
                "readme_excerpt": "demo project",
            }, f)
        solve = load_solve(os.path.join(ROOT, "agent.py"))
        out = solve(repo_path=d, api_key="offline")
        for key in ("philosophy", "plan", "action", "rationale", "success"):
            assert key in out
        assert out["success"] is True
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_offline_plan_prioritizes_open_pr_queue():
    from agent.llm import LLM
    from agent.planner import plan_next_actions

    ctx = {
        "open_prs": [{"number": 7, "title": "Add streaming export"}],
        "recent_commits": [{"sha": "1", "subject": "init"}],
    }
    plan = plan_next_actions(ctx, {}, 3, LLM(api_key="offline"))
    assert any("streaming export" in item.get("title", "").lower() for item in plan)


@pytest.mark.skipif(shutil.which("git") is None, reason="git required")
def test_replay_end_to_end_offline():
    d = tempfile.mkdtemp()
    try:
        subprocess.run(["git", "init", "-q", d], check=True)
        subprocess.run(["git", "-C", d, "config", "user.email", "t@t"], check=True)
        subprocess.run(["git", "-C", d, "config", "user.name", "t"], check=True)
        for i in range(20):
            with open(os.path.join(d, f"f{i}.py"), "w", encoding="utf-8") as f:
                f.write(f"x = {i}\n")
            subprocess.run(["git", "-C", d, "add", "-A"], check=True)
            subprocess.run(["git", "-C", d, "commit", "-q", "-m", f"commit {i}"], check=True)
        res = run_replay(d, agent_file=os.path.join(ROOT, "agent.py"), n_tasks=2, horizon=3)
        assert res.get("tasks", 0) >= 1
        assert "tally" in res and "decisive_margin" in res
    finally:
        shutil.rmtree(d, ignore_errors=True)
