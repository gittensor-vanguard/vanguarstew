"""Tests for the composite score (judge + objective anchor blended into [0, 1])."""

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from benchmark.score import composite_score, objective_component, objective_score  # noqa: E402

REVEALED = [
    {"subject": "add plugin loader", "files": ["plugins/loader.py", "README.md"]},
    {"subject": "refactor core engine", "files": ["core/engine.py"]},
    {"subject": "Release v1.2.0", "files": ["CHANGELOG.md"]},
]


def _realistic_objective_score(**backlog_overrides) -> dict:
    """Build a full objective_score-shaped dict with optional backlog field overrides."""
    plan = [
        {"title": "extend plugins loader", "kind": "feature", "theme": "plugins"},
        {"title": "cut release", "kind": "release", "theme": "changelog"},
    ]
    open_issues = [
        {"number": 12, "title": "Memory leak under load"},
        {"number": 15, "title": "Support YAML config"},
    ]
    revealed = [
        {"subject": "fix: memory leak under heavy load", "files": ["core/leak.py"]},
        {"subject": "Release v1.2.0", "files": ["CHANGELOG.md", "core/version.py"]},
    ]
    score = objective_score(
        plan, revealed, version_bump="minor", base_version="v1.1.0",
        open_issues=open_issues,
    )
    score.update(backlog_overrides)
    return score


def test_objective_component_module_recall_only():
    assert objective_component({"module_recall": 0.5}) == 0.5
    assert objective_component({}) == 0.0


def test_objective_component_counts_release_only_when_signaled():
    # no release in window -> only module recall counts
    assert objective_component({"module_recall": 0.4, "release_signaled": False}) == 0.4
    # release happened and was predicted -> averaged in as 1.0
    assert objective_component({"module_recall": 1.0, "release_signaled": True,
                                "release_predicted": True}) == 1.0
    # release happened but was missed -> averaged in as 0.0
    assert objective_component({"module_recall": 1.0, "release_signaled": True,
                                "release_predicted": False}) == 0.5


def test_objective_component_includes_kind_recall_when_kinds_present():
    # When the revealed window carries commit kinds, kind_recall feeds the anchor — mirroring
    # #215/#347 for weighted module recall.
    assert objective_component({
        "module_recall": 0.0,
        "kind_recall": 1.0,
        "actual_kinds": ["feat", "fix"],
    }) == 0.5
    assert objective_component({
        "module_recall": 1.0,
        "kind_recall": 0.0,
        "actual_kinds": ["feat"],
    }) == 0.5
    # No recognizable kinds in the window -> kind_recall must not affect the average.
    assert objective_component({"module_recall": 0.4, "kind_recall": 0.0,
                                "actual_kinds": []}) == 0.4


def test_objective_component_includes_bump_when_present():
    obj = {"module_recall": 1.0, "release_signaled": True, "release_predicted": True,
           "bump_actual": "minor", "bump_match": True}
    assert objective_component(obj) == 1.0
    obj["bump_match"] = False
    assert objective_component(obj) == round(2 / 3, 3)


def test_objective_component_prefers_weighted_module_recall():
    # When file-weighted recall is present it is used instead of plain recall, so the
    # score reflects where change actually concentrated (#61).
    assert objective_component({"module_recall": 0.5, "weighted_module_recall": 0.9}) == 0.9
    # It blends with the release/bump signals exactly like plain recall does.
    obj = {"module_recall": 0.2, "weighted_module_recall": 0.8,
           "release_signaled": True, "release_predicted": True}
    assert objective_component(obj) == round((0.8 + 1.0) / 2, 3)


def test_objective_component_falls_back_to_plain_recall_when_unweighted():
    # No weighted recall available (e.g. the weighted producer is not present yet):
    # plain module_recall is used, so behavior is unchanged until it lands.
    assert objective_component({"module_recall": 0.5}) == 0.5
    # An explicit None weighted value falls back rather than being treated as 0.0.
    assert objective_component({"module_recall": 0.4, "weighted_module_recall": None}) == 0.4


def test_composite_uses_weighted_recall_end_to_end():
    # The composite reflects weighted recall through objective_component (#61).
    obj = {"module_recall": 0.0, "weighted_module_recall": 1.0}
    assert composite_score("tie", obj) == 0.7  # 0.6*0.5 + 0.4*1.0


def test_composite_blends_judge_and_objective():
    obj = {"module_recall": 0.5}
    assert composite_score("A", obj) == 0.8    # 0.6*1.0 + 0.4*0.5
    assert composite_score("B", obj) == 0.2    # 0.6*0.0 + 0.4*0.5
    assert composite_score("tie", obj) == 0.5  # 0.6*0.5 + 0.4*0.5


def test_composite_weights_are_normalized():
    obj = {"module_recall": 1.0}
    # judge-only weighting -> pure judge outcome
    assert composite_score("A", obj, w_judge=1.0, w_objective=0.0) == 1.0
    assert composite_score("B", obj, w_judge=1.0, w_objective=0.0) == 0.0
    # weights that don't sum to 1 are normalized
    assert composite_score("A", obj, w_judge=3.0, w_objective=1.0) == 1.0


def test_objective_component_uses_only_ranking_fields_from_full_objective_dict():
    """#148: backlog diagnostics in a realistic objective_score dict must not move the anchor."""
    matched = _realistic_objective_score()
    missed = _realistic_objective_score(
        backlog_recall=0.0,
        matched_issue_numbers=[],
        addressed_issue_numbers=[12],
        addressed_backlog_diagnostics=[{
            "number": 12,
            "title": "Memory leak under load",
            "matched_subject": "fix: memory leak under heavy load",
        }],
    )
    inflated = _realistic_objective_score(
        backlog_recall=1.0,
        matched_issue_numbers=[12, 15],
        addressed_issue_numbers=[12, 15],
        addressed_backlog_diagnostics=[
            {"number": 12, "title": "Memory leak under load",
             "matched_subject": "fix: memory leak under heavy load"},
            {"number": 15, "title": "Support YAML config",
             "matched_subject": "fix: memory leak under heavy load"},
        ],
    )
    assert matched["backlog_recall"] == 0.0
    assert inflated["backlog_recall"] == 1.0
    # weighted recall + kind recall + release predicted + bump match
    expected = round(
        (matched["weighted_module_recall"] + matched["kind_recall"] + 1.0 + 1.0) / 4,
        3,
    )
    assert objective_component(missed) == expected
    assert objective_component(matched) == expected
    assert objective_component(inflated) == expected


def test_composite_score_ignores_backlog_fields_in_full_objective_dict():
    missed = _realistic_objective_score(backlog_recall=0.0, matched_issue_numbers=[])
    inflated = _realistic_objective_score(
        backlog_recall=1.0,
        matched_issue_numbers=[12, 15],
        addressed_issue_numbers=[12, 15],
    )
    anchor = objective_component(missed)
    expected_tie = round(0.6 * 0.5 + 0.4 * anchor, 3)
    for winner, judge_value in (("A", 1.0), ("B", 0.0), ("tie", 0.5)):
        expected = round((0.6 * judge_value + 0.4 * anchor) / 1.0, 3)
        assert composite_score(winner, missed) == expected
        assert composite_score(winner, inflated) == expected
    assert composite_score("tie", missed) == expected_tie


def test_objective_score_backlog_change_does_not_move_component_when_modules_match():
    """End-to-end #148 with matched vs missed backlog and identical module recall."""
    open_issues = [
        {"number": 12, "title": "Memory leak under load"},
        {"number": 99, "title": "Unrelated roadmap item"},
    ]
    revealed = [{"subject": "fix: memory leak under heavy load", "files": ["core/leak.py"]}]
    plan_match = [{"title": "Fix memory leak under load", "kind": "bugfix", "theme": "core"}]
    plan_miss = [{"title": "Refactor core internals", "kind": "refactor", "theme": "core"}]
    score_match = objective_score(plan_match, revealed, open_issues=open_issues)
    score_miss = objective_score(plan_miss, revealed, open_issues=open_issues)
    assert score_match["backlog_recall"] == 1.0
    assert score_miss["backlog_recall"] == 0.0
    assert score_match["module_recall"] == score_miss["module_recall"] == 1.0
    assert score_match["kind_recall"] == 1.0
    assert score_miss["kind_recall"] == 0.0
    assert objective_component(score_match) == 1.0
    assert objective_component(score_miss) == 0.5


def test_composite_reflects_kind_recall_end_to_end():
    revealed = [
        {"subject": "feat: add widgets", "files": ["widgets/a.py"]},
        {"subject": "fix: crash on load", "files": ["core/x.py"]},
    ]
    good = objective_score(
        [{"title": "ship features", "kind": "feature"}, {"title": "fix bugs", "kind": "bugfix"}],
        revealed,
    )
    bad = objective_score([{"title": "write docs", "kind": "docs"}], revealed)
    assert good["kind_recall"] == 1.0
    assert bad["kind_recall"] == 0.0
    assert objective_component(good) > objective_component(bad)
    assert composite_score("tie", good) > composite_score("tie", bad)
