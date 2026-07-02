"""Tests for the objective scoring anchor (deterministic, structural)."""

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from benchmark.score import (  # noqa: E402
    changed_modules,
    module_recall,
    objective_score,
    release_predicted,
    release_signaled,
)

REVEALED = [
    {"subject": "add plugin loader", "files": ["plugins/loader.py", "README.md"]},
    {"subject": "refactor core engine", "files": ["core/engine.py"]},
    {"subject": "Release v1.2.0", "files": ["CHANGELOG.md"]},
]


def test_changed_modules():
    assert changed_modules(REVEALED) == {"plugins", "readme", "core", "changelog"}


def test_module_recall_matches_by_name():
    plan = [
        {"title": "build plugin system", "theme": "plugins", "kind": "feature"},
        {"title": "update readme", "kind": "docs"},
    ]
    res = module_recall(plan, REVEALED)
    assert set(res["matched_modules"]) == {"plugins", "readme"}
    assert res["module_recall"] == round(2 / 4, 3)  # core, changelog not anticipated


def test_release_signals():
    assert release_signaled(REVEALED) is True
    assert release_predicted([{"title": "cut release", "kind": "release"}]) is True
    assert release_predicted([{"title": "fix bug", "kind": "bugfix"}]) is False


def test_objective_score_shape():
    plan = [{"title": "prepare release v1.2.0", "kind": "release", "theme": "core"}]
    score = objective_score(plan, REVEALED)
    assert "module_recall" in score
    assert score["release_signaled"] is True
    assert score["release_predicted"] is True
    assert score["release_match"] is True


def test_empty_inputs():
    res = module_recall([], [])
    assert res["module_recall"] == 0.0
    assert objective_score([], [])["release_match"] is True  # neither signaled nor predicted
