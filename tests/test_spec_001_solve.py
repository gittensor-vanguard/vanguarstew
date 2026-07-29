"""Contract tests for specs/001-solve-contract — assert agent.py::solve satisfies the spec's
EARS criteria: stable entrypoint signature, offline determinism, and full output shape. Offline,
deterministic; no network is used.
"""

import importlib.util
import inspect
import json
import os
import shutil
import sys
import tempfile
from urllib.error import URLError

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

os.environ["VANGUARSTEW_OFFLINE"] = "1"

from agent.context import load_context  # noqa: E402
from agent.decider import VALID_ACTIONS, decide  # noqa: E402
from agent.llm import LLM  # noqa: E402
from agent.philosophy import _OFFLINE_STUB, infer_philosophy  # noqa: E402
from agent.planner import _offline_plan_stub, plan_next_actions  # noqa: E402
from benchmark.runner import load_solve  # noqa: E402

_AGENT_FILE = os.path.join(ROOT, "agent.py")

_DECISION_STUB = {
    "action": "plan",
    "labels": [],
    "reviewer": None,
    "version_bump": None,
    "patch": None,
    "rationale": "offline stub decision",
}

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
    return load_solve(_AGENT_FILE)


def _agent_entry():
    """Load ``agent.py`` as a module (distinct from the ``agent/`` package)."""
    spec = importlib.util.spec_from_file_location("vanguarstew_agent_entry", _AGENT_FILE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


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


# --- Step isolation (issue #2207) -----------------------------------------------------------

def _build_expected_solve_output(context, philosophy, plan, decision, *, n: int) -> dict:
    return {
        "philosophy": philosophy,
        "plan": plan,
        "action": decision.get("action"),
        "labels": decision.get("labels", []),
        "reviewer": decision.get("reviewer"),
        "version_bump": decision.get("version_bump"),
        "patch": decision.get("patch"),
        "rationale": decision.get("rationale"),
        "logs": f"philosophy+plan({len(plan)})+decision",
        "steps": 3,
        "cost": None,
        "success": True,
    }


def test_solve_success_path_matches_unwrapped_orchestration():
    """When every step succeeds, solve() output matches direct four-step assembly."""

    def run(repo_path):
        request = "plan the next 5 maintainer actions"
        n = 3
        llm = LLM(api_key="offline")
        context = load_context(repo_path)
        philosophy = infer_philosophy(context, llm)
        plan = plan_next_actions(context, philosophy, n, llm)
        decision = decide(context, philosophy, request, llm)
        expected = _build_expected_solve_output(context, philosophy, plan, decision, n=n)
        entry = _agent_entry()
        out = entry.solve(repo_path=repo_path, request=request, api_key="offline", n=n)
        for key, value in expected.items():
            assert out[key] == value
        _assert_solve_shape(out)
    _with_context(run)


def _marker_plan():
    return [{
        "title": "survived plan item",
        "kind": "triage",
        "rationale": "downstream step ran",
        "theme": "test",
    }]


def _marker_decision():
    return {
        "action": "triage",
        "labels": ["survivor"],
        "reviewer": "@keeper",
        "version_bump": None,
        "patch": None,
        "rationale": "downstream decision ran",
    }


def test_solve_load_context_failure_uses_empty_context_and_runs_other_steps(monkeypatch):
    seen = {}

    def run(repo_path):
        def fake_load(_repo_path):
            raise URLError("transport blip")

        def fake_infer(ctx, llm):
            seen["context"] = ctx
            return dict(_OFFLINE_STUB)

        def fake_plan(ctx, ph, n, llm):
            seen["philosophy"] = ph
            return _marker_plan()

        def fake_decide(ctx, ph, request, llm):
            seen["plan_ctx"] = ctx
            return _marker_decision()

        entry = _agent_entry()
        monkeypatch.setattr(entry, "load_context", fake_load)
        monkeypatch.setattr(entry, "infer_philosophy", fake_infer)
        monkeypatch.setattr(entry, "plan_next_actions", fake_plan)
        monkeypatch.setattr(entry, "decide", fake_decide)

        out = entry.solve(repo_path=repo_path, api_key="offline", n=1)
        assert seen["context"] == {}
        assert seen["philosophy"] == dict(_OFFLINE_STUB)
        assert seen["plan_ctx"] == {}
        assert out["plan"] == _marker_plan()
        assert out["action"] == "triage"
        assert out["labels"] == ["survivor"]
    _with_context(run)


def test_solve_infer_philosophy_failure_uses_stub_and_runs_other_steps(monkeypatch):
    seen = {}

    def run(repo_path):
        marker_ctx = {**_MIN_CONTEXT, "survivor": "context"}

        def fake_infer(ctx, llm):
            seen["context"] = ctx
            raise URLError("transport blip")

        def fake_plan(ctx, ph, n, llm):
            seen["context"] = ctx
            seen["philosophy"] = ph
            return _marker_plan()

        def fake_decide(ctx, ph, request, llm):
            seen["plan"] = True
            return _marker_decision()

        entry = _agent_entry()
        monkeypatch.setattr(entry, "load_context", lambda rp: dict(marker_ctx))
        monkeypatch.setattr(entry, "infer_philosophy", fake_infer)
        monkeypatch.setattr(entry, "plan_next_actions", fake_plan)
        monkeypatch.setattr(entry, "decide", fake_decide)

        out = entry.solve(repo_path=repo_path, api_key="offline", n=1)
        assert seen["context"] == marker_ctx
        assert seen["philosophy"] == dict(_OFFLINE_STUB)
        assert seen["plan"] is True
        assert out["philosophy"] == dict(_OFFLINE_STUB)
        assert out["plan"] == _marker_plan()
        assert out["action"] == "triage"
    _with_context(run)


def test_solve_plan_failure_uses_stub_and_runs_other_steps(monkeypatch):
    seen = {}

    def run(repo_path):
        marker_ctx = {**_MIN_CONTEXT, "survivor": "context"}
        marker_phil = {**dict(_OFFLINE_STUB), "summary": "survived philosophy"}

        def fake_plan(ctx, ph, n, llm):
            seen["context"] = ctx
            seen["philosophy"] = ph
            raise URLError("transport blip")

        def fake_decide(ctx, ph, request, llm):
            seen["context"] = ctx
            seen["philosophy"] = ph
            return _marker_decision()

        entry = _agent_entry()
        monkeypatch.setattr(entry, "load_context", lambda rp: dict(marker_ctx))
        monkeypatch.setattr(entry, "infer_philosophy", lambda ctx, llm: dict(marker_phil))
        monkeypatch.setattr(entry, "plan_next_actions", fake_plan)
        monkeypatch.setattr(entry, "decide", fake_decide)

        out = entry.solve(repo_path=repo_path, api_key="offline", n=2)
        assert seen["context"] == marker_ctx
        assert seen["philosophy"] == marker_phil
        assert out["philosophy"] == marker_phil
        assert out["plan"] == _offline_plan_stub(marker_ctx, 2)
        assert out["action"] == "triage"
    _with_context(run)


def test_solve_decide_failure_uses_stub_and_retains_prior_steps(monkeypatch):
    def run(repo_path):
        marker_ctx = {**_MIN_CONTEXT, "survivor": "context"}
        marker_phil = {**dict(_OFFLINE_STUB), "summary": "survived philosophy"}
        marker_plan = _marker_plan()

        entry = _agent_entry()
        monkeypatch.setattr(entry, "load_context", lambda rp: dict(marker_ctx))
        monkeypatch.setattr(entry, "infer_philosophy", lambda ctx, llm: dict(marker_phil))
        monkeypatch.setattr(entry, "plan_next_actions", lambda ctx, ph, n, llm: list(marker_plan))
        monkeypatch.setattr(
            entry,
            "decide",
            lambda ctx, ph, request, llm: (_ for _ in ()).throw(URLError("transport blip")),
        )

        out = entry.solve(repo_path=repo_path, api_key="offline", n=1)
        assert out["philosophy"] == marker_phil
        assert out["plan"] == marker_plan
        assert out["action"] == _DECISION_STUB["action"]
        assert out["labels"] == _DECISION_STUB["labels"]
        assert out["reviewer"] == _DECISION_STUB["reviewer"]
        assert out["version_bump"] == _DECISION_STUB["version_bump"]
        assert out["patch"] == _DECISION_STUB["patch"]
        assert out["rationale"] == _DECISION_STUB["rationale"]
    _with_context(run)
