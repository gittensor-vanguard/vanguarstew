"""Tests for the objective scoring anchor (deterministic, structural)."""

import logging
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from benchmark.score import (  # noqa: E402
    _COMMIT_KIND,
    _PLAN_KIND,
    _files_list,
    _meaningful_overlap,
    _plan_file_paths,
    _plan_list,
    _plan_tokens,
    _releases_list,
    _revealed_list,
    _tokens,
    _top_module,
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
    released_version,
    trajectory_overlap,
)

REVEALED = [
    {"subject": "add plugin loader", "files": ["plugins/loader.py", "README.md"]},
    {"subject": "refactor core engine", "files": ["core/engine.py"]},
    {"subject": "Release v1.2.0", "files": ["CHANGELOG.md"]},
]


def test_changed_modules():
    assert changed_modules(REVEALED) == {"plugins", "readme", "core", "changelog"}


def test_changed_modules_top_level_dotfile_not_dropped():
    revealed = [{"subject": "tweak ignores", "files": [".gitignore"]}]
    assert changed_modules(revealed) == {"gitignore"}


def test_module_recall_credits_dotfile_only_change():
    revealed = [{"subject": "tweak ignores", "files": [".gitignore"]}]
    plan = [{"title": "update gitignore", "kind": "chore"}]
    res = module_recall(plan, revealed)
    assert res["actual_modules"] == ["gitignore"]
    assert res["matched_modules"] == ["gitignore"]
    assert res["module_recall"] == 1.0


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


def test_module_recall_excludes_kind_tag_collision():
    # A kind tag whose vocabulary collides with a module name (docs, ci, build, test, ...)
    # must not earn module recall. Only real naming (title/theme/files) counts.
    revealed = [{"subject": "chore: tidy", "files": ["docs/guide.md", "ci/workflow.yml"]}]
    plan = [
        {"title": "ship an unrelated feature", "kind": "docs"},
        {"title": "some other thing", "kind": "ci"},
    ]
    res = module_recall(plan, revealed)
    assert res["actual_modules"] == ["ci", "docs"]
    assert res["matched_modules"] == []
    assert res["module_recall"] == 0.0


def test_module_recall_still_credits_title_theme_and_files_after_kind_exclusion():
    # Excluding kind must not weaken legitimate matches via title, theme, or files.
    revealed = [{"subject": "chore: tidy", "files": ["docs/guide.md", "ci/workflow.yml"]}]
    plan = [
        {"title": "refresh the docs guide", "kind": "chore"},        # names "docs" in the title
        {"title": "housekeeping", "kind": "chore", "files": ["ci/workflow.yml"]},  # "ci" via files
    ]
    res = module_recall(plan, revealed)
    assert set(res["matched_modules"]) == {"docs", "ci"}
    assert res["module_recall"] == 1.0


def test_module_recall_tokenizes_non_dict_plan_items():
    # Plans may carry plain-string items; the non-dict branch must still tokenize them so a
    # string that names a module earns recall (guards the else branch from regressing).
    revealed = [{"subject": "refactor core engine", "files": ["core/engine.py"]}]
    plan = ["overhaul the core engine"]  # a bare string, not a dict
    res = module_recall(plan, revealed)
    assert res["matched_modules"] == ["core"]
    assert res["module_recall"] == 1.0


# --- file-weighted module recall must actually be produced (#215, #43) -----------------

def test_module_recall_produces_weighted_recall_and_weights():
    # objective_component prefers weighted_module_recall, so module_recall must emit it.
    revealed = [{"subject": "work", "files": ["core/a.py", "plugins/b.py"]}]
    plan = [{"title": "touch the plugins module", "kind": "feature"}]
    res = module_recall(plan, revealed)
    assert res["module_weights"] == {"core": 1, "plugins": 1}
    # One of two equally-weighted modules matched -> 1/2 either way.
    assert res["module_recall"] == 0.5
    assert res["weighted_module_recall"] == 0.5


def test_module_recall_reports_weighted_matched_modules():
    # #43 acceptance: alongside the aggregate, report just the matched modules each with their
    # file weight, so it is visible *which* anticipated modules carried the weighted recall.
    revealed = [
        {"subject": "big core refactor", "files": ["core/a.py", "core/b.py", "core/c.py"]},
        {"subject": "touch plugins", "files": ["plugins/x.py"]},
        {"subject": "docs tweak", "files": ["readme/readme.md"]},   # changed but NOT anticipated
    ]
    plan = [{"title": "rewrite the core engine and a plugins loader", "kind": "refactor"}]
    res = module_recall(plan, revealed)
    # Only the matched modules appear (readme is changed but unmatched, so it is excluded),
    # each carrying its own file count from module_weights.
    assert res["weighted_matched_modules"] == {"core": 3, "plugins": 1}
    assert res["module_weights"] == {"core": 3, "plugins": 1, "readme": 1}
    # It is exactly the matched subset of module_weights, and its weight sum over the total
    # reproduces weighted_module_recall (4 of 5 files anticipated).
    assert set(res["weighted_matched_modules"]) == set(res["matched_modules"])
    assert res["weighted_module_recall"] == 0.8


def test_weighted_matched_modules_absent_on_empty_window():
    # No changed files -> no weighting to report; the key is simply absent (same graceful
    # fallback as weighted_module_recall / module_weights).
    res = module_recall([{"title": "anything"}], [{"subject": "merge", "files": []}])
    assert "weighted_matched_modules" not in res


def test_weighted_recall_rewards_the_module_where_change_concentrated():
    # core absorbs 4 of 5 changed files; plugins 1. Naming the heavy module must outscore
    # naming the light one under weighting, while plain recall stays 0.5 for both.
    revealed = [
        {"subject": "big core refactor", "files": ["core/a.py", "core/b.py", "core/c.py", "core/d.py"]},
        {"subject": "tiny plugin tweak", "files": ["plugins/x.py"]},
    ]
    heavy = module_recall([{"title": "rewrite the core engine", "kind": "refactor"}], revealed)
    light = module_recall([{"title": "tweak the plugins module", "kind": "feature"}], revealed)
    assert heavy["module_recall"] == light["module_recall"] == 0.5
    assert heavy["weighted_module_recall"] == 0.8   # 4/5 files
    assert light["weighted_module_recall"] == 0.2   # 1/5 files


def test_weighted_recall_is_one_on_full_match_and_absent_on_empty_window():
    full = module_recall(
        [{"title": "core and plugins", "theme": "core plugins", "kind": "feature"}],
        [{"files": ["core/a.py", "core/b.py", "plugins/c.py"]}],
    )
    assert full["module_recall"] == 1.0
    assert full["weighted_module_recall"] == 1.0
    # No files at all -> no weighting to report; the key is simply absent (graceful fallback
    # to plain module_recall in objective_component, which tolerates a missing key).
    empty = module_recall([{"title": "anything"}], [{"subject": "merge", "files": []}])
    assert "weighted_module_recall" not in empty


def test_objective_score_and_component_use_the_weighted_recall():
    revealed = [
        {"subject": "core work", "files": ["core/a.py", "core/b.py", "core/c.py"]},
        {"subject": "docs", "files": ["readme/readme.md"]},
    ]
    score = objective_score([{"title": "rewrite the core", "kind": "refactor"}], revealed)
    assert score["weighted_module_recall"] == 0.75   # 3/4 files under core
    assert score["module_weights"] == {"core": 3, "readme": 1}
    from benchmark.score import objective_component
    # The composite anchor now reflects the weighted value (0.75), not plain recall (0.5).
    assert objective_component(score) == 0.75


def test_kind_recall_unaffected_by_module_recall_kind_exclusion():
    # Dropping kind from module recall must not touch kind_recall, which still reads kind.
    revealed = [
        {"subject": "docs: refresh guide", "files": ["docs/guide.md"]},
        {"subject": "ci: tune workflow", "files": ["ci/workflow.yml"]},
    ]
    plan = [
        {"title": "ship an unrelated feature", "kind": "docs"},
        {"title": "some other thing", "kind": "ci"},
    ]
    assert module_recall(plan, revealed)["module_recall"] == 0.0  # kind no longer farms modules
    kr = kind_recall(plan, revealed)
    assert set(kr["matched_kinds"]) == {"docs", "ci"}
    assert kr["kind_recall"] == 1.0


def test_backlog_recall_excludes_kind_tag_collision():
    # A kind tag must not push a backlog issue over the match threshold; only real content
    # tokens (title/theme/files) may anticipate an addressed issue.
    open_issues = [{"number": 7, "title": "Update ci docs"}]
    revealed = [{"subject": "update ci docs config", "files": ["ci/docs.yml"]}]
    # The plan names only "docs" in real content; "ci" would come solely from the kind tag.
    plan = [{"title": "refresh the docs", "kind": "ci"}]
    res = backlog_recall(plan, revealed, open_issues)
    assert res["addressed_issue_numbers"] == [7]  # the window does address the issue
    assert res["matched_issue_numbers"] == []      # but the plan did not truly anticipate it
    assert res["backlog_recall"] == 0.0


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


def test_is_release_subject_accepts_two_component_tags():
    # parse_semver already tolerates a missing patch component ("1.4" -> (1, 4, 0));
    # is_release_subject must recognize the same bare two-component tags as releases.
    assert is_release_subject("v2.0")
    assert is_release_subject("2.0")
    assert is_release_subject("Release v2.0")


def test_released_version_recognizes_two_component_tag():
    revealed = [{"subject": "v2.0", "files": ["CHANGELOG.md"]}]
    assert released_version(revealed) == (2, 0, 0)


def test_released_version_prefers_release_semver_over_earlier_incidental():
    # Regression: parse_semver on the whole subject used to return the first version token
    # (3.11.0 from "Python 3.11") instead of the released version (1.4.0).
    subj = "Support Python 3.11, release 1.4.0"
    assert is_release_subject(subj)
    assert released_version([{"subject": subj}]) == (1, 4, 0)
    assert bump_level((1, 3, 0), released_version([{"subject": subj}])) == "minor"


def test_release_signaled_ignores_dependency_bumps():
    dep_bumps = [
        {"subject": "chore(deps): bump lodash to v4.17.21", "files": ["package.json"]},
        {"subject": "upgrade numpy to 1.26.4", "files": ["requirements.txt"]},
    ]
    assert release_signaled(dep_bumps) is False
    # A genuine release in the window is still detected.
    assert release_signaled(dep_bumps + [{"subject": "Release v2.0.0", "files": ["CHANGELOG.md"]}])


def test_is_release_subject_rejects_incidental_release_keyword_after_cc_prefix():
    # A Conventional-Commit prefix is authoritative: incidental release/changelog wording in
    # a ci/docs/test/refactor/fix commit is not a version cut (#431).
    for subj in (
        "ci: fix the release workflow yaml",
        "docs: update the changelog for contributors",
        "test: cover the release-notes generator",
        "refactor: extract the release helper",
        "fix: typo in CHANGELOG heading",
    ):
        assert not is_release_subject(subj), subj
        assert commit_kind(subj) != "release", subj
    # Prefix-less and release-typed subjects still count.
    for subj in ("Release v1.2.0", "release: cut 2.0.0", "bump version to 3.1.0", "v2.0"):
        assert is_release_subject(subj), subj


def test_release_signaled_ignores_incidental_release_keyword_in_cc_commits():
    non_releases = [
        {"subject": "ci: fix the release workflow yaml", "files": ["ci/release.yml"]},
        {"subject": "docs: update the changelog for contributors", "files": ["CHANGELOG.md"]},
    ]
    for c in non_releases:
        assert release_signaled([c]) is False, c["subject"]
    assert release_signaled([{"subject": "Release v1.2.0", "files": ["CHANGELOG.md"]}]) is True


def test_objective_component_not_penalized_by_incidental_release_word():
    revealed = [{
        "subject": "ci: fix the release workflow yaml",
        "files": ["ci/release.yml", "ci/build.yml"],
    }]
    plan = [{
        "title": "harden the CI workflow",
        "kind": "ci",
        "files": ["ci/release.yml", "ci/build.yml"],
    }]
    from benchmark.score import objective_component

    obj = objective_score(plan, revealed)
    assert obj["release_signaled"] is False
    assert obj["module_recall"] == 1.0
    assert objective_component(obj) == 1.0


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


def test_base_from_releases_falls_back_to_release_name():
    # GitHub API releases carry tag_name and name; tag can be missing or non-semver.
    assert base_from_releases([{"tag": None, "name": "v1.2.0"}]) == "v1.2.0"
    assert base_from_releases([{"name": "v2.0.0"}]) == "v2.0.0"
    # Prefer a parseable tag; only consult name when tag is absent or not semver-shaped.
    assert base_from_releases([{"tag": "v1.5.0", "name": "v9.9.9"}]) == "v1.5.0"
    assert base_from_releases([{"tag": "latest", "name": "v1.5.0"}]) == "v1.5.0"


# --- #459: a non-list releases field must not abort replay scoring -------------------------

_MALFORMED_RELEASES = [42, 3.14, True, {"tag": "v1.0.0"}, "not a list", None]


def test_releases_list_accepts_only_real_lists():
    releases = [{"tag": "v1.2.0"}]
    assert _releases_list(releases) == releases
    assert _releases_list(None) == []
    for bad in _MALFORMED_RELEASES:
        assert _releases_list(bad) == [], bad


def test_base_from_releases_survives_non_list_container():
    for bad in _MALFORMED_RELEASES:
        assert base_from_releases(bad) is None, bad


def test_base_from_releases_skips_non_dict_rows():
    releases = [42, {"tag": "v2.0.0"}, None, {"name": "v1.5.0"}]
    assert base_from_releases(releases) == "v2.0.0"


def test_base_from_releases_well_formed_regression():
    releases = [{"tag": "v1.0.0"}, {"tag": "v1.10.0"}, {"tag": "v1.2.0"}]
    assert base_from_releases(releases) == "v1.10.0"


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


def _kind_aliases(mapping: dict, target: str) -> set[str]:
    return {alias for alias, normalized in mapping.items() if normalized == target}


def test_plan_and_commit_kind_vocabularies_stay_symmetric():
    """Invariant guard (#145): _PLAN_KIND and _COMMIT_KIND must not drift silently.

    Every normalized maintainer kind must be reachable from both vocabularies, and every
    alias in either table must normalize to the same target as its counterparts on the
    other side. ``triage`` is a valid planner-only action (see ``agent/planner.py``) that
    deliberately maps to no commit kind, so ``plan_kind("triage")`` is ``None``.
    """
    plan_targets = set(_PLAN_KIND.values())
    commit_targets = set(_COMMIT_KIND.values())
    assert plan_targets == commit_targets

    for target in plan_targets:
        plan_aliases = _kind_aliases(_PLAN_KIND, target)
        commit_aliases = _kind_aliases(_COMMIT_KIND, target)
        assert plan_aliases, f"no plan alias for normalized {target!r}"
        assert commit_aliases, f"no commit alias for normalized {target!r}"

        for alias in plan_aliases:
            assert plan_kind(alias) == target, alias
            assert plan_kind(alias.upper()) == target, alias

        for alias in commit_aliases:
            subject = "Release v1.0.0" if alias == "release" else f"{alias}: example change"
            assert commit_kind(subject) == target, alias

    assert plan_kind("triage") is None


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


# --- #308: _meaningful_overlap threshold must be reachable for single-word issue titles ------

def test_meaningful_overlap_single_word_title_reachable():
    # A single-word title can share at most one token, so the old hard floor of 2 made even an
    # exact match unreachable — it must now count, while a genuine non-match still does not.
    assert _meaningful_overlap({"flaky"}, {"fix", "flaky", "test"}) is True
    assert _meaningful_overlap({"typo"}, {"fix", "flaky", "test"}) is False
    assert _meaningful_overlap({"a"}, {"a", "b", "c", "d", "e", "f"}) is True  # 1 of a big set


def test_meaningful_overlap_multi_word_threshold_unchanged():
    # The fix only lowers the bar where the old one was mathematically impossible; multi-token
    # titles still require >=2 shared tokens (or half the smaller set).
    assert _meaningful_overlap({"memory", "leak"}, {"memory", "fix"}) is False   # 1 shared
    assert _meaningful_overlap({"memory", "leak"}, {"memory", "leak"}) is True   # 2 shared
    assert _meaningful_overlap({"a", "b", "c", "d"}, {"a", "z"}) is False        # 1 of 2/4


def test_single_word_issue_title_counts_toward_backlog():
    # End-to-end: a terse single-word issue the plan/commit clearly names must surface in
    # addressed_issues and backlog_recall instead of being silently dropped.
    open_issues = [{"number": 1, "title": "Flaky"}]
    revealed = [{"subject": "Fix flaky test in CI", "files": []}]
    assert [i["number"] for i in addressed_issues(revealed, open_issues)] == [1]
    plan = [{"title": "Stabilize the flaky suite", "kind": "test"}]
    res = backlog_recall(plan, revealed, open_issues)
    assert res["matched_issue_numbers"] == [1]
    assert res["backlog_recall"] == 1.0


# --- #324: is_release_subject must accept two-component version tags -----------------------

def test_is_release_subject_accepts_two_component_version_tags():
    # A two-component tag subject (missing patch, or CalVer) is a genuine release — matching
    # parse_semver's tolerance for a missing patch (#324).
    assert is_release_subject("v2.0") is True
    assert is_release_subject("2.0") is True
    assert is_release_subject("Release v2.0") is True
    assert is_release_subject("2024.11") is True          # CalVer
    assert is_release_subject("v2.0.1") is True            # three-component still works
    # Still anchored at the start: a version elsewhere in the subject is not a release.
    assert is_release_subject("fix crash in v1.2 parser") is False
    assert is_release_subject("add v2 support") is False   # "v2" is not a dotted version


def test_two_component_release_flows_through_downstream():
    revealed = [{"subject": "v2.0", "files": ["CHANGELOG.md"]}]
    assert release_signaled(revealed) is True
    assert released_version(revealed) == (2, 0, 0)
    assert commit_kind("v2.0") == "release"


# --- text helpers must treat a non-string LLM field as "no signal", never crash (#313) ---

# The shapes a model can emit for a field the scorer expects to be a string. A plan `title`,
# `theme`, or `kind`, a revealed `subject`, or a passed-in `base_version` can be any of these
# when the LLM's JSON doesn't match the documented contract.
_MALFORMED = [["release", "v2.0"], {"tag": "v2.0"}, 42, 3.14, True, b"v2.0", None]


def test_tokens_returns_empty_for_non_string_fields():
    for bad in _MALFORMED:
        assert _tokens(bad) == set(), f"_tokens({bad!r}) should be empty"
    # Real strings still tokenize normally (lowercased word set); "" is unchanged.
    assert _tokens("") == set()
    assert _tokens("Harden the Core Loader") == {"harden", "the", "core", "loader"}


def test_parse_semver_returns_none_for_non_string_base_version():
    for bad in _MALFORMED:
        assert parse_semver(bad) is None, f"parse_semver({bad!r}) should be None"
    assert parse_semver("v1.4.0") == (1, 4, 0)
    assert parse_semver("no version here") is None


def test_is_release_subject_is_false_for_non_string_subject():
    for bad in _MALFORMED:
        assert is_release_subject(bad) is False, f"is_release_subject({bad!r}) should be False"
    assert is_release_subject("Release v1.2.0") is True
    assert is_release_subject("bump lodash to v4.17.21") is False


def test_commit_kind_is_none_for_non_string_subject():
    for bad in _MALFORMED:
        assert commit_kind(bad) is None, f"commit_kind({bad!r}) should be None"
    assert commit_kind("feat(core): add loader") == "feat"
    assert commit_kind("Release v2.0.0") == "release"


def test_objective_score_survives_a_fully_malformed_plan_and_revealed_window():
    # Every field the scorer reads as text is malformed at once. Before the guards, the first
    # `_tokens`/`re` call would raise and abort scoring for the whole replay task; now the
    # score is well-formed and the malformed fields simply contribute nothing.
    plan = [
        {"title": ["Add", "loader"], "theme": {"area": "core"}, "kind": ["feat"]},
        {"title": 123, "kind": None},
    ]
    revealed = [
        {"subject": ["not", "a", "string"], "files": ["agent/loader.py"]},
        {"subject": 999, "files": ["benchmark/score.py"]},
    ]
    score = objective_score(
        plan, revealed,
        version_bump=["major"], base_version={"tag": "v1.0.0"},
        open_issues=[{"number": 3, "title": ["broken", "thing"]}],
    )
    for key in ("module_recall", "kind_recall", "release_signaled", "release_predicted",
                "release_match", "bump_actual", "bump_match", "backlog_recall"):
        assert key in score, key
    # No text signal survives, so structural recall is zero rather than raising.
    assert score["module_recall"] == 0.0
    assert score["kind_recall"] == 0.0


def test_backlog_recall_skips_non_dict_open_issues_entry():
    # A malformed entry in open_issues (e.g. a bare string instead of an issue dict) must be
    # skipped, not raise — and the well-formed issue alongside it must still be counted, proving
    # the guard actually filters rather than dropping the whole list.
    open_issues = [{"number": 1, "title": "Login timeout bug"}, "not-a-dict-issue"]
    revealed = [{"subject": "fix: login timeout", "files": ["auth/login.py"]}]
    plan = [{"title": "Fix the login timeout bug", "kind": "bugfix", "theme": "auth"}]

    assert [i["number"] for i in addressed_issues(revealed, open_issues)] == [1]

    res = backlog_recall(plan, revealed, open_issues)
    assert res["matched_issue_numbers"] == [1]
    assert res["addressed_issue_numbers"] == [1]
    assert res["backlog_recall"] == 1.0

    score = objective_score(plan, revealed, open_issues=open_issues)
    assert score["matched_issue_numbers"] == [1]
    assert score["backlog_recall"] == 1.0


def test_backlog_recall_logs_a_warning_for_non_dict_open_issues_entry(caplog):
    with caplog.at_level(logging.WARNING, logger="benchmark.score"):
        backlog_recall([], [], [{"number": 1, "title": "ok"}, 42, None])
    assert any("non-dict open_issues" in r.message for r in caplog.records)


def test_objective_score_tolerates_non_list_open_issues():
    # A non-list open_issues (a malformed backlog source, e.g. an int) must be treated as an
    # empty backlog rather than raising `TypeError: 'int' object is not iterable` and aborting
    # the whole replay — the same fail-soft posture as a non-dict entry or a non-list plan.
    plan = [{"title": "Fix login", "kind": "bugfix"}]
    revealed = [{"subject": "fix: login", "files": ["auth/login.py"]}]
    for bad in (42, "issues", {"number": 1}, True):
        score = objective_score(plan, revealed, open_issues=bad)
        assert score["backlog_recall"] == 0.0
        assert score["addressed_issue_numbers"] == []
    assert addressed_issues(revealed, 42) == []


def test_objective_score_unchanged_for_well_formed_plan_after_guards():
    # The guards must be inert on valid input: a plan naming the changed modules still scores
    # a perfect structural recall, proving no regression was introduced.
    revealed = [{"subject": "feat: add loader", "files": ["agent/loader.py", "core/x.py"]}]
    plan = [{"title": "add the agent loader and core module", "kind": "feat"}]
    score = objective_score(plan, revealed)
    assert score["module_recall"] == 1.0
    assert score["kind_recall"] == 1.0


def test_plan_list_accepts_only_real_lists():
    assert _plan_list([{"title": "work"}]) == [{"title": "work"}]
    for bad in (42, True, {"plan": []}, "not a list", None, ""):
        assert _plan_list(bad) == []


# --- #421: a non-list revealed window must not abort scoring --------------------------------

_MALFORMED_REVEALED = [42, 3.14, True, {"subject": "feat: x"}, "not a list", None]


def test_revealed_list_accepts_only_real_lists():
    revealed = [{"subject": "feat: add loader", "files": ["agent/x.py"]}]
    assert _revealed_list(revealed) == revealed
    assert _revealed_list(None) == []
    for bad in _MALFORMED_REVEALED:
        assert _revealed_list(bad) == [], bad


def test_released_version_survives_non_list_revealed_container():
    for bad in _MALFORMED_REVEALED:
        assert released_version(bad) is None, bad


def test_released_version_honors_valid_rows_in_mixed_list():
    revealed = [42, {"subject": "Release v2.0", "files": []}, None]
    assert released_version(revealed) == (2, 0, 0)


def test_changed_modules_skips_non_dict_revealed_rows():
    revealed = [42, {"files": ["agent/foo.py"]}, None]
    assert changed_modules(revealed) == {"agent"}


def test_kind_recall_survives_non_list_revealed_container():
    plan = [{"title": "loader work", "kind": "feat"}]
    for bad in _MALFORMED_REVEALED:
        res = kind_recall(plan, bad)
        assert res["kind_recall"] == 0.0
        assert res["actual_kinds"] == []


def test_trajectory_overlap_survives_non_list_revealed_container():
    plan = [{"title": "loader work", "kind": "feat"}]
    for bad in _MALFORMED_REVEALED:
        assert trajectory_overlap(plan, bad) == 0.0


def test_release_signaled_skips_non_dict_revealed_rows():
    assert release_signaled([42, {"subject": "Release v2.0", "files": []}]) is True
    assert release_signaled([42, {"subject": "misc tweak", "files": []}]) is False


def test_addressed_issues_skips_non_dict_revealed_rows():
    open_issues = [{"number": 1, "title": "fix loader crash"}]
    revealed = [42, {"subject": "fix loader crash in agent", "files": []}, None]
    assert len(addressed_issues(revealed, open_issues)) == 1


def test_backlog_recall_survives_mixed_revealed_rows():
    plan = [{"title": "fix loader crash", "kind": "fix"}]
    open_issues = [{"number": 1, "title": "fix loader crash"}]
    revealed = [42, {"subject": "fix loader crash in agent", "files": []}, None]
    res = backlog_recall(plan, revealed, open_issues)
    assert res["backlog_recall"] == 1.0


def test_objective_score_survives_non_list_revealed_container():
    plan = [{"title": "loader work", "kind": "feat"}]
    for bad in _MALFORMED_REVEALED:
        score = objective_score(plan, bad)
        assert score["module_recall"] == 0.0
        assert score["kind_recall"] == 0.0
        assert score["release_signaled"] is False


def test_objective_score_survives_mixed_revealed_rows():
    revealed = [
        42,
        {"subject": "feat: add loader", "files": ["agent/loader.py"]},
        None,
    ]
    plan = [{"title": "add the agent loader", "kind": "feat"}]
    score = objective_score(plan, revealed)
    assert score["module_recall"] == 1.0
    assert score["kind_recall"] == 1.0


def test_objective_score_tolerates_non_list_plan_container():
    for bad in (42, True, {"title": "oops"}):
        score = objective_score(bad, REVEALED)
        assert score["module_recall"] == 0.0
        assert score["kind_recall"] == 0.0
        assert score["release_predicted"] is False


# --- #399: non-string file-path entries must not abort module recall scoring ---------------

_MALFORMED_PATHS = [42, 3.14, None, True, ["agent"], {"path": "agent/x.py"}, b"agent/x.py"]


def test_top_module_returns_none_for_non_string_paths():
    for bad in _MALFORMED_PATHS:
        assert _top_module(bad) is None, f"_top_module({bad!r}) should be None"
    assert _top_module("agent/loader.py") == "agent"
    assert _top_module(".gitignore") == "gitignore"


def test_changed_modules_skips_non_string_revealed_paths():
    mods = changed_modules([{"files": [42, None, "agent/foo.py", "benchmark/x.py"]}])
    assert mods == {"agent", "benchmark"}


def test_plan_tokens_skips_non_string_files_entries():
    toks = _plan_tokens([{"title": "loader", "files": [123, "agent/plan.py"]}])
    assert "agent" in toks
    assert "plan" in toks
    assert "123" not in toks


def test_plan_file_paths_wraps_scalar_string():
    assert _plan_file_paths("core/loader.py") == ["core/loader.py"]
    assert _plan_file_paths({"bad": True}) == []


def test_plan_tokens_honors_scalar_files_without_char_split():
    toks = _plan_tokens([{"title": "loader", "files": "core/loader.py"}])
    assert "core" in toks
    assert "loader" in toks
    assert "c" not in toks  # would appear if the string were iterated char-by-char


def test_module_recall_honors_scalar_plan_files():
    revealed = [{"subject": "fix loader", "files": ["core/loader.py"]}]
    plan = [{"title": "unrelated", "kind": "bugfix", "files": "core/loader.py"}]
    assert module_recall(plan, revealed)["module_recall"] == 1.0


def test_module_recall_survives_non_string_paths_in_plan_and_revealed():
    plan = [{"title": "loader", "files": [None, "agent/plan.py"]}]
    revealed = [{"subject": "ship it", "files": [42, "agent/foo.py", "benchmark/x.py"]}]
    res = module_recall(plan, revealed)
    assert res["module_recall"] == 0.5
    assert res["matched_modules"] == ["agent"]
    assert res["actual_modules"] == ["agent", "benchmark"]


def test_objective_score_survives_non_string_file_paths():
    revealed = [{"subject": "feat: core work", "files": [42, None, "agent/loader.py"]}]
    plan = [{"title": "agent loader", "kind": "feat", "files": [123, "agent/plan.py"]}]
    score = objective_score(plan, revealed)
    assert score["module_recall"] == 1.0
    assert score["kind_recall"] == 1.0


# --- #587: truthy non-list files must not abort module recall scoring ------------------

_MALFORMED_FILES = [42, 3.14, True, {"path": "agent/x.py"}, "not a list"]


def test_files_list_accepts_only_real_lists():
    rows = ["agent/foo.py", "benchmark/x.py"]
    for bad in _MALFORMED_FILES:
        assert _files_list(bad, "plan.files") == [], bad
    assert _files_list(rows, "plan.files") == rows
    assert _files_list(None, "plan.files") == []


def test_plan_tokens_survives_non_list_files(caplog):
    with caplog.at_level(logging.WARNING, logger="benchmark.score"):
        toks = _plan_tokens([{"title": "loader", "files": 42}])
    assert toks == _tokens("loader")
    assert any("plan.files is int" in r.message for r in caplog.records)


def test_changed_modules_survives_non_list_revealed_files(caplog):
    with caplog.at_level(logging.WARNING, logger="benchmark.score"):
        assert changed_modules([{"files": 42}, {"files": ["agent/foo.py"]}]) == {"agent"}
    assert any("revealed.files is int" in r.message for r in caplog.records)


def test_objective_score_survives_non_list_files_field():
    revealed = [{"subject": "feat: core work", "files": 42}]
    plan = [{"title": "agent loader", "kind": "feat", "files": 42}]
    score = objective_score(plan, revealed)
    assert score["module_recall"] == 0.0
    assert score["kind_recall"] == 1.0


def test_objective_component_handles_non_dict():
    from benchmark.score import objective_component
    assert objective_component(None) == 0.0
    assert objective_component(42) == 0.0

def test_objective_component_handles_non_numeric_recall():
    from benchmark.score import objective_component
    assert objective_component({"module_recall": "not-a-number"}) == 0.0
    assert objective_component({"weighted_module_recall": [1,2,3]}) == 0.0

def test_bump_level_handles_non_tuple():
    assert bump_level(None, (1,0,0)) is None
    assert bump_level("str", (1,0,0)) is None
    assert bump_level((1,0,0), None) is None
    assert bump_level((1,), (1,0,0)) is None

def test_composite_score_handles_non_numeric_weights():
    from benchmark.score import composite_score
    assert composite_score("tie", {"module_recall": 0.5}, w_judge=None) >= 0
    assert composite_score("tie", {"module_recall": 0.5}, w_objective="str") >= 0
