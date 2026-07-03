"""Enrich a frozen snapshot with GitHub state that was knowable at time T.

`freeze.py` gives us git-only context (commits, tags, README). This adds the maintainer's
real working surface — open issues, open PRs, labels, milestones, releases — reconstructed
*as of T* so nothing from the future leaks: an item counts as "open at T" only if it was
created on or before T and was not already closed by T.

Network access is optional. Any failure (offline, rate limit, private repo) is caught and
the git-only context is returned unchanged, so the benchmark still runs without GitHub.
"""

from __future__ import annotations

import json
import os
import urllib.request
from datetime import datetime

API = "https://api.github.com"
DEFAULT_MAX_ISSUE_PAGES = 10  # bound on pages walked back toward T (100 items/page)


def parse_owner_repo(remote_url: str):
    """Extract (owner, repo) from an ssh or https GitHub remote URL."""
    s = (remote_url or "").strip()
    if s.endswith(".git"):
        s = s[:-4]
    if s.startswith("git@"):
        path = s.split(":", 1)[-1]
    elif "github.com/" in s:
        path = s.split("github.com/", 1)[-1]
    else:
        path = s
    parts = [p for p in path.split("/") if p]
    if len(parts) >= 2:
        return parts[-2], parts[-1]
    return None, None


def _parse_dt(value):
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _milestone_at(milestone: dict, until: datetime):
    """A milestone as knowable at `until`, or None if it didn't exist yet.

    Returns None when the milestone was created after T. Otherwise `state` is derived from
    `closed_at` *as of T* — `"closed"` only when it was already closed by T — rather than the
    milestone's present-day state, so a milestone closed after T isn't leaked as completed.
    """
    created = _parse_dt(milestone.get("created_at"))
    if created is None or created > until:
        return None
    closed = _parse_dt(milestone.get("closed_at"))
    state = "closed" if closed is not None and closed <= until else "open"
    return {"title": milestone.get("title"), "due_on": milestone.get("due_on"), "state": state}


def _get(url: str, token, timeout: int = 20):
    req = urllib.request.Request(
        url,
        headers={"Accept": "application/vnd.github+json", "User-Agent": "vanguarstew"},
    )
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _collect_open_at(base: str, until: datetime, token, timeout: int, max_pages: int):
    """Walk issues (created desc) page by page, collecting those open at `until`.

    Sorted newest-first, so pages created after T are skipped cheaply (small for recent T,
    the preferred case), then open-at-T items are gathered until the history is exhausted
    (a short page) or the page cap is hit. Returns (open_issues, open_prs, truncated).
    """
    open_issues, open_prs = [], []
    truncated = False
    for page in range(1, max_pages + 1):
        batch = _get(
            f"{base}/issues?state=all&per_page=100&sort=created&direction=desc&page={page}",
            token, timeout,
        )
        if not batch:
            break
        for it in batch:
            created = _parse_dt(it.get("created_at"))
            if created is None or created > until:
                continue          # created after T — future, skip
            closed = _parse_dt(it.get("closed_at"))
            if closed is not None and closed <= until:
                continue          # already closed by T — not open
            rec = {
                "number": it.get("number"),
                "title": it.get("title"),
                "labels": [lbl.get("name") for lbl in it.get("labels", [])],
                "created_at": it.get("created_at"),
            }
            (open_prs if it.get("pull_request") else open_issues).append(rec)
        if len(batch) < 100:
            break                 # exhausted all issues — complete
        if page == max_pages:
            truncated = True      # more pages remain beyond the cap
    return open_issues, open_prs, truncated


def fetch_context_at(owner: str, repo: str, until: datetime, token=None,
                     per_page: int = 100, timeout: int = 20,
                     max_issue_pages: int = DEFAULT_MAX_ISSUE_PAGES) -> dict:
    """GitHub-derived context knowable at `until` (a timezone-aware UTC datetime).

    Issues/PRs are paginated (created desc) back toward T so open-at-T reconstruction is
    complete regardless of how old T is, bounded by `max_issue_pages`; `_issues_truncated`
    flags when the cap was hit before exhausting history.
    """
    token = token or os.environ.get("GITHUB_TOKEN") or None
    base = f"{API}/repos/{owner}/{repo}"

    open_issues, open_prs, truncated = _collect_open_at(base, until, token, timeout,
                                                        max_issue_pages)

    labels = [lbl.get("name") for lbl in _get(f"{base}/labels?per_page={per_page}", token, timeout)]

    milestones = []
    for m in _get(f"{base}/milestones?state=all&per_page={per_page}", token, timeout):
        rec = _milestone_at(m, until)
        if rec is not None:
            milestones.append(rec)

    releases = []
    for r in _get(f"{base}/releases?per_page={per_page}", token, timeout):
        published = _parse_dt(r.get("published_at"))
        if published is not None and published <= until:
            releases.append({"tag": r.get("tag_name"), "name": r.get("name"),
                             "published_at": r.get("published_at")})

    return {
        "repo": f"{owner}/{repo}",
        "open_issues": open_issues,
        "open_prs": open_prs,
        "labels": labels,
        "milestones": milestones,
        "releases": releases,
        "_source": "github-api",
        "_knowable_until": until.isoformat(),
        "_issues_truncated": truncated,
    }


def enrich_context(context: dict, source_repo_path: str, token=None) -> dict:
    """Merge GitHub state (as of the freeze time in `context`) into a git-only context.

    Remote is read from `source_repo_path` (the original clone), since the frozen checkout
    has no `.git`. Returns the context unchanged (annotated) on any failure.
    """
    try:
        from benchmark.freeze import origin_url
        owner, repo = parse_owner_repo(origin_url(source_repo_path))
        until = _parse_dt((context.get("frozen_at") or {}).get("date"))
        if not (owner and repo and until):
            return context
        gh = fetch_context_at(owner, repo, until, token=token)
        merged = dict(context)
        for key in ("repo", "open_issues", "open_prs", "labels", "milestones", "releases"):
            if gh.get(key):
                merged[key] = gh[key]
        merged["_github_enriched"] = True
        return merged
    except Exception as exc:  # offline / rate-limited / private — degrade to git-only
        merged = dict(context)
        merged["_github_error"] = str(exc)[:200]
        return merged
