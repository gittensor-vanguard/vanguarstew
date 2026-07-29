import json
from pathlib import Path

import pytest

from scripts import pr_gaming_policy as policy


def _commit(sha, message):
    return {"sha": sha, "commit": {"message": message}}


def test_references_distinguish_pr_declarations_from_commit_claims():
    text = "Refs #7, fixes: #8, and closes #7. Bare #9 does not count."
    assert policy.pr_references(text) == (7, 8)
    assert policy.commit_claims(text) == (8, 7)
    assert policy.pr_references(None) == ()
    assert policy.commit_claims(None) == ()


def test_exact_hidden_scope_gaming_pattern_is_denied():
    decision = policy.evaluate_policy(
        author="contributor",
        body="Fixes #2065\n\nScripts-only; behavior is otherwise unchanged.",
        commits=[
            _commit("1e08d0838de4487d1a70cf333d5043c8381a863b", "fix(agent)\n\nFixes #1494"),
            _commit("59bce6438fde1f56a47510e0c6c77a348ded942f", "fix(scripts)\n\nFixes #2065"),
        ],
        paths=["agent/context.py", "scripts/verify_attestation.py", "tests/test_context.py"],
    )

    assert decision["allowed"] is False
    assert decision["declared_issues"] == [2065]
    assert decision["hidden_commit_issues"] == [
        {"sha": "1e08d0838de4487d1a70cf333d5043c8381a863b", "issues": [1494]}
    ]
    assert decision["scope_conflicts"] == [
        {"claim": "scripts", "unexpected": ["agent"]}
    ]


def test_declaring_every_commit_issue_allows_a_multi_commit_pr():
    decision = policy.evaluate_policy(
        author="contributor",
        body="Fixes #1494\nFixes #2065",
        commits=[
            _commit("a" * 40, "fix(agent): context\n\nFixes #1494"),
            _commit("b" * 40, "fix(scripts): verifier\n\nFixes #2065"),
        ],
        paths=["agent/context.py", "scripts/verify_attestation.py"],
    )
    assert decision == {"allowed": True, "reason": "commit scope is declared"}


def test_bare_commit_mentions_are_not_hidden_closing_claims():
    decision = policy.evaluate_policy(
        author="contributor",
        body="Fixes #12",
        commits=[_commit("a" * 40, "Fixes #12; mirrors the loader in #1563")],
        paths=["scripts/check.py"],
    )
    assert decision["allowed"] is True


@pytest.mark.parametrize(
    ("claim", "paths", "allowed"),
    [
        ("Scripts-only", ["scripts/check.py", "tests/test_check.py"], True),
        ("Scripts only", ["scripts/check.py", "agent/context.py"], False),
        ("Docs-only", ["README.md", "docs/architecture.md"], True),
        ("Documentation only", ["README.md", "benchmark/runner.py"], False),
        ("Benchmark-only", ["benchmark/runner.py", "scripts/run_eval.py"], True),
    ],
)
def test_only_surface_claims_match_source_paths(claim, paths, allowed):
    decision = policy.evaluate_policy(
        author="contributor",
        body=f"Fixes #12\n\n{claim}.",
        commits=[_commit("a" * 40, "Fixes #12")],
        paths=paths,
    )
    assert decision["allowed"] is allowed


def test_maintainers_are_exempt():
    assert policy.evaluate_policy(
        author="matedev01",
        body="",
        commits=[],
        paths=[],
    ) == {"allowed": True, "reason": "maintainer-authored PR"}


def test_event_pr_numbers_supports_pr_and_every_ci_completion():
    assert policy.event_pr_numbers({"pull_request": {"number": 9}}) == (9,)
    event = {"workflow_run": {"pull_requests": [{"number": 9}, {"number": 9}, {"number": 10}]}}
    assert policy.event_pr_numbers(event) == (9, 10)
    assert policy.event_pr_numbers({"workflow_run": {"pull_requests": []}}) == ()


def test_associated_pr_numbers_resolves_empty_fork_ci_metadata(monkeypatch):
    event = {
        "workflow_run": {
            "event": "pull_request",
            "pull_requests": [],
            "head_branch": "fix/hidden-scope",
            "head_repository": {"full_name": "contributor/vanguarstew"},
        }
    }
    seen = []

    def lookup(*args):
        seen.append(args)
        return [
            {"number": 9, "base": {"ref": "test"}},
            {"number": 10, "base": {"ref": "other"}},
        ]

    monkeypatch.setattr(policy, "_gh_json", lookup)
    assert policy.associated_pr_numbers(event, "owner/repo") == (9,)
    assert seen == [
        (
            "api",
            "--method",
            "GET",
            "repos/owner/repo/pulls",
            "-f",
            "state=open",
            "-f",
            "head=contributor:fix/hidden-scope",
        )
    ]


def test_associated_pr_numbers_does_not_query_for_push_ci(monkeypatch):
    event = {"workflow_run": {"event": "push", "pull_requests": []}}
    monkeypatch.setattr(policy, "_gh_json", lambda *args: pytest.fail("push run needs no lookup"))
    assert policy.associated_pr_numbers(event, "owner/repo") == ()


@pytest.mark.parametrize(
    "event",
    [None, {}, {"pull_request": {"number": True}}, {"workflow_run": {"pull_requests": [None]}}],
)
def test_event_pr_numbers_rejects_malformed_events(event):
    with pytest.raises(policy.PolicyError):
        policy.event_pr_numbers(event)


def test_enforce_closes_hidden_scope_pr(monkeypatch):
    calls = []
    comments = []
    monkeypatch.setattr(
        policy,
        "_pull",
        lambda repo, number: {
            "state": "open",
            "user": {"login": "contributor"},
            "body": "Fixes #2065\n\nScripts-only.",
        },
    )
    monkeypatch.setattr(
        policy,
        "_paginate",
        lambda repo, number, resource: (
            [_commit("1e08d0838de4487d1a70cf333d5043c8381a863b", "Fixes #1494")]
            if resource == "commits"
            else [{"filename": "agent/context.py"}]
        ),
    )
    monkeypatch.setattr(
        policy,
        "_sync_close_comment",
        lambda repo, number, body: comments.append((repo, number, body)),
    )
    monkeypatch.setattr(policy, "_gh", lambda *args: calls.append(args) or "")

    decision = policy.enforce("owner/repo", 9)

    assert decision["allowed"] is False
    assert len(comments) == 1
    assert "#1494" in comments[0][2]
    assert policy.COMMENT_MARKER in comments[0][2]
    assert calls == [
        ("api", "--method", "PATCH", "repos/owner/repo/pulls/9", "-f", "state=closed")
    ]


def test_enforce_does_not_mutate_allowed_or_closed_pr(monkeypatch):
    monkeypatch.setattr(
        policy,
        "_pull",
        lambda repo, number: {"state": "closed", "user": {"login": "contributor"}},
    )
    monkeypatch.setattr(policy, "_paginate", lambda *args: pytest.fail("closed PR needs no data"))
    monkeypatch.setattr(policy, "_gh", lambda *args: pytest.fail("closed PR must not mutate"))
    assert policy.enforce("owner/repo", 9)["allowed"] is True


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


def test_github_timeout_is_a_safe_policy_error(monkeypatch):
    def timeout(*args, **kwargs):
        raise policy.subprocess.TimeoutExpired(cmd=["gh"], timeout=60)

    monkeypatch.setattr(policy.subprocess, "run", timeout)
    with pytest.raises(policy.PolicyError, match="could not complete"):
        policy._gh("api", "repos/owner/repo")


def test_paginate_flattens_cli_json_lines(monkeypatch):
    seen = []

    def run(*args):
        seen.append(args)
        return '{"sha":"a"}\n{"sha":"b"}'

    monkeypatch.setattr(policy, "_gh", run)
    assert policy._paginate("owner/repo", 9, "commits") == [{"sha": "a"}, {"sha": "b"}]
    assert seen == [
        (
            "api",
            "--paginate",
            "repos/owner/repo/pulls/9/commits?per_page=100",
            "--jq",
            ".[] | @json",
        )
    ]


def test_workflow_rechecks_after_every_ci_run_using_trusted_code():
    workflow = (
        Path(__file__).resolve().parents[1]
        / ".github"
        / "workflows"
        / "pr-gaming-policy.yml"
    ).read_text(encoding="utf-8")
    assert "pull_request_target:" in workflow
    assert "workflow_run:" in workflow
    assert 'workflows: ["CI"]' in workflow
    assert "types: [completed]" in workflow
    assert "github.event.pull_request.base.sha" in workflow
    assert "github.event.repository.default_branch" in workflow
    assert "github.event.pull_request.head" not in workflow
    assert "persist-credentials: false" in workflow
    assert "pull-requests: write" in workflow


def test_main_fails_closed_without_event_context(monkeypatch, capsys):
    monkeypatch.delenv("GITHUB_EVENT_PATH", raising=False)
    monkeypatch.delenv("GITHUB_REPOSITORY", raising=False)
    assert policy.main() == 2
    assert "missing GitHub event context" in capsys.readouterr().err


def test_main_rechecks_all_event_prs(monkeypatch, tmp_path):
    event_path = tmp_path / "event.json"
    event_path.write_text(
        json.dumps({"workflow_run": {"pull_requests": [{"number": 7}, {"number": 8}]}}),
        encoding="utf-8",
    )
    monkeypatch.setenv("GITHUB_EVENT_PATH", str(event_path))
    monkeypatch.setenv("GITHUB_REPOSITORY", "owner/repo")
    seen = []
    monkeypatch.setattr(policy, "enforce", lambda repo, number: seen.append((repo, number)) or {})
    assert policy.main() == 0
    assert seen == [("owner/repo", 7), ("owner/repo", 8)]
