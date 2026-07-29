import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import benchmark_pr_policy as policy


def _issue(*, approved=True, state="open", pull_request=False):
    value = {
        "state": state,
        "labels": [{"name": policy.APPROVAL_LABEL if approved else "benchmark"}],
    }
    if pull_request:
        value["pull_request"] = {"url": "https://example.invalid/pr"}
    return value


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("benchmark/score.py", True),
        ("./benchmark/score.py", True),
        ("scripts/score_pr_delta.py", True),
        ("scripts/compare_eval.py", True),
        ("scripts/leaderboard_feed.py", True),
        ("scripts/benchmark_pr_policy.py", True),
        ("scripts/unrelated_helper.py", True),
        ("docs/architecture.md", True),
        ("docs/nested/example.txt", True),
        ("blog/release.md", True),
        ("README.md", True),
        ("roadmap.MD", True),
        ("src/README.md", True),
        (".github/workflows/benchmark-change-policy.yml", True),
        (".github/workflows/pr-integrity.yml", True),
        ("CONTRIBUTING.md", True),
        ("docs/polaris-benchmark-seal.md", True),
        ("REVIEW.md", True),
        ("scripts/plan_polaris_benchmark.py", True),
        ("scripts/run_polaris_benchmark.py", True),
        ("scripts/sandbox_candidate_entry.py", True),
        ("scripts/verify_polaris_benchmark.py", True),
        ("benchmarking/readme.md", True),
        ("benchmarking/data.json", False),
        ("agent/planner.py", False),
        ("notes.txt", False),
        (42, False),
    ],
)
def test_touches_guardrail_paths(path, expected):
    assert policy.touches_guardrail([path]) is expected


def test_touches_guardrail_rejects_malformed_collections():
    assert policy.touches_guardrail(None) is False
    assert policy.touches_guardrail("benchmark/score.py") is False


def test_referenced_issues_requires_linking_verb_and_deduplicates():
    body = "Refs #12, fixes: #7, and ReFs #12. Bare #99 and owner/repo#31 do not approve."
    assert policy.referenced_issues(body) == (12, 7)
    assert policy.referenced_issues(None) == ()


def test_issue_approval_is_strict():
    assert policy.issue_is_approved(_issue()) is True
    assert policy.issue_is_approved(_issue(approved=False)) is False
    assert policy.issue_is_approved(_issue(state="closed")) is False
    assert policy.issue_is_approved(_issue(pull_request=True)) is False
    assert policy.issue_is_approved({"state": "open", "labels": [policy.APPROVAL_LABEL]}) is False


def test_policy_allows_non_guardrail_and_maintainer_changes():
    ordinary = policy.evaluate_policy(
        author="contributor",
        paths=["agent/planner.py"],
        body="",
        issues={},
    )
    assert ordinary == {"allowed": True, "reason": "not a protected change"}

    maintainer = policy.evaluate_policy(
        author="matedev01",
        paths=["benchmark/score.py"],
        body="",
        issues={},
    )
    assert maintainer == {"allowed": True, "reason": "maintainer-authored protected change"}


def test_policy_requires_matching_open_approved_issue():
    allowed = policy.evaluate_policy(
        author="contributor",
        paths=["benchmark/score.py"],
        body="Refs #17",
        issues={17: _issue()},
    )
    assert allowed == {"allowed": True, "reason": "approved by open issue #17", "issue": 17}

    denied = policy.evaluate_policy(
        author="contributor",
        paths=["benchmark/score.py"],
        body="Refs #17 and fixes #18",
        issues={17: _issue(state="closed"), 18: _issue(approved=False)},
    )
    assert denied == {
        "allowed": False,
        "reason": "protected change lacks an approved open issue",
        "referenced_issues": [17, 18],
    }


@pytest.mark.parametrize(
    "changed_path",
    [
        "benchmark/score.py",
        "scripts/helper.py",
        "docs/architecture.md",
        "blog/update.md",
        "README.md",
    ],
)
def test_enforce_closes_unapproved_guardrail_pr(monkeypatch, changed_path):
    calls = []
    comments = []
    monkeypatch.setattr(policy, "_changed_files", lambda repo, number: [changed_path])
    monkeypatch.setattr(policy, "_issues", lambda repo, numbers: {12: _issue(approved=False)})
    monkeypatch.setattr(
        policy,
        "_sync_close_comment",
        lambda repo, number, body: comments.append((repo, number, body)),
    )
    monkeypatch.setattr(policy, "_gh", lambda *args: calls.append(args) or "")
    event = {
        "pull_request": {
            "number": 9,
            "body": "Refs #12",
            "user": {"login": "contributor"},
        }
    }

    decision = policy.enforce(event, "owner/repo")

    assert decision["allowed"] is False
    assert len(comments) == 1
    assert policy.APPROVAL_LABEL in comments[0][2]
    assert policy.COMMENT_MARKER in comments[0][2]
    assert calls == (
        [
            (
                "api",
                "--method",
                "PATCH",
                "repos/owner/repo/pulls/9",
                "-f",
                "state=closed",
            )
        ]
    )


def test_enforce_approved_change_has_no_public_mutation(monkeypatch):
    monkeypatch.setattr(policy, "_changed_files", lambda repo, number: ["benchmark/score.py"])
    monkeypatch.setattr(policy, "_issues", lambda repo, numbers: {12: _issue()})
    monkeypatch.setattr(
        policy,
        "_sync_close_comment",
        lambda *args: pytest.fail("approved PR must not receive a close comment"),
    )
    monkeypatch.setattr(policy, "_gh", lambda *args: pytest.fail("approved PR must not be closed"))
    event = {
        "pull_request": {
            "number": 9,
            "body": "Refs #12",
            "user": {"login": "contributor"},
        }
    }

    assert policy.enforce(event, "owner/repo")["allowed"] is True


def test_issue_lookup_treats_missing_as_unapproved(monkeypatch):
    monkeypatch.setattr(
        policy.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(
            returncode=1,
            stdout="",
            stderr="gh: Not Found (HTTP 404)",
        ),
    )
    assert policy._issue("owner/repo", 404) == {}


def test_issue_lookup_surfaces_api_failures(monkeypatch):
    monkeypatch.setattr(
        policy.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(
            returncode=1,
            stdout="",
            stderr="gh: service unavailable (HTTP 503)",
        ),
    )
    with pytest.raises(policy.PolicyError, match="503"):
        policy._issue("owner/repo", 12)


def test_github_timeout_is_a_safe_policy_error(monkeypatch):
    def timeout(*args, **kwargs):
        raise policy.subprocess.TimeoutExpired(cmd=["gh"], timeout=60)

    monkeypatch.setattr(policy.subprocess, "run", timeout)
    with pytest.raises(policy.PolicyError, match="could not complete"):
        policy._gh("api", "repos/owner/repo")


def test_close_comment_does_not_trust_a_contributor_marker(monkeypatch):
    calls = []
    monkeypatch.setattr(
        policy,
        "_gh_json",
        lambda *args: [
            {"id": 1, "user": {"login": "contributor"}, "body": policy.COMMENT_MARKER}
        ],
    )
    monkeypatch.setattr(policy, "_gh", lambda *args: calls.append(args) or "")
    policy._sync_close_comment("owner/repo", 9, "policy message")
    assert calls == [
        (
            "api",
            "--method",
            "POST",
            "repos/owner/repo/issues/9/comments",
            "-f",
            "body=policy message",
        )
    ]


def test_workflow_uses_only_the_trusted_base_policy():
    workflow = (
        Path(__file__).resolve().parents[1]
        / ".github"
        / "workflows"
        / "benchmark-change-policy.yml"
    ).read_text(encoding="utf-8")
    assert "pull_request_target:" in workflow
    assert "github.event.pull_request.base.sha" in workflow
    assert "github.event.pull_request.head" not in workflow
    assert "persist-credentials: false" in workflow
    assert "branches: [test, main]" in workflow
    assert '"benchmark/**"' in workflow
    assert '"scripts/**"' in workflow
    assert '"docs/**"' in workflow
    assert '"blog/**"' in workflow
    assert '"**/*.md"' in workflow
    for path in policy.GUARDRAIL_FILES:
        assert f'"{path}"' in workflow


def test_main_fails_closed_without_event_context(monkeypatch, capsys):
    monkeypatch.delenv("GITHUB_EVENT_PATH", raising=False)
    monkeypatch.delenv("GITHUB_REPOSITORY", raising=False)
    assert policy.main() == 2
    assert "missing GitHub event context" in capsys.readouterr().err


def test_main_reads_event_and_calls_enforce(monkeypatch, tmp_path):
    event_path = tmp_path / "event.json"
    event_path.write_text(json.dumps({"pull_request": {"number": 1}}), encoding="utf-8")
    monkeypatch.setenv("GITHUB_EVENT_PATH", str(event_path))
    monkeypatch.setenv("GITHUB_REPOSITORY", "owner/repo")
    seen = []
    monkeypatch.setattr(policy, "enforce", lambda event, repo: seen.append((event, repo)) or {})
    assert policy.main() == 0
    assert seen == [({"pull_request": {"number": 1}}, "owner/repo")]
