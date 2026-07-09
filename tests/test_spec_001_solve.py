"""Contract tests for specs/001-solve-contract — assert agent.py::solve satisfies the spec's
EARS criteria: stable entrypoint signature, offline determinism, and full output shape. Offline,
deterministic; no network is used.
"""

import inspect
import json
import os
import shutil
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

os.environ["VANGUARSTEW_OFFLINE"] = "1"

from agent.decider import VALID_ACTIONS  # noqa: E402
from benchmark.runner import load_solve  # noqa: E402

_SOLVE_KEYS = frozenset({
    "philosophy", "plan", "action", "labels", "reviewer", "version_bump",
    "patch", "rationale", "logs", "steps", "cost", "success",
})

_MIN_CONTEXT = {
    "frozen_at": {"commit": "abc123"},
    "recent_commits": [{"sha": "1", "subject": "init"}],
    "readme_excerpt": "demo project",
}


def _solve():
    return load_solve(os.path.join(ROOT, "agent.py"))


def _with_context(fn):
    d = tempfile.mkdtemp()
    try:
        with open(os.path.join(d, ".vanguarstew_context.json"), "w", encoding="utf-8") as f:
            json.dump(_MIN_CONTEXT, f)
        return fn(d)
    finally:
        shutil.rmtree(d, ignore_errors=True)


def _assert_solve_shape(out: dict):
    assert isinstance(out, dict)
    assert _SOLVE_KEYS <= set(out)
    assert isinstance(out["philosophy"], dict)
    assert isinstance(out["plan"], list)
    assert isinstance(out["action"], str)
    assert out["action"] in VALID_ACTIONS
    assert isinstance(out["labels"], list)
    assert out["reviewer"] is None or isinstance(out["reviewer"], str)
    assert out["version_bump"] in (None, "major", "minor", "patch")
    assert out["patch"] is None or isinstance(out["patch"], str)
    assert isinstance(out["rationale"], str)
    assert isinstance(out["logs"], str)
    assert isinstance(out["steps"], int)
    assert out["cost"] is None or isinstance(out["cost"], (int, float))
    assert isinstance(out["success"], bool)


# --- Entrypoint -----------------------------------------------------------------------------

def test_solve_exposes_managed_inference_parameters():
    params = inspect.signature(_solve()).parameters
    for name in ("repo_path", "request", "model", "api_base", "api_key", "n"):
        assert name in params


def test_solve_defaults_n_to_five():
    assert inspect.signature(_solve()).parameters["n"].default == 5


def test_solve_defaults_request_to_maintainer_prompt():
    default = inspect.signature(_solve()).parameters["request"].default
    assert isinstance(default, str) and "maintainer" in default.lower()


# --- Offline output shape -------------------------------------------------------------------

def test_solve_offline_returns_all_declared_keys():
    def run(repo_path):
        out = _solve()(repo_path=repo_path, api_key="offline")
        _assert_solve_shape(out)
        assert out["success"] is True
    _with_context(run)


def test_solve_offline_populates_decision_fields_from_stub():
    def run(repo_path):
        out = _solve()(repo_path=repo_path, api_key="offline")
        assert isinstance(out["philosophy"]["summary"], str)
        assert isinstance(out["plan"], list)
        assert out["action"] == "plan"
        assert out["labels"] == []
        assert out["reviewer"] is None
        assert out["version_bump"] is None
        assert out["patch"] is None
        assert isinstance(out["rationale"], str)
    _with_context(run)


# --- Offline determinism --------------------------------------------------------------------

def _semantic_solve_output(out: dict) -> dict:
    """Drop run-metadata keys that vary between back-to-back calls."""
    return {k: v for k, v in out.items() if k != "_elapsed_s"}


def test_solve_offline_is_deterministic_for_fixed_context():
    def run(repo_path):
        solve = _solve()
        first = solve(repo_path=repo_path, api_key="offline", n=3)
        second = solve(repo_path=repo_path, api_key="offline", n=3)
        _assert_solve_shape(first)
        assert _semantic_solve_output(first) == _semantic_solve_output(second)
        assert len(first["plan"]) <= 3
    _with_context(run)


def test_solve_offline_honors_n_plan_cap():
    def run(repo_path):
        out = _solve()(repo_path=repo_path, api_key="offline", n=2)
        assert len(out["plan"]) <= 2
    _with_context(run)
