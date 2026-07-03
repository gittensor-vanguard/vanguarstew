"""Tests for the objective scoring anchor (deterministic, structural)."""

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from benchmark.score import (  # noqa: E402
    changed_modules,
    is_release_subject,
    module_file_counts,
    module_recall,
    objective_score,
    release_predicted,
    release_signaled,
    weighted_module_recall,
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
    assert weighted_module_recall([], [])["weighted_module_recall"] == 0.0


def test_weighted_module_recall_weights_by_file_count():
    revealed = [
        {"subject": "expand benchmark", "files": [
            "benchmark/a.py", "benchmark/b.py", "benchmark/c.py", "docs/note.md",
        ]},
    ]
    assert module_file_counts(revealed) == {"benchmark": 3, "docs": 1}
    plan = [{"title": "improve benchmark scoring", "theme": "benchmark", "kind": "feature"}]
    res = weighted_module_recall(plan, revealed)
    assert res["weighted_matched_modules"] == ["benchmark"]
    assert res["weighted_module_recall"] == round(3 / 4, 3)
    assert module_recall(plan, revealed)["module_recall"] == 0.5  # 1 of 2 modules


def test_objective_score_includes_weighted_module_recall():
    plan = [{"title": "prepare release v1.2.0", "kind": "release", "theme": "core"}]
    score = objective_score(plan, REVEALED)
    assert "weighted_module_recall" in score
    assert "module_weights" in score
    assert "weighted_matched_modules" in score


def test_is_release_subject_accepts_genuine_releases():
    assert is_release_subject("Release v1.2.0")
    assert is_release_subject("v1.2.0")
    assert is_release_subject("1.2.0")
    assert is_release_subject("release: 2.0.0")
    assert is_release_subject("bump version to 2.0.0")
    assert is_release_subject("update the changelog for the next cut")


def test_is_release_subject_rejects_incidental_versions():
    # Dependency bumps and version mentions are NOT releases.
    assert not is_release_subject("chore(deps): bump lodash to v4.17.21")
    assert not is_release_subject("upgrade numpy to 1.26.4")
    assert not is_release_subject("fix crash in v1.2.0 parser")
    assert not is_release_subject("docs: mention support for Python 3.11.0")
    assert not is_release_subject("add retry logic")


def test_release_signaled_ignores_dependency_bumps():
    dep_bumps = [
        {"subject": "chore(deps): bump lodash to v4.17.21", "files": ["package.json"]},
        {"subject": "upgrade numpy to 1.26.4", "files": ["requirements.txt"]},
    ]
    assert release_signaled(dep_bumps) is False
    # A genuine release in the window is still detected.
    assert release_signaled(dep_bumps + [{"subject": "Release v2.0.0", "files": ["CHANGELOG.md"]}])


def test_release_predicted_ignores_inline_version_but_honors_kind():
    assert release_predicted([{"title": "bump pytest to 8.0.0", "kind": "dep"}]) is False
    assert release_predicted([{"title": "prepare v1.2.0", "kind": "release"}]) is True   # kind
    assert release_predicted([{"title": "Release v1.2.0", "kind": "misc"}]) is True      # subject


def test_objective_score_no_false_release_match_on_dep_bumps():
    # Window is only dep bumps; a plan that mentions a version must not score a release match.
    revealed = [{"subject": "chore(deps): bump lodash to v4.17.21", "files": ["package.json"]}]
    plan = [{"title": "upgrade deps to 2.0.0", "kind": "dep", "theme": "deps"}]
    score = objective_score(plan, revealed)
    assert score["release_signaled"] is False
    assert score["release_predicted"] is False
    assert score["release_match"] is True   # both correctly False -> agree
