"""Contract tests for specs/078-benchmark-baselines — assert baselines.py satisfies the spec's
EARS criteria: the exact registry and unknown-name error, the runner call shape and
context-as-is rule, the empty floor's literal output, the full Conventional-Commit kind
mapping, keyword bucket order and substring semantics, the exact heuristic philosophy dict
(tie-break, malformed-entry triage votes, evidence cap), the ordered heuristic plan and its
plain-slice cap, review-queue item shape and the post-append limit-zero quirk, queue-fill
composition and the uncapped rationale count, the literal stability rank table, and
cap-before-reorder. Literal expected values; offline, deterministic.

Complements tests/test_baselines.py, which owns registry identity, the truncation fail-closed
matrix (#722/#957), release-detection parity (#129), the ci/test bucket (#270),
malformed-container tolerance (#515), and end-to-end run_replay baseline selection.
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
    _infer_kind,
    _review_queue_items,
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

# Four commits (two bugfix, one feature, one release) and four issue entries, only two of
# which carry a usable title. Every expectation below is a hand-derived literal.
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

# Four titled PRs (one with a string number), one titled issue, one bugfix commit.
QUEUE_CTX = {
    "open_prs": [
        {"number": 3, "title": "Harden the retry loop"},
        {"number": "7", "title": "Refresh the cache docs"},
        {"number": 11, "title": "Wire up the profile parser"},
        {"number": 12, "title": "Trim the startup path"},
    ],
    "open_issues": [{"title": "Crash when the cache is cold"}],
    "recent_commits": [{"subject": "fix: close the socket leak"}],
}


# --- Registry (`BASELINES`, `DEFAULT_BASELINE`, `get_baseline`) ---------------------------

def test_registry_is_exactly_four_names_with_empty_default():
    # Exact equality (test_baselines.py only pins a superset) plus the documented default.
    assert set(BASELINES) == {"empty", "heuristic", "queue_first", "stability_first"}
    assert DEFAULT_BASELINE == "empty"
    assert BASELINES[DEFAULT_BASELINE] is empty_solve


def test_unknown_name_error_message_and_unhashable_passthrough():
    with pytest.raises(ValueError) as exc:
        get_baseline("bogus")
    assert str(exc.value) == (
        "unknown baseline 'bogus'; "
        "choose from ['empty', 'heuristic', 'queue_first', 'stability_first']"
    )
    assert exc.value.__cause__ is None and exc.value.__suppress_context__
    # As-built: only the lookup miss is translated; an unhashable name propagates TypeError.
    with pytest.raises(TypeError):
        get_baseline(["empty"])


# --- Solve-call shape (all four baselines) ------------------------------------------------

def test_every_baseline_accepts_the_runner_call_shape():
    # The runner calls `opponent(dest, request, context=ctx, n=horizon)`; **_kw makes a
    # future runner-side keyword non-breaking. Every output shows the judged surface.
    for name in ("empty", "heuristic", "queue_first", "stability_first"):
        out = BASELINES[name](
            "/nonexistent-repo-path", "keep the build green",
            context=dict(PLAN_CTX), n=2, future_runner_kw=True,
        )
        assert set(out) == {"philosophy", "plan", "action", "rationale"}, name
        assert out["action"] == "plan", name


def test_falsy_context_is_used_as_is_never_load_context():
    # `context={}` must be honored as-is: `load_context` runs only on `context is None`.
    # On this nonexistent repo_path a fallback to load_context would raise, so an
    # `context or load_context(...)` mutant cannot pass here.
    for solve in (heuristic_solve, queue_first_solve, stability_first_solve):
        out = solve(repo_path="/nonexistent-repo-path", context={}, n=5)
        assert out["plan"] == [], solve
        assert out["philosophy"]["values"] == ["triage"], solve


# --- The `empty` floor --------------------------------------------------------------------

def test_empty_solve_exact_literal_and_input_invariance():
    expected = {"plan": [], "philosophy": {}, "action": "plan", "rationale": "baseline"}
    assert empty_solve() == expected
    assert empty_solve("/anywhere", "any request", context=dict(PLAN_CTX), n=9, x=1) == expected
    # A fresh dict per call: mutating one output cannot leak into the next comparison.
    first = empty_solve()
    first["plan"].append("junk")
    assert empty_solve() == expected


# --- Kind inference (`_infer_kind`, `_COMMIT_KIND_TO_BASELINE`, `_KIND_KEYWORDS`) ---------

def test_infer_kind_maps_every_conventional_commit_kind():
    # The full normalized-commit-kind -> planner-vocabulary table, one probe per CC type.
    table = {
        "feat: add a widget": "feature",
        "fix: close the socket leak": "bugfix",
        "docs: describe the cache format": "docs",
        "refactor: split the loader": "refactor",
        "perf: speed up the cache": "refactor",
        "ci: pin the runner image": "refactor",
        "test: cover the loader": "refactor",
        "build: pin the toolchain": "refactor",
        "style: reformat the loader": "refactor",
        "chore: tidy the manifest": "dep",
        "revert: undo the loader split": "bugfix",
    }
    for subject, expected in table.items():
        assert _infer_kind(subject) == expected, subject


def test_keyword_buckets_first_match_wins_substring_semantics():
    # Bucket order dep, docs, bugfix, refactor, feature, test — earlier bucket wins.
    assert _infer_kind("bump the guide") == "dep"        # dep beats docs
    assert _infer_kind("fix the guide") == "docs"        # docs beats bugfix
    # Needles are plain substrings, not word matches.
    assert _infer_kind("address the situation") == "feature"   # "add" inside "address"
    assert _infer_kind("precision loss") == "refactor"         # "ci" inside "precision"
    # Nothing matched, or falsy input: triage. (A truthy non-string is out of contract —
    # callers coerce through _commit_subject/_issue_title/_pr_title first.)
    assert _infer_kind("totally unrelated words") == "triage"
    assert _infer_kind("") == "triage"
    assert _infer_kind(None) == "triage"


# --- Context coercion ---------------------------------------------------------------------

def test_baseline_list_returns_same_object_and_rejects_tuple():
    rows = [{"subject": "fix: close the socket leak"}]
    assert _baseline_list(rows, "recent_commits") is rows       # unchanged, not copied
    assert _baseline_list(({"subject": "x"},), "recent_commits") == []   # tuple is not a list


def test_truncated_context_keeps_commit_evidence_and_momentum():
    # _issues_truncated blanks only the backlog/queue; recent_commits is not gated, so the
    # philosophy evidence and the momentum/cadence items survive (the flag must not
    # over-blank the opponent). The fail-closed side is pinned in tests/test_baselines.py.
    truncated = {**PLAN_CTX, "_issues_truncated": True}
    assert heuristic_philosophy(truncated)["evidence"] == PHIL_LITERAL["evidence"]
    assert [item["title"] for item in heuristic_plan(truncated, 99)] == [
        "Continue bugfix work",
        "Continue feature work",
        "Continue release work",
        "Prepare the next release",
    ]


# --- Heuristic philosophy (`heuristic_philosophy`) ----------------------------------------

def test_philosophy_exact_literal_dict():
    # The whole dict, pinned: key set, both templates, top-3 values in frequency order, and
    # an issue count that is the *list* length (4) — malformed entries included — even
    # though only two issues are plannable.
    assert heuristic_philosophy(PLAN_CTX) == PHIL_LITERAL
    # Empty history: dominant is triage, values ["triage"]; a non-dict context yields
    # exactly the empty-context output, not some other fallback.
    empty_phil = {
        "summary": "Recent activity is dominated by triage work; 0 open issue(s) await triage.",
        "values": ["triage"],
        "merge_bar": "inferred from recent commit patterns (no explicit signal)",
        "direction": "continue triage-oriented work and clear the issue backlog",
        "evidence": [],
    }
    assert heuristic_philosophy({}) == empty_phil
    assert heuristic_philosophy("not a dict") == empty_phil


def test_philosophy_dominant_tie_breaks_to_first_seen_kind():
    docs_first = {"recent_commits": [{"subject": "docs: describe the cache format"},
                                     {"subject": "fix: close the socket leak"}]}
    fix_first = {"recent_commits": list(reversed(docs_first["recent_commits"]))}
    assert heuristic_philosophy(docs_first)["summary"] == (
        "Recent activity is dominated by docs work; 0 open issue(s) await triage."
    )
    assert heuristic_philosophy(fix_first)["summary"] == (
        "Recent activity is dominated by bugfix work; 0 open issue(s) await triage."
    )


def test_philosophy_counts_malformed_commits_as_triage_votes():
    # A malformed entry is not dropped: it coerces to "" (one evidence placeholder each)
    # and "" infers triage, so two junk entries outvote the one real bugfix commit.
    ctx = {"recent_commits": [
        {"subject": "fix: patch the widget loader"},
        77,
        {"subject": ["nested", "list"]},
    ]}
    phil = heuristic_philosophy(ctx)
    assert phil["values"] == ["triage", "bugfix"]
    assert phil["summary"] == (
        "Recent activity is dominated by triage work; 0 open issue(s) await triage."
    )
    assert phil["evidence"] == ["fix: patch the widget loader", "", ""]


def test_philosophy_evidence_caps_at_first_five_subjects():
    ctx = {"recent_commits": [{"subject": f"fix: close leak {i}"} for i in range(7)]}
    assert heuristic_philosophy(ctx)["evidence"] == [
        "fix: close leak 0", "fix: close leak 1", "fix: close leak 2",
        "fix: close leak 3", "fix: close leak 4",
    ]


# --- Heuristic plan (`heuristic_plan`) ----------------------------------------------------

def test_heuristic_plan_full_section_order_as_literal_items():
    # Sections in order: titled issues (backlog order), momentum by frequency then
    # first-seen, then the single release-cadence item *alongside* release momentum.
    # Titleless/malformed issue entries yield no item.
    assert heuristic_plan(PLAN_CTX, 99) == PLAN_FULL
    # The cadence item is keyed to a *release* inference specifically: a bugfix-only
    # history earns none, a release-only history earns momentum *plus* cadence.
    assert [item["title"] for item in heuristic_plan(
        {"recent_commits": [{"subject": "fix: close the socket leak"}]}, 99)
    ] == ["Continue bugfix work"]
    assert [item["title"] for item in heuristic_plan(
        {"recent_commits": [{"subject": "Release v0.3.0"}]}, 99)
    ] == ["Continue release work", "Prepare the next release"]


def test_heuristic_plan_cap_is_a_plain_slice():
    assert heuristic_plan(PLAN_CTX, 3) == PLAN_FULL[:3]
    assert heuristic_plan(PLAN_CTX, 0) == []


# --- Queue-first (`_review_queue_items`, `queue_first_plan`, `queue_first_solve`) ---------

def test_review_item_shape_and_number_ref_rules():
    items = _review_queue_items(QUEUE_CTX, 2)
    assert len(items) == 2
    # Exact item shape, including the " (#3)" suffix for a real int number...
    assert items[0] == {
        "title": "Review and merge PR: Harden the retry loop (#3)",
        "kind": "triage",
        "rationale": "open pull request awaiting review; clear the queue before greenfield work",
        "theme": "PR review queue",
    }
    # ...and no suffix for a string number (tests/test_baselines.py pins the bool case).
    assert items[1]["title"] == "Review and merge PR: Refresh the cache docs"


def test_review_queue_limit_none_and_post_append_zero_quirk():
    assert len(_review_queue_items(QUEUE_CTX, None)) == 4        # None = uncapped
    # As-built: the cap check runs after append, so limit=0 still emits the first titled
    # item; queue_first_plan's outer slice contains it, so the plan-level cap holds.
    assert [item["title"] for item in _review_queue_items(QUEUE_CTX, 0)] == [
        "Review and merge PR: Harden the retry loop (#3)",
    ]
    assert queue_first_plan(QUEUE_CTX, 0) == []


def test_queue_first_composition_queue_then_heuristic_fill():
    # Queue fills the horizon: review items only, in queue order.
    assert [item["title"] for item in queue_first_plan(QUEUE_CTX, 2)] == [
        "Review and merge PR: Harden the retry loop (#3)",
        "Review and merge PR: Refresh the cache docs",
    ]
    # Queue leaves room: reviews first, then the heuristic plan fills the remainder.
    assert [item["title"] for item in queue_first_plan(QUEUE_CTX, 5)] == [
        "Review and merge PR: Harden the retry loop (#3)",
        "Review and merge PR: Refresh the cache docs",
        "Review and merge PR: Wire up the profile parser (#11)",
        "Review and merge PR: Trim the startup path (#12)",
        "Address issue: Crash when the cache is cold",
    ]


def test_queue_first_rationale_counts_full_queue_not_capped_items():
    out = queue_first_solve(context=QUEUE_CTX, n=2)
    assert len(out["plan"]) == 2
    assert out["rationale"] == (
        "queue-first baseline: clear 4 open PR(s) in the review queue, "
        "then continue the dominant recent themes"
    )


# --- Stability-first (`stability_first_plan`, `_stability_rank`) --------------------------

def test_stability_rank_table_and_unknown_kind_literal():
    assert _STABILITY_KIND_RANK == {
        "bugfix": 0, "refactor": 0, "release": 1,
        "feature": 2, "docs": 2, "dep": 2, "triage": 3,
    }
    assert _stability_rank("mystery-kind") == 3


def test_stability_first_reorders_capped_plan_as_literal():
    # Stable sort by tier over the heuristic items: bugfix tier first (heuristic order
    # within it), then both release items, then the feature tier, triage absent here.
    assert [item["title"] for item in stability_first_plan(PLAN_CTX, 6)] == [
        "Address issue: Crash when the cache is cold",
        "Continue bugfix work",
        "Continue release work",
        "Prepare the next release",
        "Address issue: Support nested profiles",
        "Continue feature work",
    ]


def test_stability_cap_applies_before_reorder():
    # The sort runs over heuristic_plan(ctx, n), so truncation follows *heuristic* order:
    # at n=2 only the two issue items survive; the rank-0 "Continue bugfix work" momentum
    # item is NOT resurrected by its priority.
    titles = [item["title"] for item in stability_first_plan(PLAN_CTX, 2)]
    assert titles == [
        "Address issue: Crash when the cache is cold",
        "Address issue: Support nested profiles",
    ]
    assert "Continue bugfix work" not in titles


# --- Solve wrappers -----------------------------------------------------------------------

def test_solve_rationale_literals_and_shared_philosophy():
    heuristic = heuristic_solve(context=PLAN_CTX, n=5)
    stability = stability_first_solve(context=PLAN_CTX, n=5)
    queue = queue_first_solve(context=PLAN_CTX, n=5)
    assert heuristic["rationale"] == (
        "heuristic baseline: extrapolate the dominant recent themes and address "
        "4 open issue(s)"
    )
    assert stability["rationale"] == (
        "stability-first baseline: stabilize before greenfield across "
        "4 open issue(s) and recent-theme momentum"
    )
    # All three non-empty opponents share the same philosophy for the same context.
    for out in (heuristic, stability, queue):
        assert out["philosophy"] == PHIL_LITERAL
    # The signature default is n=5: with no n argument, the six candidate items are
    # capped at the first five in heuristic order.
    assert heuristic_solve(context=PLAN_CTX)["plan"] == PLAN_FULL[:5]


def test_philosophy_values_cap_at_the_top_three_kinds():
    # Five commits spanning FOUR distinct kinds (bugfix x2, feature, docs, dep): `values`
    # surfaces only the top three, most-common first, ties broken by first-seen order —
    # the fourth kind (dep, from the chore prefix) is cut by the cap.
    ctx = {"recent_commits": [
        {"subject": "fix: patch the loader"},
        {"subject": "fix: close the leak"},
        {"subject": "feat: add a knob"},
        {"subject": "docs: expand the guide"},
        {"subject": "chore: bump the pin"},
    ]}
    assert heuristic_philosophy(ctx)["values"] == ["bugfix", "feature", "docs"]


def test_allowed_vocabulary_is_exactly_the_seven_keyword_kinds():
    # The keyword pass emits a kind only when it sits in _ALLOWED; the set is the exact
    # seven-kind vocabulary below. "simplify" reaches the refactor bucket and survives
    # the gate — dropping any member would silently turn its bucket into triage.
    assert _ALLOWED == {"feature", "bugfix", "refactor", "docs", "release", "dep", "triage"}
    assert _infer_kind("simplify the loader") == "refactor"


def test_keyword_bucket_order_pins_the_remaining_adjacencies():
    # First-match-wins across dep, docs, bugfix, refactor, feature, test. "fix the
    # cleanup path" holds a bugfix keyword and a refactor keyword ("cleanup") — bugfix
    # wins. "add test coverage" holds a feature keyword ("add") and test keywords —
    # feature wins.
    assert _infer_kind("fix the cleanup path") == "bugfix"
    assert _infer_kind("add test coverage") == "feature"


def test_none_context_consults_load_context(monkeypatch):
    # context=None is the one path that consults load_context(repo_path); the canned
    # context it returns must drive the plan (no git repo involved).
    canned = {"recent_commits": [{"subject": "docs: expand the install guide"}]}
    monkeypatch.setattr("benchmark.baselines.load_context", lambda repo_path: canned)
    out = heuristic_solve(repo_path="/anywhere", context=None, n=5)
    assert out["plan"][0]["title"] == "Continue docs work"


def test_all_four_solves_share_the_documented_signature():
    import inspect
    expected = "repo_path=None, request='', context=None, n=5, **_kw"
    for solve in (empty_solve, heuristic_solve, queue_first_solve, stability_first_solve):
        params = inspect.signature(solve).parameters.values()
        assert ", ".join(str(p) for p in params) == expected
