"""Structural grounding for the objective anchor (#1535).

The benchmark's deterministic anchor scores ``module_recall``: did the plan anticipate the
top-level modules that actually changed next? A plan can have the right direction yet score low
because its items never name a real module.

Two knowable-at-T signals close that gap:

- ``repo_layout``    -- the repo's real top-level modules, read from the frozen checkout;
- ``module_activity`` -- those modules ranked by recent Conventional-Commit scope frequency.

Both are leakage-safe (the checkout is the tree *at* T; the subjects are already scrubbed), and
grounding flows through the existing ``files`` field rather than a new scored one, so no new
farmable surface is introduced.

The signal that makes honest grounding easy also makes shotgunning easy -- naming every module in
the layout would match every changed module and farm recall to 1.0 -- so the planner caps ``files``
per item (``MAX_PLAN_ITEM_FILES``). These tests pin both halves: the grounding, and the guard.
"""

import json
import os
import shutil
import subprocess
import tempfile

import pytest

from agent.context import (
    CONTEXT_FILE,
    context_for_agent,
    load_context,
    module_activity,
    repo_layout,
)
from agent.philosophy import _render as render_philosophy_context
from agent.planner import (
    MAX_PLAN_ITEM_FILES,
    OBJECTIVE_ANCHOR_GUIDANCE,
    _normalize_files,
    _normalize_plan_item,
)
from agent.planner import _render as render_planner_context
from benchmark.score import module_recall

# --- repo_layout -----------------------------------------------------------------------------

def test_repo_layout_lists_real_top_level_modules_and_skips_noise(tmp_path):
    for d in ("agent", "benchmark", "scripts", "__pycache__", "node_modules", "build"):
        (tmp_path / d).mkdir()
    (tmp_path / ".git").mkdir()               # hidden -- excluded
    (tmp_path / "vanguarstew.egg-info").mkdir()
    (tmp_path / "README.md").write_text("x", encoding="utf-8")  # a file, not a module

    assert repo_layout(str(tmp_path)) == ["agent", "benchmark", "scripts"]


def test_repo_layout_is_capped(tmp_path):
    for i in range(12):
        (tmp_path / f"mod{i:02d}").mkdir()

    assert repo_layout(str(tmp_path), limit=5) == [f"mod{i:02d}" for i in range(5)]


def test_repo_layout_degrades_to_empty_on_an_unreadable_path():
    assert repo_layout(os.path.join("does", "not", "exist")) == []


# --- module_activity -------------------------------------------------------------------------

def test_module_activity_ranks_modules_by_recent_scope_frequency():
    commits = [
        {"subject": "fix(scripts): a"},
        {"subject": "feat(scripts): b"},
        {"subject": "fix(benchmark): c"},
        {"subject": "chore(agent)!: d"},        # breaking-change marker still parses
        {"subject": "fix(agent/context): e"},   # nested scope -> top-level module
        {"subject": "docs: no scope here"},     # unscoped -> contributes nothing
    ]

    # scripts x2, agent x2, benchmark x1 -- ties broken by first-seen (Counter.most_common)
    assert module_activity(commits) == ["scripts", "agent", "benchmark"]


def test_module_activity_drops_scopes_that_are_not_real_top_level_modules():
    """A commit scope is free text; only the ones that are real modules can score.

    `fix(runner):` names benchmark/runner.py and `fix(ci):` a workflow -- neither is a top-level
    module, so the anchor (which keys on the first path segment) could never match them. Ranking
    them would point the planner at names that cannot score.
    """
    commits = [
        {"subject": "fix(runner): x"},      # benchmark/runner.py -- not top-level
        {"subject": "fix(runner): y"},
        {"subject": "fix(ci): z"},          # a workflow -- not top-level
        {"subject": "fix(benchmark): w"},
    ]
    layout = ["agent", "benchmark", "scripts"]

    assert module_activity(commits, layout) == ["benchmark"]
    # With no layout to check against, the raw ranking is kept rather than dropping the signal.
    assert module_activity(commits) == ["runner", "ci", "benchmark"]


def test_module_activity_is_empty_when_the_repo_does_not_use_scopes():
    assert module_activity([{"subject": "add a thing"}, {"subject": "Merge branch 'x'"}]) == []


def test_module_activity_tolerates_malformed_context():
    assert module_activity(None) == []
    assert module_activity("nope") == []
    assert module_activity([None, "str", 7, {"subject": 123}, {"no_subject": "x"}]) == []


def test_module_activity_is_capped():
    commits = [{"subject": f"fix(mod{i}): x"} for i in range(10)]

    assert len(module_activity(commits, limit=3)) == 3


# --- context wiring --------------------------------------------------------------------------

def test_context_for_agent_exposes_both_signals():
    view = context_for_agent({
        "repo_layout": ["agent", "benchmark"],
        "recent_commits": [
            {"subject": "fix(agent): x"},
            {"subject": "feat(agent): y"},
            {"subject": "fix(benchmark): z"},
        ],
    })

    assert view["repo_layout"] == ["agent", "benchmark"]
    assert view["module_activity"] == ["agent", "benchmark"]   # agent x2 > benchmark x1


def test_context_for_agent_degrades_a_malformed_layout_rather_than_propagating_it():
    assert context_for_agent({"repo_layout": "oops"})["repo_layout"] == []
    assert context_for_agent({})["repo_layout"] == []
    assert context_for_agent({})["module_activity"] == []


@pytest.mark.skipif(shutil.which("git") is None, reason="git required")
def test_load_context_attaches_the_layout_to_a_frozen_context_file():
    repo = tempfile.mkdtemp()
    try:
        subprocess.run(["git", "-C", repo, "init", "-q"], check=True)
        os.mkdir(os.path.join(repo, "benchmark"))
        with open(os.path.join(repo, CONTEXT_FILE), "w", encoding="utf-8") as f:
            json.dump({"_source": "github-api", "recent_commits": []}, f)

        ctx = load_context(repo)

        assert ctx["_source"] == "github-api"          # file content preserved verbatim...
        assert ctx["repo_layout"] == ["benchmark"]     # ...plus the layout, read from the checkout
    finally:
        shutil.rmtree(repo, ignore_errors=True)


# --- prompt surface --------------------------------------------------------------------------

def test_both_prompts_carry_the_grounding_signals():
    context = {
        "repo_layout": ["agent", "benchmark"],
        "recent_commits": [{"subject": "fix(agent): x"}],
    }

    for render in (render_planner_context, render_philosophy_context):
        payload = json.loads(render(context))
        assert payload["repo_layout"] == ["agent", "benchmark"]
        assert payload["module_activity"] == ["agent"]


def test_planner_guidance_steers_to_the_real_layout_and_warns_against_shotgunning():
    assert "repo_layout" in OBJECTIVE_ANCHOR_GUIDANCE
    assert "module_activity" in OBJECTIVE_ANCHOR_GUIDANCE
    assert "ONLY" in OBJECTIVE_ANCHOR_GUIDANCE   # name only what an item genuinely touches


# --- anti-farming guard ----------------------------------------------------------------------

def test_normalize_files_truncates_a_shotgunned_list():
    paths = [f"mod{i}/" for i in range(MAX_PLAN_ITEM_FILES + 4)]

    assert _normalize_files(paths) == paths[:MAX_PLAN_ITEM_FILES]


def test_normalize_files_leaves_an_honest_item_untouched():
    paths = ["agent/planner.py", "tests/test_planner.py"]

    assert _normalize_files(paths) == paths


def test_plan_item_files_are_capped():
    item = _normalize_plan_item({
        "title": "Touch everything",
        "kind": "refactor",
        "files": [f"mod{i}/" for i in range(20)],
    })

    assert len(item["files"]) == MAX_PLAN_ITEM_FILES


def test_the_cap_stops_a_shotgunned_plan_from_farming_module_recall():
    """The guard has to hold at the *scoring* boundary, not just in the normalizer.

    A single item naming every module in the layout would otherwise match every module that
    actually changed and drive module_recall to a perfect 1.0 while predicting nothing.
    """
    revealed = [
        {"files": ["agent/planner.py"]},
        {"files": ["benchmark/score.py"]},
        {"files": ["scripts/run_eval.py"]},
        {"files": ["docs/architecture.md"]},
        {"files": ["tests/test_score.py"]},
        {"files": ["blog/post.md"]},
        {"files": ["specs/001/spec.md"]},
    ]
    layout = ["agent", "benchmark", "scripts", "docs", "tests", "blog", "specs"]

    # Ungoverned: the raw shotgun matches every changed module.
    farmed = [{"title": "Improve the repo", "kind": "refactor", "files": layout}]
    assert module_recall(farmed, revealed)["module_recall"] == 1.0

    # Through the planner's normalizer, the same item is capped and cannot sweep the anchor.
    capped = [_normalize_plan_item(dict(farmed[0]))]
    assert module_recall(capped, revealed)["module_recall"] < 1.0

    # An honest, focused prediction still scores exactly what it earned.
    honest = [_normalize_plan_item({
        "title": "Fix the planner",
        "kind": "bugfix",
        "files": ["agent/planner.py"],
    })]
    assert module_recall(honest, revealed)["matched_modules"] == ["agent"]
