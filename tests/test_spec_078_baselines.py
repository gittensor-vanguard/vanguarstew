"""Contract tests for specs/078-benchmark-baselines.

Pins the as-built behavior of ``benchmark/baselines.py`` against Spec 078's EARS criteria:
the exact registry and unknown-name error (plus the unhashable-name TypeError passthrough),
the runner call shape and both context branches, the four solve signatures, the empty floor's
literal output, the full Conventional-Commit kind mapping, keyword-bucket order and substring
semantics, context coercion including the malformed-commit triage vote, the exact heuristic
philosophy dict, the ordered heuristic plan and its plain-slice cap, review-queue item shape
and the post-append ``limit<=0`` quirk, queue-first composition and its uncapped rationale
count, the literal stability rank table, and cap-before-reorder.

Every expected value below was computed by executing the module once and is pinned as a
literal, not re-derived at test time. Complements ``tests/test_baselines.py``, which owns
registry identity, the truncation fail-closed matrix, release-detection parity with
``benchmark/score.py``, malformed-container tolerance, and end-to-end ``run_replay`` baseline
selection.

Run: VANGUARSTEW_OFFLINE=1 python -m pytest -q tests/test_spec_078_baselines.py
"""

import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

os.environ["VANGUARSTEW_OFFLINE"] = "1"

from benchmark.baselines import (  # noqa: E402
    _ALLOWED,
    _STABILITY_KIND_RANK,
    BASELINES,
    DEFAULT_BASELINE,
    _baseline_list,
    _commit_subject,
    _infer_kind,
    _issue_title,
    _pr_title,
    _review_queue_items,
    _safe_backlog,
    _stability_rank,
    empty_solve,
    get_baseline,
    heuristic_philosophy,
    heuristic_plan,
    heuristic_solve,
    queue_first_plan,
    queue_first_solve,
    stability_first_plan,
    stability_first_solve,
)

# Four commits (2 bugfix, 1 feature, 1 release) and four issue entries, two with a usable
# title, used for the philosophy/plan literal pins below.
PLAN_CTX = {
    "recent_commits": [
        {"subject": "fix: patch the widget loader"},
        {"subject": "fix: close the socket leak"},
        {"subject": "feat: add a config knob"},
        {"subject": "Release v0.3.0"},
    ],
    "open_issues": [
        {"title": "Support nested profiles"},
        {"title": 7},
        {"title": "   "},
        {"title": "Crash when the cache is cold"},
    ],
}

PHIL_LITERAL = {
    "summary": "Recent activity is dominated by bugfix work; 4 open issue(s) await triage.",
    "values": ["bugfix", "feature", "release"],
    "merge_bar": "inferred from recent commit patterns (no explicit signal)",
    "direction": "continue bugfix-oriented work and clear the issue backlog",
    "evidence": [
        "fix: patch the widget loader",
        "fix: close the socket leak",
        "feat: add a config knob",
        "Release v0.3.0",
    ],
}

PLAN_FULL = [
    {"title": "Address issue: Support nested profiles", "kind": "feature",
     "rationale": "open issue awaiting maintainer action", "theme": "issue backlog"},
    {"title": "Address issue: Crash when the cache is cold", "kind": "bugfix",
     "rationale": "open issue awaiting maintainer action", "theme": "issue backlog"},
    {"title": "Continue bugfix work", "kind": "bugfix",
     "rationale": "recent history is dominated by bugfix changes (2 recent)",
     "theme": "bugfix momentum"},
    {"title": "Continue feature work", "kind": "feature",
     "rationale": "recent history is dominated by feature changes (1 recent)",
     "theme": "feature momentum"},
    {"title": "Continue release work", "kind": "release",
     "rationale": "recent history is dominated by release changes (1 recent)",
     "theme": "release momentum"},
    {"title": "Prepare the next release", "kind": "release",
     "rationale": "recent history shows a release cadence", "theme": "release cadence"},
]

# Five open PRs: one plain, one with a string number, one titleless, one plain, one with a
# bool number (must never render, since bool is an int subclass).
QUEUE_CTX = {
    "open_prs": [
        {"number": 3, "title": "Harden the retry loop"},
        {"number": "7", "title": "Refresh the cache docs"},
        {"number": 11, "title": ""},
        {"number": 12, "title": "Trim the startup path"},
        {"number": True, "title": "Bool number edge case"},
    ],
    "open_issues": [{"title": "Crash when the cache is cold"}],
    "recent_commits": [{"subject": "fix: close the socket leak"}],
}


# --- Registry (BASELINES, DEFAULT_BASELINE, get_baseline) --------------------------------

def test_registry_names_and_default():
    assert set(BASELINES) == {"empty", "heuristic", "queue_first", "stability_first"}
    assert DEFAULT_BASELINE == "empty"
    assert BASELINES[DEFAULT_BASELINE] is empty_solve


def test_unknown_name_raises_value_error():
    with pytest.raises(ValueError) as exc:
        get_baseline("bogus")
    assert str(exc.value) == (
        "unknown baseline 'bogus'; choose from ['empty', 'heuristic', 'queue_first', "
        "'stability_first']"
    )
    assert exc.value.__cause__ is None
    assert exc.value.__suppress_context__ is True


def test_unhashable_name_propagates_type_error():
    # As-built divergence from the docstring: only a lookup miss becomes ValueError.
    with pytest.raises(TypeError):
        get_baseline(["empty"])


# --- Solve-call shape (all four baselines) ------------------------------------------------

@pytest.mark.parametrize("name", sorted(BASELINES))
def test_all_four_solves_accept_runner_call_shape_and_extra_kwargs(name):
    solve = BASELINES[name]
    # Runner shape: repo_path, request positional; context, n keyword; tolerates **_kw.
    out = solve("/some/repo", "do the thing", context={}, n=3, unexpected_kw="ignored")
    assert isinstance(out, dict)


@pytest.mark.parametrize("name", sorted(BASELINES))
def test_solve_output_has_exactly_the_judged_keys(name):
    out = BASELINES[name](context=PLAN_CTX, n=5)
    assert set(out) == {"philosophy", "plan", "action", "rationale"}
    assert out["action"] == "plan"


@pytest.mark.parametrize("name", sorted(BASELINES))
def test_context_as_is_including_falsy_dict(name, monkeypatch):
    def boom(repo_path):
        raise AssertionError("load_context must not be called when context is not None")

    monkeypatch.setattr("benchmark.baselines.load_context", boom)
    # A falsy {} is still "not None" and must be used as-is, never replaced by load_context.
    out = BASELINES[name](context={}, n=5)
    assert isinstance(out, dict)


@pytest.mark.parametrize("name", ["heuristic", "queue_first", "stability_first"])
def test_none_context_consults_load_context(name, monkeypatch):
    calls = []

    def fake_load_context(repo_path):
        calls.append(repo_path)
        return dict(PLAN_CTX)

    monkeypatch.setattr("benchmark.baselines.load_context", fake_load_context)
    BASELINES[name](repo_path="/some/repo", context=None, n=5)
    assert calls == ["/some/repo"]


def test_empty_solve_never_touches_context_or_load_context(monkeypatch):
    # As-built divergence: empty_solve ignores its context argument entirely — it never
    # calls load_context even when context is None, unlike the other three baselines.
    def boom(repo_path):
        raise AssertionError("empty_solve must never call load_context")

    monkeypatch.setattr("benchmark.baselines.load_context", boom)
    assert empty_solve(repo_path="/some/repo", context=None) == {
        "plan": [], "philosophy": {}, "action": "plan", "rationale": "baseline",
    }


# --- The empty floor ------------------------------------------------------------------------

def test_empty_solve_is_the_exact_literal_and_argument_invariant():
    expected = {"plan": [], "philosophy": {}, "action": "plan", "rationale": "baseline"}
    assert empty_solve() == expected
    assert empty_solve("repo", "request", context={"anything": True}, n=99, extra=1) == expected
    # Each call returns a fresh dict.
    assert empty_solve() is not empty_solve()


# --- Kind inference ---------------------------------------------------------------------

def test_infer_kind_precedence_release_then_conventional_commit():
    # "release" wording wins even under a non-tooling CC prefix that would otherwise map
    # straight through _COMMIT_KIND_TO_BASELINE.
    assert _infer_kind("Release v0.3.0") == "release"
    assert _infer_kind("fix: patch the widget loader") == "bugfix"


def test_commit_kind_mapping_table_is_exact():
    table = {
        "feat: x": "feature",
        "fix: x": "bugfix",
        "docs: x": "docs",
        "refactor: x": "refactor",
        "perf: x": "refactor",
        "chore: x": "dep",
        "ci: x": "refactor",
        "test: x": "refactor",
        "build: x": "refactor",
        "style: x": "refactor",
        "revert: x": "bugfix",
    }
    for subject, expected in table.items():
        assert _infer_kind(subject) == expected, subject


def test_keyword_bucket_order_and_substring_semantics():
    # dep before docs: "bump" (dep) beats "guide" (docs) in the same subject.
    assert _infer_kind("bump the guide") == "dep"
    # docs before bugfix: "guide" (docs) beats "fix" (bugfix) in the same subject.
    assert _infer_kind("fix the guide") == "docs"
    assert _infer_kind("refactor the parser") == "refactor"
    assert _infer_kind("add support for widgets") == "feature"


def test_test_bucket_resolves_to_refactor():
    assert _infer_kind("improve test coverage") == "refactor"


def test_no_match_is_triage():
    assert _infer_kind("random unrelated text") == "triage"
    assert _infer_kind("") == "triage"
    assert _infer_kind(None) == "triage"


def test_allowed_vocabulary_is_exactly_seven_kinds():
    assert _ALLOWED == {"feature", "bugfix", "refactor", "docs", "release", "dep", "triage"}


# --- Context coercion --------------------------------------------------------------------

def test_issue_and_pr_title_coercion():
    assert _issue_title({"title": "  hi  "}) == "hi"
    assert _issue_title({"title": 5}) == ""
    assert _issue_title("nope") == ""
    assert _issue_title({}) == ""
    assert _pr_title({"title": "  hi  "}) == "hi"
    assert _pr_title("nope") == ""


def test_commit_subject_non_dict_is_logged_and_becomes_placeholder(caplog):
    with caplog.at_level("WARNING"):
        assert _commit_subject("not-a-dict") == ""
        assert _commit_subject({"subject": 42}) == ""
    assert any("skipping a non-dict recent_commits entry" in r.message for r in caplog.records)


def test_baseline_list_identity_none_and_other_types():
    lst = [1, 2]
    assert _baseline_list(lst, "x") is lst
    assert _baseline_list(None, "x") == []
    assert _baseline_list((1, 2), "x") == []


def test_safe_backlog_truncation_gate_is_identity_check():
    # Exactly True disarms the backlog...
    assert _safe_backlog({"_issues_truncated": True, "open_issues": [{"title": "x"}]},
                          "open_issues") == []
    # ...a truthy non-True value does not (identity, not truthiness).
    assert _safe_backlog({"_issues_truncated": 1, "open_issues": [{"title": "x"}]},
                          "open_issues") == [{"title": "x"}]
    assert _safe_backlog(None, "open_issues") == []


def test_recent_commits_is_not_read_through_the_truncation_gate():
    # heuristic_plan/philosophy read recent_commits via _baseline_list directly, not
    # _safe_backlog, so a truncated context still yields commit-derived momentum/evidence
    # even though its issue/PR backlog reads empty.
    ctx = {"_issues_truncated": True, "recent_commits": [{"subject": "fix: x"}],
           "open_issues": [{"title": "y"}]}
    assert heuristic_philosophy(ctx)["evidence"] == ["fix: x"]
    assert _safe_backlog(ctx, "open_issues") == []


# --- Heuristic philosophy -----------------------------------------------------------------

def test_philosophy_exact_dict_for_synthetic_context():
    assert heuristic_philosophy(PLAN_CTX) == PHIL_LITERAL


def test_philosophy_dominant_tie_breaks_first_seen():
    # bugfix (first inserted) and feature tie at 1 each; bugfix wins the tie.
    ctx = {"recent_commits": [
        {"subject": "fix: a"}, {"subject": "feat: b"},
    ], "open_issues": []}
    out = heuristic_philosophy(ctx)
    assert out["values"] == ["bugfix", "feature"]
    assert out["summary"].startswith("Recent activity is dominated by bugfix work")


def test_philosophy_empty_history_defaults_to_triage():
    out = heuristic_philosophy({"recent_commits": [], "open_issues": []})
    assert out["values"] == ["triage"]
    assert out["summary"] == "Recent activity is dominated by triage work; 0 open issue(s) await triage."


def test_philosophy_issue_count_includes_untitled_entries():
    # 4 issues total, only 2 titled — the count is the raw list length, not the titled count.
    assert heuristic_philosophy(PLAN_CTX)["summary"].endswith("4 open issue(s) await triage.")


def test_philosophy_malformed_commit_counts_as_triage_vote_and_placeholder():
    ctx = {
        "recent_commits": [
            {"subject": "fix: patch the widget loader"},
            "not-a-dict",
            {"subject": 42},
            {"subject": "feat: add a config knob"},
        ],
        "open_issues": [],
    }
    out = heuristic_philosophy(ctx)
    # triage gets 2 votes (the two malformed entries) and becomes dominant over bugfix/feature
    # at 1 each — the docstring's "logged and skipped" undersells this: it still casts a vote.
    assert out["values"] == ["triage", "bugfix", "feature"]
    assert out["evidence"] == [
        "fix: patch the widget loader", "", "", "feat: add a config knob",
    ]


def test_philosophy_non_dict_context_matches_empty_context():
    assert heuristic_philosophy(None) == heuristic_philosophy({})
    assert heuristic_philosophy("not-a-dict") == heuristic_philosophy({})


# --- Heuristic plan ------------------------------------------------------------------------

def test_heuristic_plan_full_section_order_as_literal():
    assert heuristic_plan(PLAN_CTX, 10) == PLAN_FULL


def test_heuristic_plan_cap_is_a_plain_slice_dropping_later_sections():
    assert heuristic_plan(PLAN_CTX, 3) == PLAN_FULL[:3]
    assert heuristic_plan(PLAN_CTX, 0) == []


def test_heuristic_plan_release_item_is_additional_to_momentum_item():
    titles = [item["title"] for item in PLAN_FULL]
    assert "Continue release work" in titles
    assert "Prepare the next release" in titles


# --- Queue-first -----------------------------------------------------------------------

def test_review_queue_item_shape_and_number_suffix_rules():
    items = _review_queue_items(QUEUE_CTX, None)
    titles = [item["title"] for item in items]
    assert titles == [
        "Review and merge PR: Harden the retry loop (#3)",
        "Review and merge PR: Refresh the cache docs",
        "Review and merge PR: Trim the startup path (#12)",
        "Review and merge PR: Bool number edge case",
    ]
    for item in items:
        assert set(item) == {"title", "kind", "rationale", "theme"}
        assert item["kind"] == "triage"
        assert item["theme"] == "PR review queue"


def test_review_queue_limit_none_is_uncapped():
    assert len(_review_queue_items(QUEUE_CTX, None)) == 4


def test_review_queue_limit_zero_post_append_quirk():
    # As-built divergence from the docstring's "capped at limit": the cap check runs after
    # the append, so limit<=0 still yields the first titled item.
    items = _review_queue_items(QUEUE_CTX, 0)
    assert len(items) == 1
    assert items[0]["title"] == "Review and merge PR: Harden the retry loop (#3)"


def test_queue_first_plan_fills_from_heuristic_when_queue_short():
    # n=10 exceeds the 4-item queue, so queue_first falls through to heuristic_plan for the
    # remainder — n - 4 = 6 slots requested, only 2 heuristic items exist for this context.
    plan = queue_first_plan(QUEUE_CTX, 10)
    assert [item["theme"] for item in plan] == [
        "PR review queue", "PR review queue", "PR review queue", "PR review queue",
        "issue backlog", "bugfix momentum",
    ]


def test_queue_first_plan_equals_heuristic_when_queue_empty():
    assert queue_first_plan(PLAN_CTX, 5) == heuristic_plan(PLAN_CTX, 5)


def test_queue_first_rationale_counts_full_queue_not_capped_items():
    # QUEUE_CTX has 4 titled PRs; capping the plan to n=1 must not shrink the rationale count.
    out = queue_first_solve(context=QUEUE_CTX, n=1)
    assert out["rationale"] == (
        "queue-first baseline: clear 4 open PR(s) in the review queue, "
        "then continue the dominant recent themes"
    )
    # An empty queue still reads "clear 0 open PR(s)" — it does not fall back to the
    # heuristic wrapper's own rationale text even though plan/philosophy do match heuristic.
    empty_queue = queue_first_solve(context=PLAN_CTX)
    assert empty_queue["rationale"].startswith("queue-first baseline: clear 0 open PR(s)")


# --- Stability-first -----------------------------------------------------------------------

def test_stability_rank_table_and_unknown_kind_default():
    assert _STABILITY_KIND_RANK == {
        "bugfix": 0, "refactor": 0, "release": 1,
        "feature": 2, "docs": 2, "dep": 2, "triage": 3,
    }
    assert _stability_rank("bugfix") == 0
    assert _stability_rank("nonexistent-kind") == 3


def test_stability_first_is_a_stable_sort_of_heuristic_plan():
    stab = stability_first_plan(PLAN_CTX, 10)
    heur = heuristic_plan(PLAN_CTX, 10)
    # Same multiset of items, reordered.
    assert sorted(stab, key=lambda i: i["title"]) == sorted(heur, key=lambda i: i["title"])
    # bugfix items sort before feature/release items.
    kinds_in_order = [item["kind"] for item in stab]
    assert kinds_in_order.index("bugfix") < kinds_in_order.index("feature")
    assert kinds_in_order.index("release") < kinds_in_order.index("feature")


def test_stability_cap_applies_before_reorder():
    # The heuristic n=3 cap keeps only [feature-issue, bugfix-issue, bugfix-momentum] before
    # any sort runs; the feature-momentum/release items the uncapped set would contain never
    # exist here for the sort to promote.
    capped = stability_first_plan(PLAN_CTX, 3)
    assert {item["kind"] for item in capped} == {"feature", "bugfix"}
    assert "release" not in {item["kind"] for item in capped}
    # Confirms it's not simply "stability_first_plan(ctx, 10)[:3]".
    uncapped_then_sliced = stability_first_plan(PLAN_CTX, 10)[:3]
    assert capped != uncapped_then_sliced


# --- Solve wrappers ------------------------------------------------------------------------

def test_all_three_solves_share_heuristic_philosophy():
    expected = heuristic_philosophy(PLAN_CTX)
    assert heuristic_solve(context=PLAN_CTX)["philosophy"] == expected
    assert queue_first_solve(context=PLAN_CTX)["philosophy"] == expected
    assert stability_first_solve(context=PLAN_CTX)["philosophy"] == expected


def test_solve_rationale_templates_are_exact():
    assert heuristic_solve(context=PLAN_CTX)["rationale"] == (
        "heuristic baseline: extrapolate the dominant recent themes and address "
        "4 open issue(s)"
    )
    assert stability_first_solve(context=PLAN_CTX)["rationale"] == (
        "stability-first baseline: stabilize before greenfield across "
        "4 open issue(s) and recent-theme momentum"
    )
