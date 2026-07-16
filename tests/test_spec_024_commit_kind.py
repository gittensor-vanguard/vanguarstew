"""Contract tests for specs/024-benchmark-commit-kind — assert score.commit_kind and
score.plan_kind satisfy the spec's EARS criteria: input guards, CC/release mapping, plan
vocabulary, and symmetry. Offline, deterministic.
"""

import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from benchmark.score import (  # noqa: E402
    _COMMIT_KIND,
    _PLAN_KIND,
    commit_kind,
    is_release_subject,
    plan_kind,
)

_NON_STRING_SUBJECTS = [None, 42, 3.14, True, [], {}, ()]
_NON_STRING_KINDS = [None, 123, 3.14, True, [], {}, ()]

# Normalized kinds commit_kind may return (excluding None).
COMMIT_KINDS = frozenset(_COMMIT_KIND.values()) | {"release"}

# --- commit_kind input guard --------------------------------------------------------------


@pytest.mark.parametrize("bad", _NON_STRING_SUBJECTS)
def test_commit_kind_non_string_returns_none(bad):
    assert commit_kind(bad) is None


# --- commit_kind conventional-commit prefix ------------------------------------------------


def test_commit_kind_maps_conventional_prefixes():
    assert commit_kind("feat: add plugin loader") == "feat"
    assert commit_kind("Fix(core): guard nil deref") == "fix"
    assert commit_kind("docs!: rewrite readme") == "docs"
    assert commit_kind("refactor(engine): split module") == "refactor"
    assert commit_kind("chore(deps): bump lib") == "chore"
    assert commit_kind("ci: tune workflow") == "ci"
    assert commit_kind("test: cover edge case") == "test"
    assert commit_kind("build: update toolchain") == "build"
    assert commit_kind("style: format files") == "style"
    assert commit_kind("revert: undo bad merge") == "revert"
    assert commit_kind("perf: speed up parser") == "perf"


def test_commit_kind_normalizes_synonyms():
    assert commit_kind("feature: new api") == "feat"
    assert commit_kind("bugfix: patch crash") == "fix"
    assert commit_kind("doc: update guide") == "docs"
    assert commit_kind("tests: add cases") == "test"
    assert commit_kind("dep: bump lodash") == "chore"


# --- commit_kind release subjects ---------------------------------------------------------


def test_commit_kind_release_cuts():
    for subj in (
        "Release v1.2.0",
        "chore(release): 1.4.0",
        "build(release): 2.0.0",
        "chore(main): release 1.2.3",
        "chore: release v3.1.0",
        "chore(release)!: 4.0.0",
    ):
        assert is_release_subject(subj), subj
        assert commit_kind(subj) == "release", subj


def test_commit_kind_non_release_scoped_stays_non_release():
    for subj in (
        "ci(release): update the release pipeline",
        "chore(release): tidy the release script",
        "refactor: release the lock at 3.0",
        "chore(deps): bump lodash to 4.17.21",
        "test(release): cover the release-notes generator",
    ):
        assert not is_release_subject(subj), subj
        assert commit_kind(subj) != "release", subj


# --- commit_kind unclassified subjects ----------------------------------------------------


def test_commit_kind_unclassified_subjects_return_none():
    assert commit_kind("merge branch 'main'") is None
    assert commit_kind("add plugin loader") is None
    assert commit_kind("") is None
    for result in (
        commit_kind("merge branch 'main'"),
        commit_kind("add plugin loader"),
        commit_kind(""),
    ):
        assert result is None or result in COMMIT_KINDS


# --- plan_kind input guard ----------------------------------------------------------------


@pytest.mark.parametrize("bad", _NON_STRING_KINDS)
def test_plan_kind_non_string_returns_none(bad):
    assert plan_kind(bad) is None


# --- plan_kind normalization --------------------------------------------------------------


def test_plan_kind_strips_whitespace_and_case():
    assert plan_kind("Release") == "release"
    assert plan_kind("  RELEASE  ") == "release"
    assert plan_kind("  Feat  ") == "feat"
    assert plan_kind("BUGFIX") == "fix"


# --- plan_kind vocabulary mapping ---------------------------------------------------------


def test_plan_kind_maps_aliases():
    assert plan_kind("feature") == "feat"
    assert plan_kind("bugfix") == "fix"
    assert plan_kind("Docs") == "docs"
    assert plan_kind("dep") == "chore"
    assert plan_kind("release") == "release"
    assert plan_kind("test") == "test"
    assert plan_kind("tests") == "test"
    assert plan_kind("ci") == "ci"
    assert plan_kind("build") == "build"
    assert plan_kind("refactor") == "refactor"
    assert plan_kind("perf") == "perf"
    assert plan_kind("style") == "style"
    assert plan_kind("revert") == "revert"


def test_plan_kind_triage_and_unknown_return_none():
    assert plan_kind("triage") is None
    assert plan_kind("misc") is None
    assert plan_kind("unknown-kind") is None
    assert plan_kind("") is None
    assert "triage" not in _PLAN_KIND


# --- vocabulary symmetry ------------------------------------------------------------------


def test_plan_and_commit_kind_vocabularies_stay_symmetric():
    """Every mapped plan alias must match the commit_kind for its CC prefix counterpart."""
    for alias, target in _PLAN_KIND.items():
        if alias == "triage":
            continue
        assert plan_kind(alias) == target, alias
        assert plan_kind(alias.upper()) == target, alias
        # Commit side: build a minimal CC subject from the normalized kind when possible.
        cc_type = alias if alias in _COMMIT_KIND else alias.split()[0]
        if cc_type in _COMMIT_KIND or alias in ("feature", "bugfix", "bug", "doc", "docs",
                                                  "tests", "dep", "deps"):
            subject = f"{alias}: sample change"
            assert commit_kind(subject) == target, alias


def test_commit_kinds_constant_covers_returns():
    samples = [
        "feat: x", "fix: x", "docs: x", "refactor: x", "perf: x", "test: x",
        "build: x", "ci: x", "chore: x", "style: x", "revert: x", "Release v1.0.0",
    ]
    for subj in samples:
        kind = commit_kind(subj)
        assert kind is not None
        assert kind in COMMIT_KINDS, subj
