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


def test_extract_json_prefers_the_last_of_two_fenced_blocks():
    # A verbose/chain-of-thought response can restate a schema example in an earlier
    # fenced block before its real answer in a later one. Trusting only the FIRST fence
    # would return the throwaway example instead of the real, final decision.
    text = (
        'Sure, I will respond in this format:\n'
        '```json\n{"action": "merge", "rationale": "example"}\n```\n\n'
        'Given the repo state, my actual decision:\n'
        '```json\n{"action": "reject", "rationale": "missing tests, high risk change"}\n```\n'
    )
    assert extract_json(text) == {"action": "reject", "rationale": "missing tests, high risk change"}


def test_extract_json_single_fence_still_works():
    assert extract_json('```json\n{"a": 1, "b": 2}\n```\n\nfootnote: [1]') == {"a": 1, "b": 2}


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
        # each task row carries backlog diagnostics (empty list for this git-only run)
        assert res["rows"][0]["backlog_diagnostics"] == []
    finally:
        shutil.rmtree(d, ignore_errors=True)
