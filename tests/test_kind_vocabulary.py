"""Kind-vocabulary symmetry for objective scoring (issue #145).

Guards against silent drift between planner plan kinds and the conventional-commit
prefixes ``kind_recall`` recognizes in revealed history.
"""

import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from benchmark.kind_vocab import (  # noqa: E402
    COMMIT_PREFIX_KIND,
    PLAN_ITEM_KIND,
    PLAN_ONLY_KINDS,
    normalize_commit_prefix,
    normalize_plan_kind,
    plan_aliases_for_commit_prefix,
    shared_normalized_kinds,
)
from benchmark.score import commit_kind, kind_recall, plan_kind  # noqa: E402

# Every commit-prefix alias must have at least one plan alias mapping to the same kind.
COMMIT_PREFIX_CASES = sorted(COMMIT_PREFIX_KIND.items())
PLAN_ALIAS_CASES = sorted(PLAN_ITEM_KIND.items())


@pytest.mark.parametrize("prefix,expected", COMMIT_PREFIX_CASES)
def test_commit_prefix_aliases_normalize(prefix, expected):
    assert normalize_commit_prefix(prefix) == expected
    assert normalize_commit_prefix(prefix.upper()) == expected
    assert normalize_commit_prefix(f"  {prefix}  ") == expected


@pytest.mark.parametrize("plan_kind_input,expected", PLAN_ALIAS_CASES)
def test_plan_item_aliases_normalize(plan_kind_input, expected):
    assert normalize_plan_kind(plan_kind_input) == expected
    assert normalize_plan_kind(plan_kind_input.upper()) == expected


@pytest.mark.parametrize("plan_kind_input", sorted(PLAN_ONLY_KINDS))
def test_plan_only_actions_do_not_map_to_commit_kinds(plan_kind_input):
    assert normalize_plan_kind(plan_kind_input) is None
    assert plan_kind(plan_kind_input) is None


@pytest.mark.parametrize("prefix,expected", COMMIT_PREFIX_CASES)
def test_each_commit_prefix_has_plan_coverage(prefix, expected):
    aliases = plan_aliases_for_commit_prefix(prefix)
    assert aliases, f"no plan alias covers commit prefix {prefix!r} -> {expected!r}"
    assert all(normalize_plan_kind(a) == expected for a in aliases)


def test_singular_and_plural_test_aliases_are_symmetric():
    assert normalize_commit_prefix("test") == "test"
    assert normalize_commit_prefix("tests") == "test"
    assert normalize_plan_kind("test") == "test"
    assert normalize_plan_kind("tests") == "test"


def test_dep_and_deps_aliases_map_to_chore():
    for alias in ("dep", "deps"):
        assert normalize_commit_prefix(alias) == "chore"
        assert normalize_plan_kind(alias) == "chore"


def test_shared_normalized_kinds_cover_scoring_vocabulary():
    shared = shared_normalized_kinds()
    assert "feat" in shared
    assert "fix" in shared
    assert "test" in shared
    assert "release" in shared
    assert "chore" in shared


def test_score_helpers_delegate_to_kind_vocab():
    assert commit_kind("feat: add streaming") == "feat"
    assert commit_kind("tests: cover loader edge cases") == "test"
    assert plan_kind("tests") == "test"
    assert plan_kind("feature") == "feat"


def test_kind_recall_credits_plural_tests_plan_kind():
    revealed = [{"subject": "tests: harden parser fixtures", "files": ["tests/test_parser.py"]}]
    plan = [{"title": "add parser tests", "kind": "tests"}]
    res = kind_recall(plan, revealed)
    assert res["actual_kinds"] == ["test"]
    assert res["matched_kinds"] == ["test"]
    assert res["kind_recall"] == 1.0


def test_kind_recall_still_ignores_triage_plan_items():
    revealed = [
        {"subject": "feat: api", "files": ["core/api.py"]},
        {"subject": "fix: bug", "files": ["core/x.py"]},
    ]
    plan = [
        {"title": "ship api", "kind": "feature"},
        {"title": "review queue", "kind": "triage"},
    ]
    res = kind_recall(plan, revealed)
    assert res["kind_recall"] == 0.5
    assert "triage" not in res["matched_kinds"]


@pytest.mark.parametrize(
    "subject,plan_item_kind",
    [
        ("feat: streaming api", "feature"),
        ("fix(scope): race", "bugfix"),
        ("docs: readme", "docs"),
        ("refactor: split module", "refactor"),
        ("perf: cache lookups", "perf"),
        ("tests: add coverage", "tests"),
        ("build: pin toolchain", "build"),
        ("ci: split workflow", "ci"),
        ("chore: tidy imports", "chore"),
        ("dep: bump requests", "dep"),
        ("Release v2.0.0", "release"),
    ],
)
def test_plan_and_commit_vocabulary_align_for_kind_recall(subject, plan_item_kind):
    revealed = [{"subject": subject, "files": ["core/x.py"]}]
    plan = [{"title": "anticipated work", "kind": plan_item_kind}]
    assert kind_recall(plan, revealed)["kind_recall"] == 1.0
