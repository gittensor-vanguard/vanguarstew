"""Enrich a frozen snapshot with GitHub state that was knowable at time T.

`freeze.py` gives us git-only context (commits, tags, README). This adds the maintainer's
real working surface — open issues, open PRs, labels, milestones, releases — reconstructed
*as of T* so nothing from the future leaks: an item counts as "open at T" only if it was
created on or before T and was not already closed by T.

Network access is optional. Any failure (offline, rate limit, private repo) is caught and
the git-only context is returned unchanged, so the benchmark still runs without GitHub.

Field stability (``fetch_context_at``)
--------------------------------------
Derived as-of-T (safe):
  - Issue/PR membership: ``created_at`` / ``closed_at`` gate open-at-T selection.
  - Issue/PR labels: reconstructed from timeline ``labeled``/``unlabeled`` events when
    available; omitted (not copied live) when the timeline is unavailable.
  - Milestone ``state``: derived from ``closed_at`` relative to T, not the live API field.
  - Releases: filtered by ``published_at <= T``.

Live-only (present-day REST snapshot — documented, not reconstructable without Events API):
  - Repo ``labels`` list: no created-at on the labels endpoint.
  - Milestone ``due_on``: may be edited after T; we keep the current value as best-effort.
"""

from __future__ import annotations

import json
import os
import urllib.request
from datetime import datetime

API = "https://api.github.com"
DEFAULT_MAX_ISSUE_PAGES = 10  # bound on pages walked back toward T (100 items/page)

# Metadata keys copied from ``fetch_context_at`` into an enriched git-only context.
_ENRICH_META_KEYS = ("_issues_truncated", "_knowable_until", "_source")


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


def _item_open_at(item: dict, until: datetime) -> bool:
    """True when an issue/PR was open at ``until`` (created on/before T, not closed by T)."""
    created = _parse_dt(item.get("created_at"))
    if created is None or created > until:
        return False
    closed = _parse_dt(item.get("closed_at"))
    return closed is None or closed > until


def _issue_record_at(base: str, item: dict, until: datetime, token, timeout: int) -> dict:
    """Minimal issue/PR fields copied into the frozen context as-of ``until``."""
    as_of_t = _labels_at(
        _issue_timeline(base, item.get("number"), token, timeout), until
    )
    return {
        "number": item.get("number"),
        "title": item.get("title"),
        "labels": as_of_t if as_of_t is not None else [],
        "labels_as_of_t": as_of_t is not None,
        "created_at": item.get("created_at"),
    }


def _milestone_at(milestone: dict, until: datetime) -> dict | None:
    """A milestone as knowable at ``until``, or None if it did not exist yet.

    ``state`` is derived from ``closed_at`` as-of T — ``"closed"`` only when the milestone
    was already closed by T — rather than the milestone's present-day ``state`` field.
    """
    created = _parse_dt(milestone.get("created_at"))
    if created is None or created > until:
        return None
    closed = _parse_dt(milestone.get("closed_at"))
    state = "closed" if closed is not None and closed <= until else "open"
    return {
        "title": milestone.get("title"),
        "due_on": milestone.get("due_on"),
        "state": state,
    }


def _get(url: str, token, timeout: int = 20):
    req = urllib.request.Request(
        url,
        headers={"Accept": "application/vnd.github+json", "User-Agent": "vanguarstew"},
    )
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _labels_at(events, until: datetime):
    """Reconstruct an issue/PR's label set *as of `until`* from its timeline.

    Replays ``labeled`` / ``unlabeled`` events in chronological order, ignoring any
    event after T, so the result reflects membership at the freeze time rather than
    today's live labels. Returns a sorted list of label names, or ``None`` when the
    timeline carries no usable label event at/or before T — the caller then falls
    back to omitting labels rather than leaking the present-day set.
    """
    relevant = []
    for ev in events or []:
        if ev.get("event") not in ("labeled", "unlabeled"):
            continue
        ts = _parse_dt(ev.get("created_at"))
        if ts is None or ts > until:
            continue
        name = (ev.get("label") or {}).get("name")
        if name:
            relevant.append((ts, ev.get("event"), name))
    if not relevant:
        return None
    relevant.sort(key=lambda x: x[0])
    labels = set()
    for _, etype, name in relevant:
        if etype == "labeled":
            labels.add(name)
        else:
            labels.discard(name)
    return sorted(labels)


def _issue_timeline(base: str, number, token, timeout: int, max_pages: int = 5):
    """Fetch an issue/PR's timeline events (paginated). Returns ``[]`` on any error,
    so label reconstruction degrades to the safe omit-labels fallback offline."""
    if number is None:
        return []
    events = []
    for page in range(1, max_pages + 1):
        try:
            batch = _get(f"{base}/issues/{number}/timeline?per_page=100&page={page}",
                         token, timeout)
        except Exception:
            break
        if not batch:
            break
        events.extend(batch)
        if len(batch) < 100:
            break
    return events


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
            if not _item_open_at(it, until):
                continue
            rec = _issue_record_at(base, it, until, token, timeout)
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
        for key in _ENRICH_META_KEYS:
            if key in gh:
                merged[key] = gh[key]
        merged["_github_enriched"] = True
        return merged
    except Exception as exc:  # offline / rate-limited / private — degrade to git-only
        merged = dict(context)
        merged["_github_error"] = str(exc)[:200]
        return merged
