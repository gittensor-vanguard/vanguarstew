"""Enrich a frozen snapshot with GitHub state that was knowable at time T.

`freeze.py` gives us git-only context (commits, tags, README). This adds the maintainer's
real working surface — open issues, open PRs, milestones, releases, and other fields we can
defend *as of T* — so nothing from the future leaks: an item counts as "open at T" only if it
was created on or before T and was not already closed by T.

Network access is optional. Any failure (offline, rate limit, private repo) is caught and
the git-only context is returned unchanged, so the benchmark still runs without GitHub.

Field stability (``fetch_context_at``)
--------------------------------------
Derived as-of-T (safe):
  - Issue/PR membership: ``created_at`` / ``closed_at`` gate open-at-T selection.
  - Issue/PR labels: reconstructed from timeline ``labeled``/``unlabeled`` events when
    available; omitted (not copied live) when the timeline is unavailable.
  - Milestone ``state``: derived from ``closed_at`` relative to T, not the live API field.
  - Releases: filtered by ``published_at <= T`` (drafts, which carry no ``published_at``,
    are excluded).

Live, copied as-is (no cheap as-of-T source):
  - Issue/PR ``number`` and ``created_at``: immutable, so the live value already equals the
    as-of-T value.
  - Issue/PR ``title``: the present-day title, which can be edited after T. Consumers must not
    treat it as historically exact; accepted as a residual limitation (title edits are rare and
    there is no cheap as-of-T source).

Omitted (no created-at or editable after T, so not reconstructable as-of-T — dropped rather
than leaked as a present-day value):
  - Repo ``labels`` catalog: the labels endpoint carries no created-at, so its live list
    would leak today's set; not fetched at all (``fetch_context_at`` returns no ``labels``).
  - Milestone ``due_on``: the REST value is today's editable due date, so a post-T edit would
    leak; dropped rather than carried as a possibly-future value.
"""

from __future__ import annotations

import json
import logging
import os
import urllib.request
from datetime import datetime

logger = logging.getLogger(__name__)

API = "https://api.github.com"
DEFAULT_MAX_ISSUE_PAGES = 10  # bound on pages walked back toward T (100 items/page)
DEFAULT_MAX_LIST_PAGES = 10   # bound on pages walked for milestones / releases

# Metadata keys copied from ``fetch_context_at`` into an enriched git-only context.
_ENRICH_META_KEYS = ("_issues_truncated", "_knowable_until", "_source")


def parse_owner_repo(remote_url: str):
    """Extract (owner, repo) from an ssh or https GitHub remote URL."""
    if not isinstance(remote_url, str):
        return None, None
    s = remote_url.strip()
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
    """Parse an ISO-8601 timestamp string, or None when the input is unusable."""
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _item_open_at(item: dict, until: datetime) -> bool:
    """True when an issue/PR was open at ``until`` (created on/before T, not closed by T)."""
    created = _parse_dt(item.get("created_at"))
    if created is None or created > until:
        return False
    closed = _parse_dt(item.get("closed_at"))
    return closed is None or closed > until


def _issue_record_at(base: str, item: dict, until: datetime, token, timeout: int) -> dict:
    """Minimal issue/PR fields for the frozen context.

    ``number``/``created_at`` are immutable and ``labels`` are reconstructed as-of ``until``.
    ``title`` is copied live (present-day value): it may have been edited after T — an accepted
    residual limitation noted in the module's field-stability contract.
    """
    events, truncated = _issue_timeline(base, item.get("number"), token, timeout)
    # A truncated timeline can produce a label set that actively contradicts the true as-of-T
    # membership, so fail closed exactly like the timeline-unavailable case: omit labels and
    # report labels_as_of_t=False rather than trusting a partial (possibly wrong) reconstruction.
    as_of_t = None if truncated else _labels_at(events, until)
    return {
        "number": item.get("number"),
        "title": item.get("title"),
        "labels": as_of_t if as_of_t is not None else [],
        "labels_as_of_t": as_of_t is not None,
        "created_at": item.get("created_at"),
    }


def _milestone_at(milestone: dict, until: datetime) -> dict | None:
    """A milestone as knowable at ``until``, or None if it did not exist yet.

    Returns None when the milestone was created after T. Otherwise ``state`` is derived from
    ``closed_at`` *as of T* — ``"closed"`` only when it was already closed by T — rather than
    the milestone's present-day state, so a milestone closed after T isn't leaked as completed.

    ``due_on`` is intentionally omitted: the REST snapshot is today's editable due date, and we
    do not have a cheap historical edit stream to reconstruct it reliably as-of-T.
    """
    created = _parse_dt(milestone.get("created_at"))
    if created is None or created > until:
        return None
    closed = _parse_dt(milestone.get("closed_at"))
    state = "closed" if closed is not None and closed <= until else "open"
    return {"title": milestone.get("title"), "state": state}


def _get(url: str, token, timeout: int = 20):
    req = urllib.request.Request(
        url,
        headers={"Accept": "application/vnd.github+json", "User-Agent": "vanguarstew"},
    )
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _get_all(url: str, token, timeout: int, max_pages: int, per_page: int = 100):
    """Collect items across a paginated GitHub list response.

    `url` already carries its query string (including `per_page`); a `page=` parameter is
    appended per request. Pagination stops on the first empty or short (< `per_page`) page or
    when `max_pages` is reached. Request errors propagate, so a hard failure still fails the
    whole enrichment closed to git-only context — the same posture as before, only now the
    result is complete instead of silently capped at the first 100 items.
    """
    sep = "&" if "?" in url else "?"
    items = []
    for page in range(1, max_pages + 1):
        batch = _get(f"{url}{sep}page={page}", token, timeout)
        if not batch:
            break
        items.extend(batch)
        if len(batch) < per_page:
            break
    return items


def _timeline_events(events) -> list:
    """Return ``events`` when it is a list; otherwise treat as no timeline.

    A truthy non-list must not reach ``for ev in events`` or malformed timeline JSON
    aborts label reconstruction (#488). An empty timeline makes :func:`_labels_at` return
    ``None``, so the caller omits labels (fail-closed) rather than leaking live labels.
    """
    if isinstance(events, list):
        return events
    if events is not None:
        logger.warning(
            "github_context: timeline events is %s, not a list; treating as empty",
            type(events).__name__,
        )
    return []


def _labels_at(events, until: datetime):
    """Reconstruct an issue/PR's label set *as of `until`* from its timeline.

    Replays ``labeled`` / ``unlabeled`` events in chronological order, ignoring any
    event after T, so the result reflects membership at the freeze time rather than
    today's live labels. Returns a sorted list of label names, or ``None`` when the
    timeline carries no usable label event at/or before T — the caller then falls
    back to omitting labels rather than leaking the present-day set.

    A non-list ``events`` value is treated as an empty timeline (``None``), matching
    the fail-closed posture used when reconstruction is unavailable.
    """
    relevant = []
    for idx, ev in enumerate(_timeline_events(events)):
        if not isinstance(ev, dict):
            logger.warning(
                "github_context: skipping non-dict timeline event at index %d (%s: %r)",
                idx,
                type(ev).__name__,
                ev,
            )
            continue
        if ev.get("event") not in ("labeled", "unlabeled"):
            continue
        ts = _parse_dt(ev.get("created_at"))
        if ts is None or ts > until:
            continue
        label = ev.get("label")
        if not isinstance(label, dict):
            continue
        name = label.get("name")
        if not isinstance(name, str) or not name.strip():
            continue
        relevant.append((ts, ev.get("event"), name.strip()))
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
    """Fetch an issue/PR's timeline events (paginated).

    Returns ``(events, truncated)``. ``truncated`` is True when the page cap is hit with a
    full final page — more events may exist before T than were fetched, so a label
    reconstruction from ``events`` could be *confidently wrong* (a later ``unlabeled`` beyond
    the cap never gets applied) and the caller must not trust it. Returns ``([], False)`` on
    any error or missing number, so reconstruction degrades to the safe omit-labels fallback.
    """
    if number is None:
        return [], False
    events = []
    truncated = False
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
        if page == max_pages:
            truncated = True      # full final page at the cap: more events may remain before T
    return events, truncated


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
                     max_issue_pages: int = DEFAULT_MAX_ISSUE_PAGES,
                     max_list_pages: int = DEFAULT_MAX_LIST_PAGES) -> dict:
    """GitHub-derived context knowable at `until` (a timezone-aware UTC datetime).

    Issues/PRs are paginated (created desc) back toward T so open-at-T reconstruction is
    complete regardless of how old T is, bounded by `max_issue_pages`; `_issues_truncated`
    flags when the cap was hit before exhausting history.

    Milestones and releases are likewise paginated (bounded by `max_list_pages`) instead of
    reading only the first page — a repo with more than `per_page` of either would otherwise
    silently drop the rest, which can hide a milestone that was open at T or an older release
    that sets the frozen base version.
    """
    token = token or os.environ.get("GITHUB_TOKEN") or None
    base = f"{API}/repos/{owner}/{repo}"

    open_issues, open_prs, truncated = _collect_open_at(base, until, token, timeout,
                                                        max_issue_pages)

    milestones = []
    for m in _get_all(f"{base}/milestones?state=all&per_page={per_page}", token, timeout,
                      max_list_pages, per_page):
        rec = _milestone_at(m, until)
        if rec is not None:
            milestones.append(rec)

    releases = []
    for r in _get_all(f"{base}/releases?per_page={per_page}", token, timeout, max_list_pages,
                      per_page):
        published = _parse_dt(r.get("published_at"))
        if published is not None and published <= until:
            releases.append({"tag": r.get("tag_name"), "name": r.get("name"),
                             "published_at": r.get("published_at")})

    return {
        "repo": f"{owner}/{repo}",
        "open_issues": open_issues,
        "open_prs": open_prs,
        "milestones": milestones,
        "releases": releases,
        "_source": "github-api",
        "_knowable_until": until.isoformat(),
        "_issues_truncated": truncated,
    }


def _frozen_at_date(context: dict):
    """Parse ``context['frozen_at']['date']``, or None when missing or unusable."""
    if not isinstance(context, dict):
        return None
    frozen = context.get("frozen_at")
    if not isinstance(frozen, dict):
        return None
    return _parse_dt(frozen.get("date"))


def enrich_context(context: dict, source_repo_path: str, token=None) -> dict:
    """Merge GitHub state (as of the freeze time in `context`) into a git-only context.

    Remote is read from `source_repo_path` (the original clone), since the frozen checkout
    has no `.git`. Returns the context unchanged (annotated) on any failure.

    A non-dict ``context`` is returned unchanged so callers can degrade without aborting
    the replay path (#518).
    """
    if not isinstance(context, dict):
        logger.warning(
            "github_context: enrich_context context is %s, not a dict; returning unchanged",
            type(context).__name__ if context is not None else "None",
        )
        return context
    try:
        from benchmark.freeze import origin_url
        owner, repo = parse_owner_repo(origin_url(source_repo_path))
        until = _frozen_at_date(context)
        if not (owner and repo and until):
            return context
        gh = fetch_context_at(owner, repo, until, token=token)
        merged = dict(context)
        # No ``labels`` here: the repo label catalog is intentionally omitted from the frozen
        # context (see module docstring), so ``fetch_context_at`` never produces that key.
        for key in ("repo", "open_issues", "open_prs", "milestones", "releases"):
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
