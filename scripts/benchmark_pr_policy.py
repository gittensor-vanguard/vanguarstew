#!/usr/bin/env python3
"""Close unapproved contributor PRs outside the agent submission surface."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

APPROVAL_LABEL = "benchmark-change-approved"
MAINTAINERS = frozenset({"matedev01", "vanguarstew"})
COMMENT_MARKER = "<!-- vanguarstew:benchmark-change-policy -->"
_ISSUE_REF_RE = re.compile(
    r"\b(?:fixes|closes|resolves|refs)\s*:?[ \t]*#([1-9][0-9]*)\b",
    re.IGNORECASE,
)


class PolicyError(RuntimeError):
    """The event or GitHub response could not be evaluated safely."""


def _normalized_paths(paths) -> tuple[str, ...] | None:
    """Return safe repository-relative paths, or ``None`` for malformed input."""
    if not isinstance(paths, (list, tuple, set, frozenset)):
        return None
    normalized_paths = []
    for path in paths:
        if not isinstance(path, str):
            return None
        if path != path.strip() or any(ord(character) < 32 or ord(character) == 127 for character in path):
            return None
        normalized = path
        while normalized.startswith("./"):
            normalized = normalized[2:]
        parts = normalized.split("/")
        if (
            not normalized
            or normalized.startswith("/")
            or any(part in {"", ".", ".."} for part in parts)
        ):
            return None
        normalized_paths.append(normalized)
    return tuple(normalized_paths)


def is_agent_submission(paths) -> bool:
    """Whether every change is agent code or a companion test for that agent code."""
    normalized = _normalized_paths(paths)
    if not normalized:
        return False
    has_agent_change = any(path == "agent.py" or path.startswith("agent/") for path in normalized)
    allowed = all(
        path == "agent.py" or path.startswith(("agent/", "tests/"))
        for path in normalized
    )
    return has_agent_change and allowed


def touches_guardrail(paths) -> bool:
    """Whether a change falls outside the narrowly defined agent submission surface."""
    return not is_agent_submission(paths)


def referenced_issues(body) -> tuple[int, ...]:
    """Return unique same-repository issue references using an explicit linking verb."""
    if not isinstance(body, str):
        return ()
    return tuple(dict.fromkeys(int(value) for value in _ISSUE_REF_RE.findall(body)))


def issue_is_approved(issue) -> bool:
    """An approval is an open issue (not a PR) carrying the exact approval label."""
    if not isinstance(issue, dict) or issue.get("state") != "open" or "pull_request" in issue:
        return False
    labels = issue.get("labels")
    if not isinstance(labels, list):
        return False
    names = {
        item.get("name")
        for item in labels
        if isinstance(item, dict) and isinstance(item.get("name"), str)
    }
    return APPROVAL_LABEL in names


def evaluate_policy(*, author, paths, body, issues) -> dict:
    """Return a deterministic allow/close decision from already-fetched metadata."""
    if not touches_guardrail(paths):
        return {"allowed": True, "reason": "eligible agent submission"}
    if author in MAINTAINERS:
        return {"allowed": True, "reason": "maintainer-authored protected change"}
    refs = referenced_issues(body)
    for number in refs:
        if issue_is_approved(issues.get(number) if isinstance(issues, dict) else None):
            return {
                "allowed": True,
                "reason": f"approved by open issue #{number}",
                "issue": number,
            }
    return {
        "allowed": False,
        "reason": "protected change lacks an approved open issue",
        "referenced_issues": list(refs),
    }


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


def _changed_files(repo: str, number: int) -> list[str]:
    raw = _gh(
        "api",
        "--paginate",
        f"repos/{repo}/pulls/{number}/files",
        "--jq",
        ".[].filename",
    )
    return [line for line in raw.splitlines() if line]


def _issue(repo: str, number: int) -> dict:
    try:
        result = subprocess.run(
            ["gh", "api", f"repos/{repo}/issues/{number}"],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise PolicyError("GitHub issue lookup could not complete") from exc
    if result.returncode != 0:
        if "HTTP 404" in (result.stderr or ""):
            return {}
        detail = (result.stderr or result.stdout or "GitHub issue lookup failed").strip()
        raise PolicyError(detail[:300])
    try:
        value = json.loads(result.stdout)
    except ValueError as exc:
        raise PolicyError("GitHub issue lookup returned malformed JSON") from exc
    if not isinstance(value, dict):
        raise PolicyError("GitHub issue lookup returned a non-object")
    return value


def _issues(repo: str, numbers: tuple[int, ...]) -> dict[int, dict]:
    return {number: _issue(repo, number) for number in numbers}


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


def enforce(event: dict, repo: str) -> dict:
    """Evaluate one pull_request_target event and close it when policy requires."""
    pr = event.get("pull_request") if isinstance(event, dict) else None
    if not isinstance(pr, dict):
        raise PolicyError("pull request event is missing")
    number = pr.get("number")
    author = (pr.get("user") or {}).get("login")
    if isinstance(number, bool) or not isinstance(number, int) or number <= 0:
        raise PolicyError("pull request number is malformed")
    if not isinstance(author, str) or not author:
        raise PolicyError("pull request author is malformed")

    paths = _changed_files(repo, number)
    refs = referenced_issues(pr.get("body") or "")
    issues = _issues(repo, refs) if touches_guardrail(paths) and author not in MAINTAINERS else {}
    decision = evaluate_policy(
        author=author,
        paths=paths,
        body=pr.get("body") or "",
        issues=issues,
    )
    if decision["allowed"]:
        print(f"protected change policy: allowed ({decision['reason']})")
        return decision

    comment = (
        "Closing automatically: this PR changes files outside the agent submission surface. "
        "Agent submissions are limited to `agent/**` or `agent.py`, with companion `tests/**` "
        "changes allowed in the same PR. Every other project path, including `.github/**`, is "
        "maintainer-directed. Please open an issue first, agree the scope with a maintainer, "
        f"and wait for the `{APPROVAL_LABEL}` label before submitting a PR. Then reference that "
        "open issue with `Refs #<number>` and ask a maintainer to reopen this PR.\n\n"
        f"{COMMENT_MARKER}"
    )
    _sync_close_comment(repo, number, comment)
    _gh(
        "api",
        "--method",
        "PATCH",
        f"repos/{repo}/pulls/{number}",
        "-f",
        "state=closed",
    )
    print(f"protected change policy: closed PR #{number}")
    return decision


def main() -> int:
    event_path = os.environ.get("GITHUB_EVENT_PATH")
    repo = os.environ.get("GITHUB_REPOSITORY")
    if not event_path or not repo or "/" not in repo:
        print("protected change policy: missing GitHub event context", file=sys.stderr)
        return 2
    try:
        event = json.loads(Path(event_path).read_text(encoding="utf-8"))
        enforce(event, repo)
    except (OSError, ValueError, PolicyError) as exc:
        print(f"protected change policy failed safely: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
