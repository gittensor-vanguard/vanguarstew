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

# As-of-T provenance for every field surfaced by `fetch_context_at`, from a focused audit of
# mutable GitHub fields (issue #79). Each field is an immutable creation fact, guarded by an
# explicit as-of-T filter, or DROPPED because the list APIs cannot reconstruct its value at T
# (so present-day state would otherwise leak into a snapshot that claims to be frozen at T).
FIELD_PROVENANCE = {
    "issue_or_pr.number": "immutable creation fact",
    "issue_or_pr.created_at": "immutable creation fact",
    "issue_or_pr.title": (
        "mutable (editable after T); the list API exposes no edit history, so the as-of-T "
        "title is unreconstructable — kept best-effort, as it rarely encodes future outcome"
    ),
    "issue_or_pr.labels": (
        "reconstructed from timeline labeled/unlabeled events up to T; the live label list is "
        "never copied directly because it can include outcome / mult:* / duplicate labels "
        "applied after T"
    ),
    "issue_or_pr.labels_as_of_t": (
        "true when timeline history was available and label membership was reconstructed as of "
        "T, including the empty set; false means label history was unavailable or incomplete"
    ),
    "issue_or_pr.membership": (
        "guarded: an item is included only if created_at <= T and not closed by T; its live "
        "state/closed_at drive membership only and are never copied"
    ),
    "labels": (
        "current repo label vocabulary; GitHub's labels API exposes no creation time, so an "
        "as-of-T set is unreconstructable — treated as approximately stable"
    ),
    "milestones.title": "created_at-filtered milestone title; mutable after T, kept best-effort",
    "milestones.state": "derived from closed_at as-of-T rather than copied from the live state",
    "milestones.due_on": (
        "mutable editable due date; no cheap historical reconstruction, so the snapshot keeps "
        "the live value best-effort rather than claiming it is exact as-of-T"
    ),
    "releases.tag": "published_at-guarded immutable release tag",
    "releases.name": (
        "published_at-guarded release name; mutable after T, kept best-effort and "
        "forward-reference scrubbed"
    ),
    "releases.published_at": "published_at-guarded release timestamp",
}

# The only issue/PR fields safe to copy into an as-of-T snapshot: immutable creation facts.
# Everything else a raw GitHub item carries (labels, current state/closed_at, assignees,
# reactions, updated_at, …) is mutable and cannot be reconstructed as-of-T from the list API.
_AS_OF_T_ITEM_FIELDS = ("number", "title", "created_at")


def _as_of_t_record(item: dict) -> dict:
    """Project a raw GitHub issue/PR down to its immutable core fields.

    Whitelisting (rather than copy-then-delete) means a newly-added mutable field on a GitHub
    item can never silently leak future state into a frozen snapshot. As-of-T label membership
    is added separately from the item's timeline.
    """
    return {field: item.get(field) for field in _AS_OF_T_ITEM_FIELDS}


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


def _labels_at(events, until: datetime):
    """Reconstruct an issue/PR's label set *as of `until`* from its timeline.

    Replays ``labeled`` / ``unlabeled`` events in chronological order, ignoring any
    event after T, so the result reflects membership at the freeze time rather than
    today's live labels. Returns a sorted list of label names, possibly empty when
    the timeline shows no labels at T, or ``None`` when the timeline was unavailable.
    """
    if events is None:
        return None
    relevant = []
    for ev in events:
        if ev.get("event") not in ("labeled", "unlabeled"):
            continue
        ts = _parse_dt(ev.get("created_at"))
        if ts is None or ts > until:
            continue
        name = (ev.get("label") or {}).get("name")
        if name:
            relevant.append((ts, ev.get("event"), name))
    relevant.sort(key=lambda x: x[0])
    labels = set()
    for _, etype, name in relevant:
        if etype == "labeled":
            labels.add(name)
        else:
            labels.discard(name)
    return sorted(labels)


def _issue_timeline(base: str, number, token, timeout: int, max_pages: int = 5):
    """Fetch an issue/PR's timeline events, or ``None`` when history is unavailable."""
    if number is None:
        return None
    events = []
    for page in range(1, max_pages + 1):
        try:
            batch = _get(f"{base}/issues/{number}/timeline?per_page=100&page={page}",
                         token, timeout)
        except Exception:
            return None
        if not batch:
            return events
        events.extend(batch)
        if len(batch) < 100:
            return events
    return None


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
            # Labels are mutable and the live list leaks today's state, so
            # reconstruct membership as-of-T from the item's timeline instead of
            # copying it.get("labels"). When the timeline can't be read (offline,
            # rate-limited, or capped before completion), omit labels rather than leak.
            as_of_t = _labels_at(
                _issue_timeline(base, it.get("number"), token, timeout), until
            )
            rec = _as_of_t_record(it)
            rec["labels"] = as_of_t if as_of_t is not None else []
            rec["labels_as_of_t"] = as_of_t is not None
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
        "_field_provenance": FIELD_PROVENANCE,
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
        if gh.get("_field_provenance"):
            merged["_field_provenance"] = gh["_field_provenance"]
        merged["_github_enriched"] = True
        return merged
    except Exception as exc:  # offline / rate-limited / private — degrade to git-only
        merged = dict(context)
        merged["_github_error"] = str(exc)[:200]
        return merged
