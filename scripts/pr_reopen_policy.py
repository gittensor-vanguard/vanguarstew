#!/usr/bin/env python3
"""Re-close pull requests reopened without maintainer authority."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

MAINTAINERS = frozenset({"matedev01", "vanguarstew"})
COMMENT_MARKER = "<!-- vanguarstew:pr-reopen-policy -->"
COMMENT_BODY = (
    "This pull request was re-closed automatically because contributors may not reopen a "
    "pull request after it has been closed by a maintainer or repository automation. If you "
    "believe the closure reason has been resolved, ask a maintainer to reopen it. Please do "
    "not reopen it yourself.\n\n"
    f"{COMMENT_MARKER}"
)


class PolicyError(RuntimeError):
    """The event or GitHub response could not be evaluated safely."""


def evaluate_policy(*, action, actor) -> dict:
    """Return a deterministic allow/close decision for a PR activity event."""
    if action != "reopened":
        raise PolicyError("unsupported pull request action")
    if not isinstance(actor, str) or not actor.strip():
        raise PolicyError("GitHub actor is malformed")
    if actor.casefold() in {login.casefold() for login in MAINTAINERS}:
        return {"allowed": True, "reason": "authorized maintainer reopen"}
    return {"allowed": False, "reason": "contributor reopen is not authorized"}


def event_pr_number(event) -> int:
    """Extract and validate the pull request number from a reopened event."""
    if not isinstance(event, dict) or event.get("action") != "reopened":
        raise PolicyError("reopened pull request event is required")
    pr = event.get("pull_request")
    number = pr.get("number") if isinstance(pr, dict) else None
    if isinstance(number, bool) or not isinstance(number, int) or number <= 0:
        raise PolicyError("pull request number is malformed")
    return number


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


def _pull_state(repo: str, number: int) -> str:
    value = _gh_json("api", f"repos/{repo}/pulls/{number}")
    state = value.get("state") if isinstance(value, dict) else None
    if state not in {"open", "closed"}:
        raise PolicyError("pull request state is malformed")
    return state


def _comments(repo: str, number: int) -> list[dict]:
    raw = _gh(
        "api",
        "--paginate",
        f"repos/{repo}/issues/{number}/comments?per_page=100",
        "--jq",
        ".[] | @json",
    )
    comments = []
    for line in raw.splitlines():
        try:
            comment = json.loads(line)
        except ValueError as exc:
            raise PolicyError("GitHub comments response is malformed") from exc
        if not isinstance(comment, dict):
            raise PolicyError("GitHub comments response is malformed")
        comments.append(comment)
    return comments


def _ensure_comment(repo: str, number: int) -> bool:
    """Create the policy comment once; return whether a new comment was posted."""
    for comment in _comments(repo, number):
        user = comment.get("user")
        login = user.get("login") if isinstance(user, dict) else None
        body = comment.get("body")
        if login == "github-actions[bot]" and isinstance(body, str) and COMMENT_MARKER in body:
            return False
    _gh(
        "api",
        "--method",
        "POST",
        f"repos/{repo}/issues/{number}/comments",
        "-f",
        f"body={COMMENT_BODY}",
    )
    return True


def enforce(event, actor: str, repo: str) -> dict:
    """Apply the reopen policy to one pull_request_target event."""
    number = event_pr_number(event)
    decision = evaluate_policy(action=event.get("action"), actor=actor)
    if decision["allowed"]:
        print(f"PR reopen policy: allowed PR #{number} ({decision['reason']})")
        return decision

    # Re-close first so a comment API failure cannot leave the PR open. The workflow never
    # checks out contributor code, and per-PR concurrency cancels an older run when a newer
    # maintainer reopen event arrives.
    if _pull_state(repo, number) == "open":
        _gh(
            "api",
            "--method",
            "PATCH",
            f"repos/{repo}/pulls/{number}",
            "-f",
            "state=closed",
        )
    posted = _ensure_comment(repo, number)
    print(
        f"PR reopen policy: re-closed PR #{number}; "
        f"policy comment {'posted' if posted else 'already present'}"
    )
    return decision


def main() -> int:
    event_path = os.environ.get("GITHUB_EVENT_PATH")
    repo = os.environ.get("GITHUB_REPOSITORY")
    actor = os.environ.get("GITHUB_ACTOR")
    if not event_path or not repo or "/" not in repo or not actor:
        print("PR reopen policy: missing GitHub event context", file=sys.stderr)
        return 2
    try:
        event = json.loads(Path(event_path).read_text(encoding="utf-8"))
        enforce(event, actor, repo)
    except (OSError, ValueError, PolicyError) as exc:
        print(f"PR reopen policy failed safely: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
