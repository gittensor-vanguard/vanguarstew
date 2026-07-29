#!/usr/bin/env python3
"""Close contributor PRs with deceptive commit identity metadata."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

MAINTAINERS = frozenset({"matedev01", "vanguarstew"})
COMMENT_MARKER = "<!-- vanguarstew:pr-gaming-policy -->"


class PolicyError(RuntimeError):
    """The event or GitHub response could not be evaluated safely."""


def _normalized_account(value) -> str:
    """Normalize a public account claim for a conservative comparison."""
    if not isinstance(value, str):
        return ""
    return re.sub(r"[^a-z0-9]", "", value.casefold())


def _commit_record(commit) -> tuple[str, dict]:
    if not isinstance(commit, dict):
        raise PolicyError("GitHub commit metadata is malformed")
    sha = commit.get("sha")
    raw_commit = commit.get("commit")
    if not isinstance(sha, str) or not sha or not isinstance(raw_commit, dict):
        raise PolicyError("GitHub commit metadata is incomplete")
    return sha, raw_commit


def _role_identity(commit: dict, raw_commit: dict, role: str) -> tuple[str, str | None]:
    raw_role = raw_commit.get(role)
    if not isinstance(raw_role, dict):
        raise PolicyError(f"Git {role} metadata is incomplete")
    claimed_name = raw_role.get("name")
    if not isinstance(claimed_name, str) or not claimed_name.strip():
        raise PolicyError(f"Git {role} name is incomplete")

    github_role = commit.get(role)
    if github_role is None:
        return claimed_name, None
    if not isinstance(github_role, dict):
        raise PolicyError(f"GitHub {role} metadata is malformed")
    resolved_login = github_role.get("login")
    if not isinstance(resolved_login, str) or not resolved_login:
        raise PolicyError(f"GitHub {role} login is incomplete")
    return claimed_name, resolved_login


def evaluate_policy(*, pr_author, commits) -> dict:
    """Return a deterministic allow/close decision from public commit attribution."""
    if pr_author in MAINTAINERS:
        return {"allowed": True, "reason": "maintainer-authored PR"}
    if not isinstance(pr_author, str) or not pr_author:
        raise PolicyError("pull request author is malformed")
    if not isinstance(commits, list):
        raise PolicyError("pull request commit metadata is malformed")

    claimed_account = _normalized_account(pr_author)
    if not claimed_account:
        raise PolicyError("pull request author cannot be compared safely")

    mismatches = []
    for commit in commits:
        sha, raw_commit = _commit_record(commit)
        for role in ("author", "committer"):
            claimed_name, resolved_login = _role_identity(commit, raw_commit, role)
            if resolved_login is None:
                # An unlinked email does not prove that another GitHub account owns the commit.
                continue
            if (
                _normalized_account(claimed_name) == claimed_account
                and resolved_login.casefold() != pr_author.casefold()
            ):
                mismatches.append(
                    {
                        "sha": sha,
                        "role": role,
                        "claimed": claimed_name,
                        "resolved": resolved_login,
                    }
                )

    if mismatches:
        return {
            "allowed": False,
            "reason": "commit identity claim conflicts with GitHub attribution",
            "identity_mismatches": mismatches,
        }
    return {"allowed": True, "reason": "commit identity is consistent"}


def event_pr_numbers(event) -> tuple[int, ...]:
    """Extract associated PR numbers from pull_request_target or workflow_run events."""
    if not isinstance(event, dict):
        raise PolicyError("GitHub event is malformed")
    pr = event.get("pull_request")
    if isinstance(pr, dict):
        number = pr.get("number")
        if isinstance(number, bool) or not isinstance(number, int) or number <= 0:
            raise PolicyError("pull request number is malformed")
        return (number,)

    workflow_run = event.get("workflow_run")
    if not isinstance(workflow_run, dict):
        raise PolicyError("unsupported GitHub event")
    pulls = workflow_run.get("pull_requests")
    if not isinstance(pulls, list):
        raise PolicyError("workflow run pull request metadata is malformed")
    numbers = []
    for item in pulls:
        number = item.get("number") if isinstance(item, dict) else None
        if isinstance(number, bool) or not isinstance(number, int) or number <= 0:
            raise PolicyError("workflow run contains a malformed pull request")
        if number not in numbers:
            numbers.append(number)
    return tuple(numbers)


def associated_pr_numbers(event, repo: str) -> tuple[int, ...]:
    """Resolve PRs for an event, including fork CI runs with an empty PR array."""
    numbers = event_pr_numbers(event)
    if numbers:
        return numbers
    workflow_run = event.get("workflow_run")
    if workflow_run.get("event") != "pull_request":
        return ()
    head_repository = workflow_run.get("head_repository")
    head_owner = (head_repository or {}).get("owner", {}).get("login")
    if not isinstance(head_owner, str) or not head_owner:
        full_name = (head_repository or {}).get("full_name")
        if isinstance(full_name, str) and "/" in full_name:
            head_owner = full_name.split("/", 1)[0]
    head_branch = workflow_run.get("head_branch")
    if not isinstance(head_owner, str) or not head_owner or not isinstance(head_branch, str):
        raise PolicyError("workflow run cannot be associated with its fork branch")
    pulls = _gh_json(
        "api",
        "--method",
        "GET",
        f"repos/{repo}/pulls",
        "-f",
        "state=open",
        "-f",
        f"head={head_owner}:{head_branch}",
    )
    if not isinstance(pulls, list):
        raise PolicyError("GitHub head-branch PR lookup is malformed")
    resolved = []
    for pull in pulls:
        number = pull.get("number") if isinstance(pull, dict) else None
        base = (pull.get("base") or {}).get("ref") if isinstance(pull, dict) else None
        if (
            isinstance(number, int)
            and not isinstance(number, bool)
            and number > 0
            and base in {"test", "main"}
            and number not in resolved
        ):
            resolved.append(number)
    return tuple(resolved)


def _gh(*args) -> str:
    try:
        result = subprocess.run(
            ["gh", *args],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise PolicyError("GitHub API request could not complete") from exc
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "GitHub API request failed").strip()
        raise PolicyError(detail[:300])
    return result.stdout.strip()


def _gh_json(*args):
    raw = _gh(*args)
    try:
        return json.loads(raw or "null")
    except ValueError as exc:
        raise PolicyError("GitHub API returned malformed JSON") from exc


def _paginate(repo: str, number: int, resource: str):
    raw = _gh(
        "api",
        "--paginate",
        f"repos/{repo}/pulls/{number}/{resource}?per_page=100",
        "--jq",
        ".[] | @json",
    )
    values = []
    for line in raw.splitlines():
        try:
            item = json.loads(line)
        except ValueError as exc:
            raise PolicyError(f"GitHub PR {resource} response is malformed") from exc
        if not isinstance(item, dict):
            raise PolicyError(f"GitHub PR {resource} response is malformed")
        values.append(item)
    return values


def _pull(repo: str, number: int) -> dict:
    value = _gh_json("api", f"repos/{repo}/pulls/{number}")
    if not isinstance(value, dict):
        raise PolicyError("GitHub PR response is malformed")
    return value


def _sync_close_comment(repo: str, number: int, body: str) -> None:
    comments = _gh_json("api", f"repos/{repo}/issues/{number}/comments?per_page=100")
    if not isinstance(comments, list):
        raise PolicyError("GitHub comments response is malformed")
    for comment in comments:
        if not isinstance(comment, dict):
            continue
        login = (comment.get("user") or {}).get("login")
        if login == "github-actions[bot]" and COMMENT_MARKER in (comment.get("body") or ""):
            _gh(
                "api",
                "--method",
                "PATCH",
                f"repos/{repo}/issues/comments/{comment['id']}",
                "-f",
                f"body={body}",
            )
            return
    _gh(
        "api",
        "--method",
        "POST",
        f"repos/{repo}/issues/{number}/comments",
        "-f",
        f"body={body}",
    )


def _close_comment(decision: dict) -> str:
    details = []
    for item in decision.get("identity_mismatches", []):
        details.append(
            f"- commit `{item['sha'][:12]}` declares `{item['claimed']}` as its Git "
            f"{item['role']}, but GitHub attributes that role to `@{item['resolved']}`"
        )
    findings = "\n".join(details)
    return (
        "Closing automatically: this PR contains deceptive commit identity metadata. Git metadata "
        "claims the PR author's account name, while GitHub attributes the same commit role to a "
        "different account.\n\n"
        f"{findings}\n\n"
        "Use accurate Git author and committer identity before reopening. This policy is checked "
        "on PR updates and again after every CI run completes.\n\n"
        f"{COMMENT_MARKER}"
    )


def enforce(repo: str, number: int) -> dict:
    """Evaluate one pull request and close it when required."""
    pr = _pull(repo, number)
    state = pr.get("state")
    if state not in {"open", "closed"}:
        raise PolicyError("pull request state is malformed")
    was_open = state == "open"
    pr_author = (pr.get("user") or {}).get("login")
    commits = _paginate(repo, number, "commits")
    decision = evaluate_policy(pr_author=pr_author, commits=commits)
    if decision["allowed"]:
        print(f"PR gaming policy: allowed PR #{number} ({decision['reason']})")
        return decision

    _sync_close_comment(repo, number, _close_comment(decision))
    if was_open:
        _gh(
            "api",
            "--method",
            "PATCH",
            f"repos/{repo}/pulls/{number}",
            "-f",
            "state=closed",
        )
        print(f"PR gaming policy: closed PR #{number}")
    else:
        print(f"PR gaming policy: recorded identity mismatch on closed PR #{number}")
    return decision


def main() -> int:
    event_path = os.environ.get("GITHUB_EVENT_PATH")
    repo = os.environ.get("GITHUB_REPOSITORY")
    if not event_path or not repo or "/" not in repo:
        print("PR gaming policy: missing GitHub event context", file=sys.stderr)
        return 2
    try:
        event = json.loads(Path(event_path).read_text(encoding="utf-8"))
        for number in associated_pr_numbers(event, repo):
            enforce(repo, number)
    except (OSError, ValueError, PolicyError) as exc:
        print(f"PR gaming policy failed safely: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
