"""Contract tests for specs/022-benchmark-leakage-audit — assert leakage_audit.py satisfies
the spec's EARS criteria: audited fields, malformed-context handling, findings-list logging,
and audit_headline robustness. Offline, deterministic.
"""

import copy
import logging
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from benchmark.leakage import scrub_context  # noqa: E402
from benchmark.leakage_audit import (  # noqa: E402
    _findings_list,
    audit_context,
    audit_headline,
    is_clean,
)

_LEAKY_CTX = {
    "readme_excerpt": "roadmap; tracked in #101",
    "recent_commits": [{"subject": "work on #200 via deadBEEF"}],
    "open_issues": [{"title": "dup of #300"}],
    "open_prs": [{"title": "see https://github.com/o/r/pull/900"}],
    "milestones": [{"title": "v2 at commit a1b2c3d4e5f6"}],
    "releases": [{"tag": "v2.0-fixes-#900", "name": "Release https://github.com/o/r/releases/tag/v2.0"}],
}

_MALFORMED_FINDINGS = [42, 3.14, True, {"location": "readme_excerpt"}, "not a list"]

_NON_DICT_CONTEXTS = [None, 42, "not a dict", [], True]


# --- Audited fields -----------------------------------------------------------------------


def test_audit_context_flags_scrubbable_fields():
    findings = audit_context(_LEAKY_CTX)
    locations = {row["location"] for row in findings}
    assert "readme_excerpt" in locations
    assert "recent_commits[0].subject" in locations
    assert "open_issues[0].title" in locations
    assert "open_prs[0].title" in locations
    assert "milestones[0].title" in locations
    assert "releases[0].tag" in locations
    assert "releases[0].name" in locations


def test_finding_shape_and_masked_differs_from_value():
    findings = audit_context(_LEAKY_CTX)
    assert findings
    for row in findings:
        assert set(row) == {"location", "value", "masked"}
        assert row["masked"] != row["value"]
        assert "#ref" in row["masked"] or "<link>" in row["masked"] or "<sha>" in row["masked"]


# --- Non-dict and malformed context handling ----------------------------------------------


@pytest.mark.parametrize("bad", _NON_DICT_CONTEXTS)
def test_non_dict_context_returns_empty_findings(bad):
    assert audit_context(bad) == []


def test_malformed_list_fields_are_skipped():
    ctx = {
        "readme_excerpt": "ok",
        "recent_commits": 42,
        "open_issues": {"title": "Fix #900"},
        "open_prs": None,
    }
    assert audit_context(ctx) == []


def test_skips_non_dict_rows_and_empty_text():
    ctx = {
        "open_issues": [42, None, {"title": ""}, {"title": ["Fix #900"]}],
        "recent_commits": [{"subject": "Fix #123"}],
    }
    findings = audit_context(ctx)
    assert len(findings) == 1
    assert findings[0]["location"] == "recent_commits[0].subject"


# --- Clean gate ---------------------------------------------------------------------------


def test_is_clean_false_when_leaks_present():
    assert not is_clean(_LEAKY_CTX)


@pytest.mark.parametrize("bad", _NON_DICT_CONTEXTS)
def test_is_clean_true_for_non_dict_context(bad):
    assert is_clean(bad)


# --- Scrub alignment ----------------------------------------------------------------------


def test_scrubbed_context_audits_clean():
    scrubbed = scrub_context(_LEAKY_CTX)
    assert audit_context(scrubbed) == []
    assert is_clean(scrubbed)


# --- False-positive guard -----------------------------------------------------------------


def test_plain_numbers_not_flagged():
    ctx = {"readme_excerpt": "supports 2500000 requests per second"}
    assert audit_context(ctx) == []
    assert is_clean(ctx)


# --- Findings-list sanitization (logging contract) ----------------------------------------


def test_findings_list_returns_list_unchanged():
    rows = [{"location": "readme_excerpt", "value": "x", "masked": "y"}]
    assert _findings_list(rows) == rows


def test_findings_list_none_and_empty_are_silent(caplog):
    with caplog.at_level(logging.WARNING, logger="benchmark.leakage_audit"):
        assert _findings_list(None) == []
        assert _findings_list([]) == []
    assert not caplog.records


@pytest.mark.parametrize("bad", _MALFORMED_FINDINGS)
def test_findings_list_non_list_returns_empty(bad):
    assert _findings_list(bad) == []


def test_findings_list_logs_warning_for_non_list_container(caplog):
    with caplog.at_level(logging.WARNING, logger="benchmark.leakage_audit"):
        assert _findings_list(42) == []
    assert any("findings is int" in r.message for r in caplog.records)


# --- Audit headline -----------------------------------------------------------------------


def test_audit_headline_clean_when_no_findings():
    assert audit_headline([]) == "audit_context: clean (no forward-reference leaks)"


def test_audit_headline_reports_leak_count():
    assert "2 leak" in audit_headline([{}, {}])


@pytest.mark.parametrize("bad", _MALFORMED_FINDINGS)
def test_audit_headline_survives_non_list_findings(bad):
    assert audit_headline(bad) == "audit_context: clean (no forward-reference leaks)"


def test_audit_headline_logs_warning_for_non_list_findings(caplog):
    with caplog.at_level(logging.WARNING, logger="benchmark.leakage_audit"):
        line = audit_headline(42)
    assert line == "audit_context: clean (no forward-reference leaks)"
    assert any("findings is int" in r.message for r in caplog.records)


# --- Pure evaluation ----------------------------------------------------------------------


def test_audit_context_does_not_mutate_context():
    ctx = copy.deepcopy(_LEAKY_CTX)
    before = copy.deepcopy(ctx)
    audit_context(ctx)
    assert ctx == before
