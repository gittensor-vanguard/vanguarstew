"""Tests for the objective scoring anchor (deterministic, structural)."""

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from benchmark.score import (  # noqa: E402
    actual_bump,
    changed_modules,
    is_release_subject,
    module_recall,
    objective_score,
    parse_semver,
    release_predicted,
    release_signaled,
    semver_bump_level,
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


def test_parse_semver_with_and_without_v():
    assert parse_semver("v1.2.0") == (1, 2, 0)
    assert parse_semver("1.2.0") == (1, 2, 0)
    assert parse_semver("Release v2.10.3") == (2, 10, 3)
    assert parse_semver("no version here") is None
    assert parse_semver("") is None


def test_semver_bump_level_major_minor_patch():
    assert semver_bump_level("1.4.2", "2.0.0") == "major"
    assert semver_bump_level("1.4.2", "1.5.0") == "minor"
    assert semver_bump_level("1.4.2", "1.4.3") == "patch"
    assert semver_bump_level("1.4.2", "1.4.2") is None  # no change
    assert semver_bump_level("v1.0.0", "v1.1.0") == "minor"  # tolerates leading v
    assert semver_bump_level("nope", "1.0.0") is None  # unparseable


def test_actual_bump_from_revealed_window():
    minor = [
        {"subject": "Release v1.4.0", "files": ["CHANGELOG.md"]},
        {"subject": "add feature", "files": ["core/x.py"]},
        {"subject": "Release v1.5.0", "files": ["CHANGELOG.md"]},
    ]
    assert actual_bump(minor) == "minor"
    # a single version in the window can't establish a delta
    assert actual_bump(REVEALED) is None


def test_objective_score_reports_bump_match():
    window = [
        {"subject": "Release v1.0.0", "files": ["CHANGELOG.md"]},
        {"subject": "Release v2.0.0", "files": ["CHANGELOG.md"]},
    ]
    plan = [{"title": "cut the next release", "kind": "release"}]
    hit = objective_score(plan, window, version_bump="major")
    assert hit["bump_actual"] == "major"
    assert hit["bump_match"] is True

    miss = objective_score(plan, window, version_bump="patch")
    assert miss["bump_actual"] == "major"
    assert miss["bump_match"] is False

    # no bump inferable -> bump fields stay neutral (not scored downstream)
    none = objective_score(plan, REVEALED, version_bump="minor")
    assert none["bump_actual"] is None
    assert none["bump_match"] is None
