import json
from pathlib import Path

import pytest

from scripts import pr_gaming_policy as policy


def _commit(
    sha,
    *,
    git_author,
    github_author,
    git_committer=None,
    github_committer=None,
):
    git_committer = git_committer or git_author
    return {
        "sha": sha,
        "commit": {
            "author": {"name": git_author, "email": "author@example.com"},
            "committer": {"name": git_committer, "email": "committer@example.com"},
        },
        "author": {"login": github_author} if github_author else None,
        "committer": {"login": github_committer} if github_committer else None,
    }


def test_exact_deceptive_identity_pattern_is_denied():
    commits = [
        _commit(
            "1e08d0838de4487d1a70cf333d5043c8381a863b",
            git_author="RealDiligent",
            github_author="RealDiligent",
            git_committer="RealDiligent",
            github_committer="jak-glitch",
        ),
        _commit(
            "59bce6438fde1f56a47510e0c6c77a348ded942f",
            git_author="RealDiligent",
            github_author="jak-glitch",
            git_committer="RealDiligent",
            github_committer="jak-glitch",
        ),
    ]

    decision = policy.evaluate_policy(pr_author="RealDiligent", commits=commits)

    assert decision == {
        "allowed": False,
        "reason": "commit identity claim conflicts with GitHub attribution",
        "identity_mismatches": [
            {
                "sha": "1e08d0838de4487d1a70cf333d5043c8381a863b",
                "role": "committer",
                "claimed": "RealDiligent",
                "resolved": "jak-glitch",
            },
            {
                "sha": "59bce6438fde1f56a47510e0c6c77a348ded942f",
                "role": "author",
                "claimed": "RealDiligent",
                "resolved": "jak-glitch",
            },
            {
                "sha": "59bce6438fde1f56a47510e0c6c77a348ded942f",
                "role": "committer",
                "claimed": "RealDiligent",
                "resolved": "jak-glitch",
            },
        ],
    }


def test_consistent_github_identity_is_allowed():
    commit = _commit(
        "a" * 40,
        git_author="Contributor-One",
        github_author="contributor-one",
        git_committer="contributor_one",
        github_committer="Contributor-One",
    )
    assert policy.evaluate_policy(pr_author="contributor-one", commits=[commit]) == {
        "allowed": True,
        "reason": "commit identity is consistent",
    }


def test_legitimate_different_author_is_not_treated_as_impersonation():
    commit = _commit(
        "a" * 40,
        git_author="Collaborator",
        github_author="collaborator-account",
        git_committer="GitHub",
        github_committer="web-flow",
    )
    assert policy.evaluate_policy(pr_author="pr-owner", commits=[commit])["allowed"] is True


def test_unlinked_email_does_not_prove_a_different_account():
    commit = _commit(
        "a" * 40,
        git_author="pr-owner",
        github_author=None,
        git_committer="pr-owner",
        github_committer=None,
    )
    assert policy.evaluate_policy(pr_author="pr-owner", commits=[commit])["allowed"] is True


def test_display_name_that_does_not_claim_pr_login_is_allowed():
    commit = _commit(
        "a" * 40,
        git_author="Clayton",
        github_author="claytonlin1110",
        git_committer="Clayton",
        github_committer="claytonlin1110",
    )
    assert policy.evaluate_policy(pr_author="claytonlin1110", commits=[commit])["allowed"] is True


def test_maintainers_are_exempt():
    assert policy.evaluate_policy(pr_author="matedev01", commits=[]) == {
        "allowed": True,
        "reason": "maintainer-authored PR",
    }


@pytest.mark.parametrize("role", ["author", "committer"])
def test_malformed_commit_roles_fail_safely(role):
    commit = _commit(
        "a" * 40,
        git_author="owner",
        github_author="owner",
        github_committer="owner",
    )
    commit["commit"][role] = None
    with pytest.raises(policy.PolicyError, match=role):
        policy.evaluate_policy(pr_author="owner", commits=[commit])


def test_event_pr_numbers_supports_pr_and_every_ci_completion():
    assert policy.event_pr_numbers({"pull_request": {"number": 9}}) == (9,)
    event = {"workflow_run": {"pull_requests": [{"number": 9}, {"number": 10}]}}
    assert policy.event_pr_numbers(event) == (9, 10)
    assert policy.event_pr_numbers({"workflow_run": {"pull_requests": []}}) == ()


def test_associated_pr_numbers_resolves_empty_fork_ci_metadata(monkeypatch):
    event = {
        "workflow_run": {
            "event": "pull_request",
            "pull_requests": [],
            "head_branch": "fix/identity",
            "head_repository": {"full_name": "contributor/vanguarstew"},
        }
    }
    monkeypatch.setattr(
        policy,
        "_gh_json",
        lambda *args: [
            {"number": 9, "base": {"ref": "test"}},
            {"number": 10, "base": {"ref": "other"}},
        ],
    )
    assert policy.associated_pr_numbers(event, "owner/repo") == (9,)


def test_associated_pr_numbers_does_not_query_for_push_ci(monkeypatch):
    event = {"workflow_run": {"event": "push", "pull_requests": []}}
    monkeypatch.setattr(policy, "_gh_json", lambda *args: pytest.fail("no lookup expected"))
    assert policy.associated_pr_numbers(event, "owner/repo") == ()


@pytest.mark.parametrize(
    "event",
    [None, {}, {"pull_request": {"number": True}}, {"workflow_run": {"pull_requests": [None]}}],
)
def test_event_pr_numbers_rejects_malformed_events(event):
    with pytest.raises(policy.PolicyError):
        policy.event_pr_numbers(event)


def test_enforce_closes_identity_mismatch(monkeypatch):
    calls = []
    comments = []
    monkeypatch.setattr(
        policy,
        "_pull",
        lambda repo, number: {"state": "open", "user": {"login": "RealDiligent"}},
    )
    monkeypatch.setattr(
        policy,
        "_paginate",
        lambda repo, number, resource: [
            _commit(
                "1e08d0838de4487d1a70cf333d5043c8381a863b",
                git_author="RealDiligent",
                github_author="RealDiligent",
                git_committer="RealDiligent",
                github_committer="jak-glitch",
            )
        ],
    )
    monkeypatch.setattr(
        policy,
        "_sync_close_comment",
        lambda repo, number, body: comments.append((repo, number, body)),
    )
    monkeypatch.setattr(policy, "_gh", lambda *args: calls.append(args) or "")

    decision = policy.enforce("owner/repo", 9)

    assert decision["allowed"] is False
    assert "@jak-glitch" in comments[0][2]
    assert "Git committer" in comments[0][2]
    assert "ask a maintainer to reopen" in comments[0][2]
    assert policy.COMMENT_MARKER in comments[0][2]
    assert calls == [
        ("api", "--method", "PATCH", "repos/owner/repo/pulls/9", "-f", "state=closed")
    ]


def test_enforce_records_mismatch_if_another_policy_closed_first(monkeypatch):
    comments = []
    monkeypatch.setattr(
        policy,
        "_pull",
        lambda repo, number: {"state": "closed", "user": {"login": "RealDiligent"}},
    )
    monkeypatch.setattr(
        policy,
        "_paginate",
        lambda repo, number, resource: [
            _commit(
                "1e08d0838de4487d1a70cf333d5043c8381a863b",
                git_author="RealDiligent",
                github_author="RealDiligent",
                git_committer="RealDiligent",
                github_committer="jak-glitch",
            )
        ],
    )
    monkeypatch.setattr(
        policy,
        "_sync_close_comment",
        lambda repo, number, body: comments.append((repo, number, body)),
    )
    monkeypatch.setattr(policy, "_gh", lambda *args: pytest.fail("must not close twice"))

    assert policy.enforce("owner/repo", 9)["allowed"] is False
    assert "@jak-glitch" in comments[0][2]


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
    assert calls[0][1:3] == ("--method", "POST")


def test_github_timeout_is_a_safe_policy_error(monkeypatch):
    def timeout(*args, **kwargs):
        raise policy.subprocess.TimeoutExpired(cmd=["gh"], timeout=60)

    monkeypatch.setattr(policy.subprocess, "run", timeout)
    with pytest.raises(policy.PolicyError, match="could not complete"):
        policy._gh("api", "repos/owner/repo")


def test_paginate_flattens_cli_json_lines(monkeypatch):
    monkeypatch.setattr(policy, "_gh", lambda *args: '{"sha":"a"}\n{"sha":"b"}')
    assert policy._paginate("owner/repo", 9, "commits") == [{"sha": "a"}, {"sha": "b"}]


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
    assert "github.event.pull_request.base.ref" in workflow
    assert "github.event.pull_request.base.sha" not in workflow
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
