"""Tests for frozen-context leakage auditing."""

import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from benchmark.leakage import scrub_context  # noqa: E402
from benchmark.leakage_audit import audit_context, audit_headline, is_clean  # noqa: E402

_LEAKY_CTX = {
    "readme_excerpt": "roadmap; tracked in #101",
    "recent_commits": [{"subject": "work on #200 via deadBEEF"}],
    "open_issues": [{"title": "dup of #300"}],
    "open_prs": [{"title": "see https://github.com/o/r/pull/900"}],
    "milestones": [{"title": "v2 at commit a1b2c3d4e5f6"}],
    "releases": [{"tag": "v2.0-fixes-#900", "name": "Release https://github.com/o/r/releases/tag/v2.0"}],
}


def test_audit_context_flags_all_scrubbable_fields():
    findings = audit_context(_LEAKY_CTX)
    locations = {row["location"] for row in findings}
    assert "readme_excerpt" in locations
    assert "recent_commits[0].subject" in locations
    assert "open_issues[0].title" in locations
    assert "open_prs[0].title" in locations
    assert "milestones[0].title" in locations
    assert "releases[0].tag" in locations
    assert "releases[0].name" in locations
    for row in findings:
        assert row["masked"] != row["value"]
        assert "#ref" in row["masked"] or "<link>" in row["masked"] or "<sha>" in row["masked"]


def test_scrubbed_context_audits_clean():
    scrubbed = scrub_context(_LEAKY_CTX)
    assert audit_context(scrubbed) == []
    assert is_clean(scrubbed)


def test_is_clean_gates_leaky_vs_scrubbed():
    assert not is_clean(_LEAKY_CTX)
    assert is_clean(scrub_context(_LEAKY_CTX))


def test_audit_context_preserves_plain_numbers():
    ctx = {"readme_excerpt": "supports 2500000 requests per second"}
    assert audit_context(ctx) == []
    assert is_clean(ctx)


def test_audit_context_tolerates_malformed_context():
    for bad in (None, 42, "not a dict", [], True):
        assert audit_context(bad) == []
        assert is_clean(bad)


def test_audit_context_tolerates_non_list_list_fields():
    ctx = {
        "readme_excerpt": "ok",
        "recent_commits": 42,
        "open_issues": {"title": "Fix #900"},
        "open_prs": None,
    }
    assert audit_context(ctx) == []


def test_audit_context_skips_non_dict_rows_and_empty_text():
    ctx = {
        "open_issues": [42, None, {"title": ""}, {"title": ["Fix #900"]}],
        "recent_commits": [{"subject": "Fix #123"}],
    }
    findings = audit_context(ctx)
    assert len(findings) == 1
    assert findings[0]["location"] == "recent_commits[0].subject"


def test_audit_headline_summarizes_findings():
    assert "clean" in audit_headline([])
    assert "2 leak" in audit_headline([{}, {}])


def test_audit_cli_reports_and_strict_exit(tmp_path):
    path = tmp_path / "ctx.json"
    path.write_text(json.dumps(_LEAKY_CTX), encoding="utf-8")

    ok = subprocess.run(
        [sys.executable, "-m", "scripts.audit_context", str(path)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert ok.returncode == 0
    assert "leak" in ok.stderr.lower()
    report = json.loads(ok.stdout)
    assert report["clean"] is False
    assert len(report["findings"]) >= 1

    bad = subprocess.run(
        [sys.executable, "-m", "scripts.audit_context", str(path), "--strict"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert bad.returncode == 1

    clean_path = tmp_path / "clean.json"
    clean_path.write_text(json.dumps(scrub_context(_LEAKY_CTX)), encoding="utf-8")
    strict_ok = subprocess.run(
        [sys.executable, "-m", "scripts.audit_context", str(clean_path), "--strict"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert strict_ok.returncode == 0
    assert json.loads(strict_ok.stdout)["clean"] is True
