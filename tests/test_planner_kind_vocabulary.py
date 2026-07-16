"""Planner plan-kind vocabulary vs. the objective anchor (#1687) — deterministic, offline.

`kind_recall` compares `plan_kind(item["kind"])` against `commit_kind(revealed_subject)`. A kind
the anchor scores but a plan item cannot name is pinned at 0 recall for any repo whose work lands
under it, however well the plan reads the repo. These lock the two vocabularies together, from
both directions, so the gap cannot silently reopen.

The alignment is asserted here rather than in `agent/` because `agent/` must not import
`benchmark/` (a miner-only split is planned); the test suite is the seam that may see both.
"""

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

os.environ["VANGUARSTEW_OFFLINE"] = "1"

import pytest  # noqa: E402

from agent.planner import (  # noqa: E402
    _PLAN_KINDS,
    OBJECTIVE_ANCHOR_GUIDANCE,
    PLAN_ITEM_SCHEMA,
    _commit_plan_kind,
    _normalize_plan_item,
    _recent_kinds_note,
)
from benchmark.score import _COMMIT_KIND, plan_kind  # noqa: E402

# The six the anchor scores that no plan item could previously express (#1687).
_PREVIOUSLY_UNEXPRESSIBLE = ("build", "ci", "test", "perf", "style", "revert")


def _expressible_commit_kinds() -> set:
    """Commit kinds reachable from some plan kind; `triage` maps to None by design."""
    return {plan_kind(k) for k in _PLAN_KINDS} - {None}


def test_every_commit_kind_the_anchor_scores_is_expressible_by_a_plan_item():
    # The bug: `build`/`ci`/`test`/`perf`/`style`/`revert` were scoreable but unplannable,
    # so kind_recall was structurally 0 on any repo whose window landed under one of them.
    assert set(_COMMIT_KIND.values()) <= _expressible_commit_kinds()


def test_every_non_triage_plan_kind_maps_to_a_commit_kind_the_anchor_scores():
    # The mirror direction: a plan kind the anchor cannot score is dead weight in the prompt.
    for kind in _PLAN_KINDS - {"triage"}:
        assert plan_kind(kind) in set(_COMMIT_KIND.values()), kind


def test_triage_stays_unmapped():
    # `triage` is a maintainer action, not a commit kind — it must not become scoreable.
    assert "triage" in _PLAN_KINDS
    assert plan_kind("triage") is None


@pytest.mark.parametrize("kind", _PREVIOUSLY_UNEXPRESSIBLE)
def test_normalize_preserves_kinds_the_anchor_scores(kind):
    # Previously coerced to "triage", which `plan_kind` maps to None -> unscoreable.
    assert _normalize_plan_item({"title": "work", "kind": kind})["kind"] == kind


@pytest.mark.parametrize(
    ("subject", "expected"),
    [
        ("ci: bump actions/checkout from 6.0.2 to 6.0.3", "ci"),
        ("build: switch to hatchling backend", "build"),
        ("test: cover the loader edge case", "test"),
        ("tests(scope): add regression case", "test"),
        ("perf: avoid a second pass over the index", "perf"),
        ("style: reformat with the new ruff rules", "style"),
        ("revert: undo the cache change", "revert"),
    ],
)
def test_commit_plan_kind_reads_the_types_the_anchor_classifies(subject, expected):
    # Read side: these types were dropped, so `_recent_kinds_note` could not report them.
    assert _commit_plan_kind(subject) == expected


def test_recent_kinds_note_reports_ci_churn():
    # pluggy's most common frozen type is `ci` (9/50) and the note never mentioned it (#1687).
    ctx = {"recent_commits": [{"subject": "ci: bump actions/checkout"} for _ in range(9)]}
    assert "ci (9)" in _recent_kinds_note(ctx)


@pytest.mark.parametrize(
    "subject",
    ["build(release): 2.0.0", "chore(release): 1.4.0", "chore: release v1.2.3"],
)
def test_release_cuts_still_outrank_their_literal_type(subject):
    # Regression guard: `build`/`chore` now map to themselves, but a version-cut body must
    # still read as a release — matching how the anchor classifies it.
    assert _commit_plan_kind(subject) == "release"


def test_plan_item_schema_advertises_every_plan_kind():
    # The prompt is the only place the model learns the vocabulary; a kind absent here is
    # one the model will never emit, so the map change alone would be inert.
    for kind in _PLAN_KINDS:
        assert f'"{kind}"' in PLAN_ITEM_SCHEMA, kind


def test_objective_anchor_guidance_names_the_upkeep_kinds():
    for kind in ("build", "ci", "test", "perf", "style", "revert"):
        assert kind in OBJECTIVE_ANCHOR_GUIDANCE, kind
