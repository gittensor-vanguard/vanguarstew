"""Tests for the objective scoring anchor (deterministic, structural)."""

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from benchmark.score import (  # noqa: E402
    addressed_issues,
    backlog_recall,
    base_from_releases,
    bump_level,
    changed_modules,
    commit_kind,
    is_release_subject,
    kind_recall,
    module_recall,
    objective_score,
    parse_semver,
    plan_kind,
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


def test_module_recall_honors_plan_files_without_title_overlap():
    revealed = [{"subject": "fix: race in loader", "files": ["core/loader.py"]}]
    vague_title = [{"title": "harden concurrency", "kind": "bugfix"}]
    with_files = [{"title": "harden concurrency", "kind": "bugfix", "files": ["core/loader.py"]}]
    assert module_recall(vague_title, revealed)["module_recall"] == 0.0
    assert module_recall(with_files, revealed)["module_recall"] == 1.0


def test_backlog_recall_honors_plan_files_for_issue_titles():
    open_issues = [{"number": 7, "title": "Race in core loader"}]
    revealed = [{"subject": "fix: race in core loader", "files": ["core/loader.py"]}]
    plan = [{"title": "address backlog item", "kind": "bugfix", "files": ["core/loader.py"]}]
    res = backlog_recall(plan, revealed, open_issues)
    assert res["matched_issue_numbers"] == [7]
    assert res["backlog_recall"] == 1.0


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
    assert backlog_recall([], [], [])["backlog_recall"] == 0.0


def test_backlog_recall_matches_addressed_issues():
    open_issues = [
        {"number": 12, "title": "Memory leak under load"},
        {"number": 15, "title": "Support YAML config"},
        {"number": 99, "title": "Unrelated roadmap item"},
    ]
    revealed = [
        {"subject": "fix: memory leak under heavy load", "files": []},
        {"subject": "docs: tweak readme", "files": []},
    ]
    assert [i["number"] for i in addressed_issues(revealed, open_issues)] == [12]
    plan = [{"title": "Fix memory leak under load", "kind": "bugfix"}]
    res = backlog_recall(plan, revealed, open_issues)
    assert res["matched_issue_numbers"] == [12]
    assert res["backlog_recall"] == 1.0
    score = objective_score(plan, revealed, open_issues=open_issues)
    assert score["backlog_recall"] == 1.0


def test_git_only_backlog_does_not_change_core_objective_score():
    """Empty or unaddressed backlog must not shift module/release/bump signals."""
    plan = [{"title": "build plugin system", "theme": "plugins", "kind": "feature"}]
    baseline = objective_score(plan, REVEALED)
    with_empty = objective_score(plan, REVEALED, open_issues=[])
    with_unaddressed = objective_score(plan, REVEALED, open_issues=[
        {"number": 1, "title": "Future feature nobody touched"},
    ])
    for score in (with_empty, with_unaddressed):
        assert score["module_recall"] == baseline["module_recall"]
        assert score["kind_recall"] == baseline["kind_recall"]
        assert score["release_signaled"] == baseline["release_signaled"]
        assert score["release_predicted"] == baseline["release_predicted"]
        assert score["release_match"] == baseline["release_match"]
        assert score["backlog_recall"] == 0.0
        assert score["matched_issue_numbers"] == []
        assert score["addressed_backlog_diagnostics"] == []


def test_addressed_backlog_diagnostics_show_number_title_and_matched_subject():
    """#135: human-readable evidence for maintainer-facing inspection, additive only."""
    open_issues = [
        {"number": 12, "title": "Memory leak under load"},
        {"number": 15, "title": "Support YAML config"},
    ]
    revealed = [
        {"subject": "fix: memory leak under heavy load", "files": []},
        {"subject": "docs: tweak readme", "files": []},
    ]
    res = backlog_recall([], revealed, open_issues)
    assert res["addressed_backlog_diagnostics"] == [
        {
            "number": 12,
            "title": "Memory leak under load",
            "matched_subject": "fix: memory leak under heavy load",
        }
    ]
    # diagnostics don't change scoring: same recall/matched numbers with or without them
    assert res["backlog_recall"] == 0.0  # empty plan anticipates nothing
    assert res["addressed_issue_numbers"] == [12]


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


def test_parse_semver_with_and_without_leading_v():
    assert parse_semver("v1.2.0") == (1, 2, 0)
    assert parse_semver("1.2.0") == (1, 2, 0)
    assert parse_semver("Release v2.0.0") == (2, 0, 0)  # embedded in a subject line
    assert parse_semver("1.4") == (1, 4, 0)             # missing patch -> 0
    assert parse_semver("v3.1.4-rc2") == (3, 1, 4)      # pre-release suffix ignored
    assert parse_semver("no version here") is None


def test_bump_level_major_minor_patch():
    assert bump_level((1, 2, 3), (2, 0, 0)) == "major"
    assert bump_level((1, 2, 3), (1, 3, 0)) == "minor"
    assert bump_level((1, 2, 3), (1, 2, 4)) == "patch"
    assert bump_level((1, 2, 3), (1, 2, 3)) is None     # no change
    assert bump_level((1, 2, 3), (1, 1, 0)) is None     # not a forward bump
    assert bump_level(None, (1, 0, 0)) is None           # unknown base


def _revealed_release(tag):
    return [
        {"subject": "refactor core engine", "files": ["core/engine.py"]},
        {"subject": f"Release {tag}", "files": ["CHANGELOG.md"]},
    ]


def test_objective_score_bump_major():
    score = objective_score(
        [{"title": "cut release", "kind": "release"}],
        _revealed_release("v2.0.0"),
        version_bump="major", base_version="v1.4.2",
    )
    assert score["bump_actual"] == "major"
    assert score["bump_match"] is True


def test_objective_score_bump_minor_handles_no_leading_v():
    # base tag without a leading v, revealed tag with one — both must parse.
    score = objective_score(
        [{"title": "cut release", "kind": "release"}],
        _revealed_release("v1.5.0"),
        version_bump="minor", base_version="1.4.2",
    )
    assert score["bump_actual"] == "minor"
    assert score["bump_match"] is True


def test_objective_score_bump_patch_and_mismatch():
    revealed = _revealed_release("v1.4.3")
    score = objective_score(
        [{"title": "cut release", "kind": "release"}], revealed,
        version_bump="minor", base_version="v1.4.2",
    )
    assert score["bump_actual"] == "patch"
    assert score["bump_match"] is False       # agent said minor, actual was patch
    # normalization: the agent predicting the right level (any case) matches.
    assert objective_score([], revealed, version_bump="PATCH",
                           base_version="v1.4.2")["bump_match"] is True


def test_objective_score_bump_none_when_no_release_or_no_base():
    # No release in the window -> no actual bump; predicting none is a match.
    no_release = [{"subject": "refactor core engine", "files": ["core/engine.py"]}]
    assert objective_score([], no_release, base_version="v1.4.2")["bump_actual"] is None
    assert objective_score([], no_release, base_version="v1.4.2")["bump_match"] is True
    # Release present but base unknown -> can't classify the delta.
    assert objective_score([], _revealed_release("v2.0.0"),
                           version_bump="major")["bump_actual"] is None


def test_base_from_releases_picks_highest_tag():
    releases = [{"tag": "v1.2.0"}, {"tag": "v1.10.0"}, {"tag": "v1.9.3"}]
    assert base_from_releases(releases) == "v1.10.0"   # semver, not lexical, ordering
    assert base_from_releases([]) is None


def test_bump_actual_ignores_version_in_non_release_commit():
    # Reviewer case: a non-release commit that merely names a version (e.g. a dep bump)
    # must not produce a spurious bump_actual, even when its version is the highest around.
    revealed = [
        {"subject": "bump dep to v9.9.9", "files": ["requirements.txt"]},
        {"subject": "Release v1.3.0", "files": ["CHANGELOG.md"]},
    ]
    score = objective_score([{"title": "cut release", "kind": "release"}], revealed,
                            version_bump="minor", base_version="v1.2.0")
    # Only the genuine release (v1.3.0) counts, so base v1.2.0 -> v1.3.0 is a minor bump —
    # NOT a major driven by the incidental v9.9.9.
    assert score["bump_actual"] == "minor"
    assert score["bump_match"] is True
    # And with only the non-release version present, there is no actual bump at all.
    dep_only = [{"subject": "bump dep to v9.9.9", "files": ["requirements.txt"]}]
    assert objective_score([], dep_only, base_version="v1.2.0")["bump_actual"] is None


def test_commit_kind_conventional_prefixes():
    assert commit_kind("feat: add plugin loader") == "feat"
    assert commit_kind("Fix(core): guard nil deref") == "fix"
    assert commit_kind("docs!: rewrite readme") == "docs"
    assert commit_kind("refactor(engine): split module") == "refactor"
    assert commit_kind("chore(deps): bump lib") == "chore"
    assert commit_kind("Release v1.2.0") == "release"  # fallback, no prefix
    assert commit_kind("merge branch 'main'") is None
    assert commit_kind("add plugin loader") is None  # no prefix, not a release
    assert commit_kind("") is None


def test_plan_kind_maps_to_commit_vocabulary():
    assert plan_kind("feature") == "feat"
    assert plan_kind("bugfix") == "fix"
    assert plan_kind("Docs") == "docs"
    assert plan_kind("dep") == "chore"
    assert plan_kind("release") == "release"
    # Plurals map like their singular, mirroring _COMMIT_KIND ("tests" -> "test") and the
    # sibling "dep"/"deps" pair — so a plan item labelled "tests" isn't silently dropped.
    assert plan_kind("test") == "test"
    assert plan_kind("tests") == "test"
    assert plan_kind("triage") is None  # not a commit kind
    assert plan_kind("") is None


def test_kind_recall_credits_plural_tests_kind():
    # A plan item declaring the natural plural kind "tests" must earn credit when the
    # maintainer actually shipped test commits (regression: "tests" mapped to None).
    revealed = [{"subject": "tests: add coverage", "files": ["tests/t.py"]}]
    plan = [{"title": "add unit tests", "kind": "tests"}]
    res = kind_recall(plan, revealed)
    assert res["actual_kinds"] == ["test"]
    assert res["matched_kinds"] == ["test"]
    assert res["kind_recall"] == 1.0


def test_kind_recall_matches_anticipated_kinds():
    revealed = [
        {"subject": "feat: streaming api", "files": ["core/api.py"]},
        {"subject": "fix: race in loader", "files": ["core/loader.py"]},
        {"subject": "docs: update readme", "files": ["README.md"]},
    ]
    plan = [
        {"title": "ship streaming", "kind": "feature"},  # -> feat
        {"title": "harden loader", "kind": "bugfix"},    # -> fix
        {"title": "triage backlog", "kind": "triage"},   # -> no kind
    ]
    res = kind_recall(plan, revealed)
    assert res["actual_kinds"] == ["docs", "feat", "fix"]
    assert res["matched_kinds"] == ["feat", "fix"]
    assert res["kind_recall"] == round(2 / 3, 3)  # docs not anticipated


def test_kind_recall_empty_inputs():
    assert kind_recall([], []) == {"kind_recall": 0.0, "actual_kinds": [], "matched_kinds": []}
    # revealed has no recognizable kinds -> zero, empty lists
    assert kind_recall([{"kind": "feature"}], [{"subject": "misc tweak"}])["actual_kinds"] == []


def test_objective_score_includes_kind_recall():
    plan = [{"title": "cut release", "kind": "release", "theme": "core"}]
    score = objective_score(plan, REVEALED)
    assert "kind_recall" in score
    assert "actual_kinds" in score
    assert "matched_kinds" in score
    assert score["actual_kinds"] == ["release"]  # only "Release v1.2.0" carries a kind
    assert score["matched_kinds"] == ["release"]
    assert score["kind_recall"] == 1.0


def test_release_predicted_normalizes_kind_case_and_whitespace():
    # The kind vocabulary is case/whitespace-insensitive everywhere else (plan_kind,
    # kind_recall); release_predicted must agree, so a "Release" / " release " item whose
    # title carries no release wording still counts as predicting a release.
    for kind in ("Release", "RELEASE", "  release  "):
        assert release_predicted([{"title": "ship the next cut", "kind": kind}]) is True, kind
    # A non-release kind with a non-release title is still not a predicted release.
    assert release_predicted([{"title": "tidy things up", "kind": "chore"}]) is False


def test_release_predicted_tolerates_non_string_kind():
    # An LLM plan may carry a non-string kind; it must not crash and must not be mistaken for a
    # release unless the title itself signals one.
    assert release_predicted([{"title": "misc work", "kind": 123}]) is False
    assert release_predicted([{"title": "misc work", "kind": ["release"]}]) is False
    assert release_predicted([{"title": "Release v2.0.0", "kind": None}]) is True  # via subject


def test_plan_kind_tolerates_non_string_and_case():
    assert plan_kind("Release") == "release"
    assert plan_kind("  RELEASE  ") == "release"
    assert plan_kind(123) is None
    assert plan_kind(None) is None
    assert plan_kind(["release"]) is None


def test_objective_score_release_match_honors_cased_kind():
    # Regression: a release is revealed and the plan predicts it via a capitalized kind
    # ("Release"). Before normalization this scored release_predicted=False, wrongly making
    # release_match=False for a correct prediction.
    revealed = [{"subject": "Release v2.0.0", "files": ["CHANGELOG.md"]}]
    score = objective_score([{"title": "prepare the cut", "kind": "Release"}], revealed)
    assert score["release_signaled"] is True
    assert score["release_predicted"] is True
    assert score["release_match"] is True
