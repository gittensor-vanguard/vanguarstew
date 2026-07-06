"""Tests for the frozen-context leakage audit (deterministic, offline)."""

import copy
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from benchmark.leakage import scrub_context  # noqa: E402
from benchmark.leakage_audit import audit_context, audit_headline, is_clean  # noqa: E402

# A context whose free-text fields carry forward references in every scrubbed field.
_LEAKY = {
    "readme_excerpt": "roadmap: see https://github.com/o/r/pull/900 next",
    "recent_commits": [
        {"subject": "safe subject"},
        {"subject": "part of #512, follow-up work"},
    ],
    "open_issues": [{"title": "Fix bug (tracked in #777)"}],
    "open_prs": [{"title": "clean title"}],
    "milestones": [{"title": "v2 planning at f00ba47c0ffee"}],
    "releases": [{"tag": "v1.0.0"}, {"name": "see https://github.com/o/r/releases/tag/v2.0.0"}],
}


def test_audit_flags_every_leaky_field_with_its_location():
    findings = audit_context(_LEAKY)
    fields = {f["field"] for f in findings}
    assert "readme_excerpt" in fields
    assert "recent_commits[1].subject" in fields          # index locates the leaky entry
    assert "open_issues[0].title" in fields
    assert "milestones[0].title" in fields
    assert "releases[1].name" in fields
    # The safe entries are not flagged.
    assert "recent_commits[0].subject" not in fields
    assert "open_prs[0].title" not in fields
    assert "releases[0].tag" not in fields


def test_findings_show_the_original_and_masked_forms():
    finding = next(f for f in audit_context(_LEAKY) if f["field"] == "open_issues[0].title")
    assert finding["text"] == "Fix bug (tracked in #777)"      # the leaky original
    assert finding["scrubbed"] == "Fix bug (tracked in #ref)"  # the masked form
    assert "#777" not in finding["scrubbed"]


def test_is_clean_is_false_for_a_leaky_context():
    assert is_clean(_LEAKY) is False


def test_a_scrubbed_context_audits_clean():
    # The whole point: after scrub_context, the audit finds nothing.
    scrubbed = scrub_context(_LEAKY)
    assert audit_context(scrubbed) == []
    assert is_clean(scrubbed) is True


def test_clean_context_and_empty_context_audit_clean():
    clean = {
        "readme_excerpt": "a normal readme with no forward references",
        "recent_commits": [{"subject": "Add loader"}],
        "open_issues": [{"title": "Support YAML"}],
    }
    assert audit_context(clean) == []
    assert is_clean(clean) is True
    assert audit_context({}) == [] and is_clean({}) is True


def test_audit_tolerates_a_malformed_context():
    # Non-dict context, non-list fields, non-dict items, and non-string text must not crash.
    assert audit_context("not a dict") == []
    assert audit_context(None) == []
    malformed = {
        "readme_excerpt": 123,                         # non-string -> skipped
        "recent_commits": "not-a-list",                # non-list -> skipped
        "open_issues": ["not-a-dict", {"title": 5}, {}],  # non-dict / non-string / missing key
        "releases": [{"tag": None}],
    }
    assert audit_context(malformed) == []
    assert is_clean(malformed) is True


def test_releases_tag_and_name_are_both_audited():
    leaky_tag = {"releases": [{"tag": "part of #900"}]}
    leaky_name = {"releases": [{"name": "see https://github.com/o/r/pull/5"}]}
    assert [f["field"] for f in audit_context(leaky_tag)] == ["releases[0].tag"]
    assert [f["field"] for f in audit_context(leaky_name)] == ["releases[0].name"]


def test_audit_headline_summarizes_leaks():
    assert audit_headline([]) == "leakage audit: clean"
    line = audit_headline(audit_context(_LEAKY))
    assert line.startswith("leakage audit:") and "leak(s) in" in line
    assert "readme_excerpt" in line


def test_audit_detects_each_forward_reference_kind():
    # The three vector kinds the scrubber masks are each caught by the audit.
    issue_ref = audit_context({"recent_commits": [{"subject": "fixes #900 upstream"}]})
    assert issue_ref and "#900" not in issue_ref[0]["scrubbed"]     # issue/PR backref -> #ref

    gh_link = audit_context({"readme_excerpt": "see https://github.com/o/r/pull/12 for the plan"})
    assert gh_link and "<link>" in gh_link[0]["scrubbed"]           # github deep-link -> <link>

    sha = audit_context({"open_prs": [{"title": "revert 1a2b3c4d5e6f7a8b for now"}]})
    assert sha and "<sha>" in sha[0]["scrubbed"]                    # raw SHA -> <sha>


def test_audit_counts_multiple_leaks_across_and_within_fields():
    ctx = {
        "recent_commits": [{"subject": "part of #1"}, {"subject": "closes #2"}],
        "open_issues": [{"title": "ref https://github.com/o/r/issues/3"}],
    }
    findings = audit_context(ctx)
    assert len(findings) == 3
    assert [f["field"] for f in findings] == [
        "recent_commits[0].subject", "recent_commits[1].subject", "open_issues[0].title",
    ]


def test_is_clean_gates_a_freshly_frozen_then_scrubbed_context():
    # End-to-end contract for a CI gate: a leaky context fails, its scrubbed form passes.
    assert is_clean(_LEAKY) is False
    assert is_clean(scrub_context(_LEAKY)) is True


def test_bare_numeric_tokens_are_not_treated_as_shas():
    # A bare number (a year/count) is not a SHA and must not be flagged (matches the scrubber's
    # deliberate policy of preserving numeric tokens).
    assert audit_context({"recent_commits": [{"subject": "bump timeout to 30000 ms in 2024"}]}) == []


def test_finding_snippets_are_truncated():
    # Very long fields are truncated in the finding so the report stays readable.
    long_leak = "start " + ("x" * 500) + " fixes #900"
    finding = audit_context({"readme_excerpt": long_leak})[0]
    assert len(finding["text"]) <= 120 and len(finding["scrubbed"]) <= 120


def test_audit_matches_scrubber_across_all_field_types():
    # For every field the scrubber touches, "leaky per the audit" iff "changed by the scrubber",
    # so audit and scrub can never disagree about what counts as a leak.
    ctx = {
        "readme_excerpt": "see https://github.com/o/r/commit/abc1234 and #5",
        "recent_commits": [{"subject": "closes #9"}],
        "open_issues": [{"title": "ref f00ba47c0ffee1234"}],
        "open_prs": [{"title": "https://github.com/o/r/pull/7"}],
        "milestones": [{"title": "plain milestone"}],
        "releases": [{"tag": "v1.0.0"}, {"name": "cut from #12"}],
    }
    scrubbed = scrub_context(ctx)
    leaky_fields = {f["field"].split("[")[0] for f in audit_context(ctx)}
    # Fields the scrubber changed are exactly the ones the audit flags (by top-level key).
    assert "readme_excerpt" in leaky_fields
    assert {"recent_commits", "open_issues", "open_prs", "releases"} <= leaky_fields
    assert "milestones" not in leaky_fields          # the one clean field is not flagged
    assert is_clean(scrubbed) is True                # and its scrubbed form is fully clean


def test_audit_does_not_mutate_the_context():
    snapshot = copy.deepcopy(_LEAKY)
    audit_context(_LEAKY)
    assert _LEAKY == snapshot
