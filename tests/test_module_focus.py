"""Tests for the module-churn focus ranking — deterministic, offline.

The frozen checkout is a `git archive` export with no `.git`, so the agent cannot see which
files recent commits touched. These lock the two freeze-T-only signals that stand in for it:
the tree's own shape (`context.module_weights`) and which modules recent subjects name
(`planner._module_attention`), plus the blended ranking the prompt is grounded in.
"""

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

os.environ["VANGUARSTEW_OFFLINE"] = "1"

from agent.context import (  # noqa: E402
    CONTEXT_FILE,
    MODULE_WEIGHT_FILE_LIMIT,
    load_context,
    module_weights,
    top_module,
)
from agent.planner import (  # noqa: E402
    _MODULE_FOCUS_TOP,
    MODULE_FOCUS_GUIDANCE,
    _anchor_tokens,
    _module_attention,
    _module_focus,
    _module_focus_note,
    _module_weights,
)

# --- top_module: must mirror benchmark/score.py::_top_module -------------------------------

def test_top_module_mirrors_the_objective_anchor_normalization():
    from benchmark.score import _top_module as anchor

    for path in ("agent/foo.py", "README.md", ".gitignore", "docs/a/b.rst", "tox.ini",
                 "src/pkg/mod.py", "Makefile", ".pre-commit-config.yaml", "a.b.c.py"):
        assert top_module(path) == anchor(path), path


def test_top_module_rejects_non_strings_and_empty_paths():
    assert top_module(None) is None
    assert top_module(123) is None
    assert top_module("") is None
    assert top_module("///") is None


# --- module_weights: walks the frozen tree -------------------------------------------------

def _tree(tmp_path, files):
    for rel in files:
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("x")
    return str(tmp_path)


def test_module_weights_counts_files_per_top_level_module(tmp_path):
    root = _tree(tmp_path, ["pkg/a.py", "pkg/b.py", "pkg/sub/c.py", "docs/i.rst", "README.md"])
    assert module_weights(root) == {"pkg": 3, "docs": 1, "readme": 1}


def test_module_weights_excludes_the_freeze_artifact_and_git(tmp_path):
    root = _tree(tmp_path, ["pkg/a.py", CONTEXT_FILE, ".git/config", ".git/objects/ab/cd"])
    assert module_weights(root) == {"pkg": 1}


def test_module_weights_degrades_to_empty_on_an_unreadable_path(tmp_path):
    assert module_weights(str(tmp_path / "missing")) == {}
    assert module_weights("") == {}
    assert module_weights(None) == {}
    assert module_weights(123) == {}


def test_module_weights_honors_the_file_limit(tmp_path):
    root = _tree(tmp_path, [f"pkg/f{i}.py" for i in range(10)])
    assert sum(module_weights(root, limit=4).values()) == 4
    assert module_weights(root, limit=0) == {}
    # a bool / negative / non-int limit falls back to the default rather than truncating
    assert sum(module_weights(root, limit=True).values()) == 10
    assert sum(module_weights(root, limit=-1).values()) == 10
    assert sum(module_weights(root, limit="nope").values()) == 10
    assert MODULE_WEIGHT_FILE_LIMIT > 0


def test_load_context_derives_module_weights_from_the_checkout(tmp_path):
    root = _tree(tmp_path, ["pkg/a.py", "docs/i.rst"])
    (tmp_path / CONTEXT_FILE).write_text('{"recent_commits": []}')
    ctx = load_context(root)
    assert ctx["module_weights"] == {"pkg": 1, "docs": 1}


def test_load_context_module_weights_cannot_be_spoofed_by_the_context_file(tmp_path):
    root = _tree(tmp_path, ["pkg/a.py"])
    (tmp_path / CONTEXT_FILE).write_text(
        '{"recent_commits": [], "module_weights": {"invented": 999}}'
    )
    ctx = load_context(root)
    assert ctx["module_weights"] == {"pkg": 1}


# --- planner guards ------------------------------------------------------------------------

def test_planner_module_weights_drops_malformed_entries():
    assert _module_weights({"module_weights": {"a": 3, "b": True, "c": -1, "d": 0,
                                               "e": "2", 7: 5, "  ": 4}}) == {"a": 3}
    assert _module_weights({"module_weights": "nope"}) == {}
    assert _module_weights({}) == {}
    assert _module_weights(None) == {}


# --- attention: subjects are the only per-commit signal -------------------------------------

def test_attention_weights_a_conventional_commit_scope_above_a_bare_mention():
    scoped = _module_attention(
        {"recent_commits": [{"subject": "fix(parser): tighten"}]}, ["parser"])
    bare = _module_attention(
        {"recent_commits": [{"subject": "fix: tighten the parser"}]}, ["parser"])
    assert scoped["parser"] > bare["parser"] > 0


def test_attention_is_recency_weighted_newest_first():
    mods = ["alpha", "beta"]
    # recent_commits is newest-first: alpha named first must outweigh beta named last
    scores = _module_attention({"recent_commits": [
        {"subject": "docs: alpha"}, {"subject": "docs: x"}, {"subject": "docs: beta"},
    ]}, mods)
    assert scores["alpha"] > scores["beta"]


def test_attention_ignores_names_that_are_not_real_modules():
    scores = _module_attention({"recent_commits": [{"subject": "fix(ghost): nope"}]}, ["pkg"])
    assert scores == {}


def test_attention_tolerates_malformed_history():
    ctx = {"recent_commits": [None, 7, {"subject": None}, {"subject": ""}, {"no_subject": 1}]}
    assert _module_attention(ctx, ["pkg"]) == {}
    assert _module_attention({"recent_commits": []}, ["pkg"]) == {}
    assert _module_attention({"recent_commits": [{"subject": "fix: pkg"}]}, []) == {}


def test_anchor_tokens_keeps_short_names_significant_tokens_would_drop():
    # h2 / ci are real curated-set modules; the anchor scores them, so ranking must see them
    assert _anchor_tokens("h2") == {"h2"}
    assert _anchor_tokens(".pre-commit-config") == {"pre", "commit", "config"}
    assert _anchor_tokens(None) == set()


# --- focus ranking -------------------------------------------------------------------------

def test_focus_ranks_by_size_prior_when_no_subject_names_a_module():
    ctx = {"module_weights": {"big": 50, "small": 1}, "recent_commits": []}
    assert _module_focus(ctx)[0] == "big"


def test_focus_lets_subject_attention_promote_a_smaller_module():
    weights = {"big": 40, "small": 20}
    quiet = _module_focus({"module_weights": weights, "recent_commits": []})
    loud = _module_focus({"module_weights": weights, "recent_commits": [
        {"subject": "fix(small): a"}, {"subject": "fix(small): b"}, {"subject": "feat(small): c"},
    ]})
    assert quiet[0] == "big"
    assert loud[0] == "small"


def test_focus_is_capped_and_deterministic():
    ctx = {"module_weights": {f"m{i}": i + 1 for i in range(20)}, "recent_commits": []}
    focus = _module_focus(ctx)
    assert len(focus) == _MODULE_FOCUS_TOP
    assert focus == _module_focus(ctx)
    assert _module_focus(ctx, top=3) == focus[:3]
    # a bool / non-positive / non-int top falls back to the default rather than emptying
    assert len(_module_focus(ctx, top=True)) == _MODULE_FOCUS_TOP
    assert len(_module_focus(ctx, top=0)) == _MODULE_FOCUS_TOP
    assert len(_module_focus(ctx, top="nope")) == _MODULE_FOCUS_TOP


def test_focus_breaks_ties_on_weight_then_name():
    ctx = {"module_weights": {"b": 5, "a": 5, "c": 9}, "recent_commits": []}
    assert _module_focus(ctx) == ["c", "a", "b"]


def test_focus_is_empty_without_usable_weights():
    assert _module_focus({}) == []
    assert _module_focus(None) == []
    assert _module_focus({"module_weights": {}}) == []


# --- the prompt note -----------------------------------------------------------------------

def test_focus_note_names_the_ranking_and_carries_the_guidance():
    note = _module_focus_note({"module_weights": {"pkg": 9, "docs": 2}, "recent_commits": []})
    assert "pkg, docs" in note
    assert MODULE_FOCUS_GUIDANCE in note


def test_focus_note_is_empty_without_weights_so_the_prompt_is_unchanged():
    """A context with no walkable tree must produce the byte-identical prompt it did before."""
    assert _module_focus_note({}) == ""
    assert _module_focus_note(None) == ""
    assert _module_focus_note({"module_weights": {}}) == ""
    assert _module_focus_note({"module_weights": "nope"}) == ""


def test_focus_note_is_wired_into_the_planning_prompt(monkeypatch):
    import agent.planner as planner

    seen = {}

    class _LLM:
        def chat_json(self, system, user, stub=None):
            seen["user"] = user
            return stub

    planner.plan_next_actions(
        {"module_weights": {"pkg": 9, "docs": 2}, "recent_commits": [], "repo_layout": ["pkg/"]},
        {"summary": "s"}, 5, _LLM())
    assert "pkg, docs" in seen["user"]
    assert MODULE_FOCUS_GUIDANCE in seen["user"]
