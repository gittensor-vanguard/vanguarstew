import json
from pathlib import Path

import pytest

from scripts import pr_reopen_policy as policy


@pytest.mark.parametrize("actor", ["matedev01", "vanguarstew", "MateDev01"])
def test_maintainer_reopen_is_allowed(actor):
    assert policy.evaluate_policy(action="reopened", actor=actor) == {
        "allowed": True,
        "reason": "authorized maintainer reopen",
    }


@pytest.mark.parametrize("actor", ["contributor", "github-actions[bot]"])
def test_non_maintainer_reopen_is_denied(actor):
    assert policy.evaluate_policy(action="reopened", actor=actor) == {
        "allowed": False,
        "reason": "contributor reopen is not authorized",
    }


@pytest.mark.parametrize(
    ("action", "actor"),
    [("opened", "contributor"), (None, "contributor"), ("reopened", ""), ("reopened", None)],
)
def test_malformed_policy_inputs_fail_safely(action, actor):
    with pytest.raises(policy.PolicyError):
        policy.evaluate_policy(action=action, actor=actor)


@pytest.mark.parametrize(
    "event",
    [
        None,
        {},
        {"action": "opened"},
        {"action": "reopened", "pull_request": None},
        {"action": "reopened", "pull_request": {"number": True}},
    ],
)
def test_event_pr_number_requires_valid_reopened_event(event):
    with pytest.raises(policy.PolicyError):
        policy.event_pr_number(event)


def test_enforce_recloses_contributor_reopen_before_commenting(monkeypatch):
    calls = []
    monkeypatch.setattr(policy, "_pull_state", lambda repo, number: "open")
    monkeypatch.setattr(policy, "_gh", lambda *args: calls.append(args) or "")
    monkeypatch.setattr(
        policy,
        "_ensure_comment",
        lambda repo, number: calls.append(("comment",)) or True,
    )

    decision = policy.enforce(
        {"action": "reopened", "pull_request": {"number": 42}},
        "contributor",
        "owner/repo",
    )

    assert decision["allowed"] is False
    assert calls == [
        ("api", "--method", "PATCH", "repos/owner/repo/pulls/42", "-f", "state=closed"),
        ("comment",),
    ]


def test_enforce_authorized_reopen_has_no_github_mutation(monkeypatch):
    monkeypatch.setattr(policy, "_pull_state", lambda *args: pytest.fail("no lookup expected"))
    monkeypatch.setattr(policy, "_gh", lambda *args: pytest.fail("no mutation expected"))
    monkeypatch.setattr(policy, "_ensure_comment", lambda *args: pytest.fail("no comment expected"))

    decision = policy.enforce(
        {"action": "reopened", "pull_request": {"number": 42}},
        "matedev01",
        "owner/repo",
    )
    assert decision["allowed"] is True


def test_enforce_does_not_close_twice_when_another_policy_won_race(monkeypatch):
    monkeypatch.setattr(policy, "_pull_state", lambda repo, number: "closed")
    monkeypatch.setattr(policy, "_gh", lambda *args: pytest.fail("must not close twice"))
    comments = []
    monkeypatch.setattr(
        policy,
        "_ensure_comment",
        lambda repo, number: comments.append((repo, number)) or False,
    )

    assert policy.enforce(
        {"action": "reopened", "pull_request": {"number": 42}},
        "contributor",
        "owner/repo",
    )["allowed"] is False
    assert comments == [("owner/repo", 42)]


def test_policy_comment_is_idempotent_and_ignores_contributor_marker(monkeypatch):
    calls = []
    monkeypatch.setattr(
        policy,
        "_comments",
        lambda repo, number: [
            {"user": {"login": "contributor"}, "body": policy.COMMENT_MARKER},
            {"user": {"login": "github-actions[bot]"}, "body": policy.COMMENT_BODY},
        ],
    )
    monkeypatch.setattr(policy, "_gh", lambda *args: calls.append(args) or "")
    assert policy._ensure_comment("owner/repo", 42) is False
    assert calls == []


def test_policy_posts_when_only_contributor_marker_exists(monkeypatch):
    calls = []
    monkeypatch.setattr(
        policy,
        "_comments",
        lambda repo, number: [
            {"user": {"login": "contributor"}, "body": policy.COMMENT_MARKER}
        ],
    )
    monkeypatch.setattr(policy, "_gh", lambda *args: calls.append(args) or "")
    assert policy._ensure_comment("owner/repo", 42) is True
    assert calls[0][:3] == ("api", "--method", "POST")
    assert policy.COMMENT_MARKER in calls[0][-1]


def test_comments_pagination_parses_every_page(monkeypatch):
    monkeypatch.setattr(policy, "_gh", lambda *args: '{"id":1}\n{"id":2}')
    assert policy._comments("owner/repo", 42) == [{"id": 1}, {"id": 2}]


def test_workflow_uses_trusted_base_code_and_minimal_event_scope():
    workflow = (
        Path(__file__).resolve().parents[1]
        / ".github"
        / "workflows"
        / "pr-reopen-policy.yml"
    ).read_text(encoding="utf-8")
    assert "pull_request_target:" in workflow
    assert "types: [reopened]" in workflow
    assert "branches: [test, main]" in workflow
    assert "github.event.pull_request.base.sha" in workflow
    assert "github.event.pull_request.head" not in workflow
    assert "persist-credentials: false" in workflow
    assert "pull-requests: write" in workflow
    assert "issues: write" in workflow
    assert "cancel-in-progress: true" in workflow


def test_target_redirect_does_not_tell_contributor_to_reopen():
    workflow = (
        Path(__file__).resolve().parents[1]
        / ".github"
        / "workflows"
        / "pr-target-check.yml"
    ).read_text(encoding="utf-8")
    assert "open a new PR against \\`test\\`" in workflow
    assert "and reopen" not in workflow


def test_main_fails_closed_without_event_context(monkeypatch, capsys):
    monkeypatch.delenv("GITHUB_EVENT_PATH", raising=False)
    monkeypatch.delenv("GITHUB_REPOSITORY", raising=False)
    monkeypatch.delenv("GITHUB_ACTOR", raising=False)
    assert policy.main() == 2
    assert "missing GitHub event context" in capsys.readouterr().err


def test_main_reads_event_and_enforces(monkeypatch, tmp_path):
    event = {"action": "reopened", "pull_request": {"number": 42}}
    event_path = tmp_path / "event.json"
    event_path.write_text(json.dumps(event), encoding="utf-8")
    monkeypatch.setenv("GITHUB_EVENT_PATH", str(event_path))
    monkeypatch.setenv("GITHUB_REPOSITORY", "owner/repo")
    monkeypatch.setenv("GITHUB_ACTOR", "contributor")
    seen = []
    monkeypatch.setattr(
        policy,
        "enforce",
        lambda got_event, actor, repo: seen.append((got_event, actor, repo)) or {},
    )
    assert policy.main() == 0
    assert seen == [(event, "contributor", "owner/repo")]
