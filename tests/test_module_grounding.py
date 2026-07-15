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
    MIN_PLAN_MODULE_BUDGET,
    OBJECTIVE_ANCHOR_GUIDANCE,
    _enforce_module_budget,
    _normalize_files,
    _normalize_plan_item,
    _top_module,
)
from agent.planner import _render as render_planner_context
from benchmark.score import _top_module as score_top_module
from benchmark.score import module_recall

# A repo whose revealed window touched every module in its layout -- so an ungoverned shotgun
# would score a perfect module_recall and an honest plan has real modules to get right.
_LAYOUT = ("agent", "benchmark", "scripts", "docs", "tests", "blog", "specs", "tools")
_REVEALED = [{"files": [f"{module}/x.py"]} for module in _LAYOUT]

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


def test_top_module_matches_the_scorer():
    """The budget must count modules exactly as the anchor does, or it guards the wrong unit.

    ``agent/`` cannot import ``benchmark/``, so the derivation is duplicated; this pins the two
    copies together (the same alignment discipline as tests/test_scrubber_alignment.py).
    """
    for path in (
        "agent/planner.py", "benchmark/score.py", "docs/", "README.md", ".gitignore",
        "a/b/c.py", "Makefile", "", "tests/unit/test_x.py",
    ):
        assert _top_module(path) == score_top_module(path), path


def test_the_cap_stops_a_single_item_shotgun_from_farming_module_recall():
    """The guard has to hold at the *scoring* boundary, not just in the normalizer."""
    # Ungoverned: the raw shotgun matches every changed module.
    farmed = [{"title": "Improve the repo", "kind": "refactor", "files": list(_LAYOUT)}]
    assert module_recall(farmed, _REVEALED)["module_recall"] == 1.0

    # Through the planner's normalizer, the same item is capped and cannot sweep the anchor.
    capped = [_normalize_plan_item(dict(farmed[0]))]
    assert module_recall(capped, _REVEALED)["module_recall"] < 1.0


def test_the_budget_stops_a_MULTI_item_shotgun_the_per_item_cap_cannot():
    """The farmable unit is the plan-wide distinct-module set, not the per-item file list.

    module_recall tokenizes the *whole plan*, so a per-item cap alone is defeated by simply
    spreading the layout across several items -- five items naming five modules each still sweeps
    every module. This is why the budget exists.
    """
    # Spread the layout across 4 items, each within MAX_PLAN_ITEM_FILES.
    spread = [
        _normalize_plan_item({"title": f"item {i}", "kind": "refactor",
                              "files": list(_LAYOUT[i * 2:i * 2 + 2])})
        for i in range(4)
    ]
    # The per-item cap alone leaves the anchor fully farmed...
    assert module_recall(spread, _REVEALED)["module_recall"] == 1.0

    # ...but the plan-wide budget bounds the distinct modules the plan may claim.
    governed = _enforce_module_budget([dict(item) for item in spread])
    named = {_top_module(p) for item in governed for p in item.get("files", [])}
    assert len(named) <= max(MIN_PLAN_MODULE_BUDGET, len(governed) + 1)
    assert module_recall(governed, _REVEALED)["module_recall"] < 1.0


def test_the_budget_leaves_an_honest_plan_untouched():
    """A focused plan spends few distinct modules however long it is, so it never hits the cap."""
    honest = [
        {"title": "Fix the planner", "kind": "bugfix",
         "files": ["agent/planner.py", "tests/test_planner.py"]},
        {"title": "Harden the scorer", "kind": "bugfix",
         "files": ["agent/context.py", "tests/test_context.py"]},
        {"title": "Review the open queue", "kind": "triage"},
    ]
    before = [dict(item) for item in honest]

    assert _enforce_module_budget(honest) == before          # nothing dropped
    assert module_recall(honest, _REVEALED)["matched_modules"] == ["agent", "tests"]


def test_the_budget_keeps_the_earliest_highest_conviction_modules():
    plan = [
        {"title": "a", "files": ["agent/x.py"]},
        {"title": "b", "files": ["benchmark/y.py"]},
        {"title": "c", "files": ["docs/z.md"]},
        {"title": "d", "files": ["blog/w.md"]},      # 4 items -> budget 5, still admitted
    ]
    _enforce_module_budget(plan)
    assert [item.get("files") for item in plan] == [
        ["agent/x.py"], ["benchmark/y.py"], ["docs/z.md"], ["blog/w.md"],
    ]

    # A single item may not spend the whole budget on new modules beyond it.
    tight = [{"title": "only", "files": [f"{m}/x.py" for m in _LAYOUT]}]
    _enforce_module_budget(tight)
    assert len(tight[0]["files"]) == MIN_PLAN_MODULE_BUDGET   # 1 item -> floor of 3
