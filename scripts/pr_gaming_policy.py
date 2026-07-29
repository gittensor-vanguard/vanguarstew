#!/usr/bin/env python3
"""Close contributor PRs that hide commit scope from the PR declaration."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

MAINTAINERS = frozenset({"matedev01", "vanguarstew"})
COMMENT_MARKER = "<!-- vanguarstew:pr-gaming-policy -->"
_PR_REF_RE = re.compile(
    r"\b(?:fix(?:e[sd])?|close[sd]?|resolve[sd]?|refs?)\s*:?[ \t]*#([1-9][0-9]*)\b",
    re.IGNORECASE,
)
_COMMIT_CLAIM_RE = re.compile(
    r"\b(?:fix(?:e[sd])?|close[sd]?|resolve[sd]?)\s*:?[ \t]*#([1-9][0-9]*)\b",
    re.IGNORECASE,
)
_ONLY_SURFACE_RE = re.compile(
    r"\b(agent|benchmark|scripts?|docs?|documentation|tests?)[ -]only\b",
    re.IGNORECASE,
)


class PolicyError(RuntimeError):
    """The event or GitHub response could not be evaluated safely."""


def pr_references(body) -> tuple[int, ...]:
    """Return issue references explicitly declared in a PR body."""
    if not isinstance(body, str):
        return ()
    return tuple(dict.fromkeys(int(value) for value in _PR_REF_RE.findall(body)))


def commit_claims(message) -> tuple[int, ...]:
    """Return issues a commit explicitly claims to fix, close, or resolve."""
    if not isinstance(message, str):
        return ()
    return tuple(dict.fromkeys(int(value) for value in _COMMIT_CLAIM_RE.findall(message)))


def only_surface_claims(body) -> tuple[str, ...]:
    """Return normalized source surfaces that the PR explicitly calls exclusive."""
    if not isinstance(body, str):
        return ()
    aliases = {
        "script": "scripts",
        "scripts": "scripts",
        "doc": "docs",
        "docs": "docs",
        "documentation": "docs",
        "test": "tests",
        "tests": "tests",
    }
    claims = []
    for value in _ONLY_SURFACE_RE.findall(body):
        normalized = aliases.get(value.lower(), value.lower())
        if normalized not in claims:
            claims.append(normalized)
    return tuple(claims)


def source_surface(path) -> str | None:
    """Map a changed path onto a source surface relevant to an only-scope claim."""
    if not isinstance(path, str):
        return None
    normalized = path.strip()
    while normalized.startswith("./"):
        normalized = normalized[2:]
    if normalized == "agent.py" or normalized.startswith("agent/"):
        return "agent"
    if normalized.startswith("benchmark/"):
        return "benchmark"
    if normalized.startswith("scripts/"):
        return "scripts"
    return None


def _commit_record(commit) -> tuple[str, str]:
    if not isinstance(commit, dict):
        raise PolicyError("GitHub commit metadata is malformed")
    sha = commit.get("sha")
    message = (commit.get("commit") or {}).get("message")
    if not isinstance(sha, str) or not sha or not isinstance(message, str):
        raise PolicyError("GitHub commit metadata is incomplete")
    return sha, message


def evaluate_policy(*, author, body, commits, paths) -> dict:
    """Return a deterministic allow/close decision from fetched PR metadata."""
    if author in MAINTAINERS:
        return {"allowed": True, "reason": "maintainer-authored PR"}
    if not isinstance(author, str) or not author:
        raise PolicyError("pull request author is malformed")
    if not isinstance(commits, list) or not isinstance(paths, list):
        raise PolicyError("pull request commit or path metadata is malformed")

    declared = set(pr_references(body))
    hidden = []
    for commit in commits:
        sha, message = _commit_record(commit)
        missing = sorted(set(commit_claims(message)) - declared)
        if missing:
            hidden.append({"sha": sha, "issues": missing})

    source_surfaces = {surface for path in paths if (surface := source_surface(path))}
    scope_conflicts = []
    allowed_by_claim = {
        "agent": {"agent"},
        "benchmark": {"benchmark", "scripts"},
        "scripts": {"scripts"},
        "docs": set(),
        "tests": set(),
    }
    for claim in only_surface_claims(body):
        unexpected = sorted(source_surfaces - allowed_by_claim[claim])
        if unexpected:
            scope_conflicts.append({"claim": claim, "unexpected": unexpected})

    if hidden or scope_conflicts:
        return {
            "allowed": False,
            "reason": "PR declaration omits commit scope",
            "declared_issues": sorted(declared),
            "hidden_commit_issues": hidden,
            "scope_conflicts": scope_conflicts,
        }
    return {"allowed": True, "reason": "commit scope is declared"}


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
    for item in decision.get("hidden_commit_issues", []):
        issues = ", ".join(f"#{number}" for number in item["issues"])
        details.append(f"- commit `{item['sha'][:12]}` claims {issues}, absent from the PR body")
    for item in decision.get("scope_conflicts", []):
        surfaces = ", ".join(f"`{name}/`" for name in item["unexpected"])
        details.append(f"- `{item['claim']}-only` conflicts with changed source under {surfaces}")
    findings = "\n".join(details)
    return (
        "Closing automatically: this PR contains commit scope that its public declaration omits. "
        "Every issue a commit claims to fix, close, or resolve must also be referenced in the PR "
        "body, and an `*-only` scope claim must match the changed source surfaces.\n\n"
        f"{findings}\n\n"
        "Split unrelated work into focused PRs or correct the declaration before reopening. This "
        "policy is checked on PR updates and again after every CI run completes.\n\n"
        f"{COMMENT_MARKER}"
    )


def enforce(repo: str, number: int) -> dict:
    """Evaluate and, when required, close one open pull request."""
    pr = _pull(repo, number)
    if pr.get("state") != "open":
        return {"allowed": True, "reason": "PR is not open"}
    author = (pr.get("user") or {}).get("login")
    commits = _paginate(repo, number, "commits")
    files = _paginate(repo, number, "files")
    paths = [item.get("filename") for item in files if isinstance(item, dict)]
    if any(not isinstance(path, str) or not path for path in paths):
        raise PolicyError("GitHub PR file metadata is incomplete")
    decision = evaluate_policy(
        author=author,
        body=pr.get("body") or "",
        commits=commits,
        paths=paths,
    )
    if decision["allowed"]:
        print(f"PR gaming policy: allowed PR #{number} ({decision['reason']})")
        return decision

    _sync_close_comment(repo, number, _close_comment(decision))
    _gh(
        "api",
        "--method",
        "PATCH",
        f"repos/{repo}/pulls/{number}",
        "-f",
        "state=closed",
    )
    print(f"PR gaming policy: closed PR #{number}")
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
