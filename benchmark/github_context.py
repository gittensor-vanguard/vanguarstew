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


def _get(url: str, token, timeout: int = 20):
    req = urllib.request.Request(
        url,
        headers={"Accept": "application/vnd.github+json", "User-Agent": "vanguarstew"},
    )
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def fetch_context_at(owner: str, repo: str, until: datetime, token=None,
                     per_page: int = 100, timeout: int = 20) -> dict:
    """GitHub-derived context knowable at `until` (a timezone-aware UTC datetime).

    Note: issues/PRs are drawn from the most recent `per_page` items (created desc), then
    filtered to those open at `until`. This is accurate for *recent* freeze points — which
    the leakage strategy prefers anyway — but under-fills open_issues/open_prs for a T far in
    the past (their open-at-T items fall outside the first page). Full historical coverage
    would require paginating back to T; deferred.
    """
    token = token or os.environ.get("GITHUB_TOKEN") or None
    base = f"{API}/repos/{owner}/{repo}"

    open_issues, open_prs = [], []
    issues = _get(f"{base}/issues?state=all&per_page={per_page}&sort=created&direction=desc",
                  token, timeout)
    for it in issues:
        created = _parse_dt(it.get("created_at"))
        closed = _parse_dt(it.get("closed_at"))
        if created is None or created > until:
            continue          # created after T — future, skip
        if closed is not None and closed <= until:
            continue          # already closed by T — not open
        rec = {
            "number": it.get("number"),
            "title": it.get("title"),
            "labels": [lbl.get("name") for lbl in it.get("labels", [])],
            "created_at": it.get("created_at"),
        }
        (open_prs if it.get("pull_request") else open_issues).append(rec)

    labels = [lbl.get("name") for lbl in _get(f"{base}/labels?per_page={per_page}", token, timeout)]

    milestones = []
    for m in _get(f"{base}/milestones?state=all&per_page={per_page}", token, timeout):
        created = _parse_dt(m.get("created_at"))
        if created is not None and created <= until:
            milestones.append({"title": m.get("title"), "due_on": m.get("due_on"),
                               "state": m.get("state")})

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
