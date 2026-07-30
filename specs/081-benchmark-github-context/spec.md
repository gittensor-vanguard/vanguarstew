# Spec 081 — knowable-at-T GitHub context producer

- **Status:** draft (SDD Phase 1 — Specify)
- **Owner:** benchmark
- **Issue:** #1993
- **Constitution:** [`AGENTS.md`](../../AGENTS.md) → *Benchmark integrity (M1–M3)*
- **Methodology:** [`blog/spec-driven-development.md`](../../blog/spec-driven-development.md)
- **Related:** [`benchmark/github_context.py`](../../benchmark/github_context.py) (the producer under
  test), [`benchmark/freeze.py`](../../benchmark/freeze.py) (`origin_url`, `frozen_at` consumed by
  `enrich_context`), [`specs/003-leakage-integrity`](../003-leakage-integrity/spec.md) (the
  knowable-at-T policy this module enforces), [`specs/022-benchmark-leakage-audit`](../022-benchmark-leakage-audit/spec.md)
  (the forward-reference *detector*; this spec pins the *producer*), [`specs/085-benchmark-freeze`](../085-benchmark-freeze/spec.md)
  (the git-only context this module enriches)

This spec makes the **existing, implicit** GitHub-context producer contract explicit. It describes
the as-built behavior of `benchmark/github_context.py`; it introduces **no behavior change**.

## Why

`benchmark/github_context.py` is where the knowable-at-T boundary is enforced for the maintainer's
working surface — open issues/PRs, their labels and titles, milestones and releases. Spec 003 states
the leakage principle and Spec 022 pins `audit_context` (the detector); nothing yet pins the
**producer**. At 534 lines it is the largest unspecced module in `benchmark/`, and the one where a
silent regression is least likely to be caught: a leak here does not crash, it just makes the
agent's scored context quietly better than it should be.

The module's own docstring already carries a careful field-stability policy (derived-as-of-T vs.
copied-live vs. deliberately omitted). This spec makes that policy executable.

## User stories

1. **As a benchmark operator**, I can trust that `enrich_context` adds only GitHub state that was
   knowable at freeze time T, and degrades to git-only context on any failure.
2. **As a reviewer**, every remote-parse quirk, timestamp edge case, timeline truncation rule, label
   vs. title fail-closed posture, pagination cap, and backlog gate is written down so a change to
   this module is checked against intent.
3. **As a leakage auditor**, I can distinguish what the producer guarantees (as-built) from what
   the detector (`audit_context`, Spec 022) checks downstream.

## Constants

- `API` SHALL be `"https://api.github.com"`.
- `DEFAULT_MAX_ISSUE_PAGES` SHALL be `10` (issues/PRs list pagination cap).
- `DEFAULT_MAX_LIST_PAGES` SHALL be `10` (milestones/releases list pagination cap).
- `_ENRICH_META_KEYS` SHALL be `("_issues_truncated", "_milestones_truncated",
  "_releases_truncated", "_knowable_until", "_source")`.

## Warnings

Where this spec says a helper "warns", the delivery is a single `logging.warning` call on the module
logger `benchmark.github_context`; no exception is raised and the sanitized value is still returned.
The message content is pinned per case below and is asserted via `caplog` in the contract tests.

## Acceptance criteria (EARS)

### Remote parsing (`parse_owner_repo`)

- WHEN `remote_url` is not a `str` THEN `parse_owner_repo` SHALL return `(None, None)`.
- OTHERWISE the URL SHALL be stripped; a trailing `.git` suffix SHALL be removed only when it is the
  final characters of the stripped string (a URL ending in `.git/` retains `.git` in the repo
  segment).
- An `git@host:path` SSH URL SHALL take the path after the first `:`; an HTTPS URL containing
  `github.com/` SHALL take the path after `github.com/`; OTHERWISE the whole stripped string SHALL
  be treated as the path (non-GitHub hosts are not rejected — e.g. `https://gitlab.com/o/r` yields
  `("https:", "gitlab.com")`, a truthy pair that `enrich_context` may attempt against the GitHub
  API before degrading).
- The first two non-empty `/`-separated path segments SHALL be returned as `(owner, repo)`; trailing
  subpaths (`/tree/…`, `/blob/…`) SHALL be ignored; fewer than two segments SHALL yield
  `(None, None)`.

### Timestamp parsing (`_parse_dt`, `_frozen_at_date`)

- `_parse_dt(value)` SHALL return `None` when `value` is not a non-empty `str` or is not
  ISO-8601-parseable (after replacing trailing `Z` with `+00:00`).
- OTHERWISE it SHALL return a `datetime` from `datetime.fromisoformat` (which may be
  timezone-naive when the input carries no offset).
- `_frozen_at_date(context)` SHALL return `None` when `context` is not a `dict`, `frozen_at` is not
  a `dict`, or `frozen_at["date"]` is unusable per `_parse_dt`; otherwise the parsed datetime.

### Open-at-T membership (`_item_open_at`)

- An item SHALL count as open at `until` when `created_at` parses and is `<= until`, AND either
  `closed_at` is missing/unparseable OR `closed_at` parses and is `> until` (inclusive on
  `created_at`, exclusive on closure — an item closed exactly at T is not open).
- WHEN `created_at` is missing or unparseable THEN the item SHALL NOT be open.
- WHEN a parsed timestamp is timezone-naive but `until` is timezone-aware (or vice versa) THEN
  comparison SHALL raise `TypeError` (not caught inside `_item_open_at`); inside `fetch_context_at`
  / `enrich_context` this propagates to the catch-all and silently drops the entire GitHub surface
  for the run.

### Timeline close correction (`_closed_at_from_timeline`)

- Events SHALL be read via `_timeline_events`; only `closed` / `reopened` events with a parseable
  `created_at <= until` SHALL contribute.
- WHEN no such events exist THEN the function SHALL return `False` (no correction — trust live
  `closed_at`).
- OTHERWISE events SHALL be sorted by timestamp before reading state; the last toggle's
  `reopened`/`closed` value determines open/closed at T, and the return SHALL be the negation of
  "open at T" (order-independent even when the input list is out of chronological order).
- WHEN the corrected state shows the item was closed at T THEN `_issue_record_at` SHALL return
  `None` (exclude the item), but only when the timeline is complete (`truncated` is `False`).

### Timeline container (`_timeline_events`)

- WHEN `events` is a `list` THEN it SHALL be returned unchanged.
- WHEN `events` is a truthy non-list THEN a warning
  `github_context: timeline events is {type}, not a list; treating as empty` SHALL be logged and
  `[]` returned.
- WHEN `events` is `None` or falsy THEN `[]` SHALL be returned silently.

### Label reconstruction (`_labels_at`)

- Only `labeled` / `unlabeled` events with a parseable `created_at <= until` and a dict `label` whose
  `name` is a non-empty stripped `str` SHALL contribute; non-dict events SHALL be skipped with a
  warning including the index.
- Events SHALL be replayed in chronological order (sorted before application) regardless of input
  order.
- WHEN no usable label events exist at/before T THEN the function SHALL return `None` ("not
  reconstructable — fail closed and omit").
- WHEN usable events exist and replay yields an empty set (every label added before T was removed
  before T) THEN the function SHALL return `[]` ("reconstructed, genuinely no labels at T").
- The caller (`_issue_record_at`) maps `None` → `labels=[]`, `labels_as_of_t=False`; maps a list
  (including `[]`) → that list, `labels_as_of_t=True`.

### Title reconstruction (`_title_at`)

- Only `renamed` events with parseable `created_at`, dict `rename` with string `from`/`to` SHALL
  contribute; malformed rename payloads SHALL be skipped with a warning.
- WHEN no rename events exist THEN the live `title` SHALL be returned when it is a `str`, else
  `None`.
- Rename events SHALL be sorted chronologically; renames after T SHALL cause the `from` title of the
  earliest post-T rename to be returned; renames at/before T SHALL be replayed to the final title.
- A missing or non-list `events` container SHALL be treated as no timeline (via `_timeline_events`)
  and fall back to the live title.

### Issue timeline fetch (`_issue_timeline`)

- WHEN `number` is `None` THEN the function SHALL return `([], True)`.
- Pagination SHALL request up to `max_pages` pages of 100 events; a short final page means history
  is complete (`truncated=False`); a full final page at the cap means `truncated=True`.
- WHEN any page fetch raises THEN `truncated=True` and collected events so far are returned (a
  first-page error yields `([], True)`).
- An unavailable timeline (nothing collected, or first-page error) SHALL be reported as
  `truncated=True`, not `([], False)`: an empty timeline omits labels safely but the title path reads
  a no-rename timeline as "title never changed" and would leak a post-T rename.
- Only a timeline that was actually fetched and came back empty (complete, event-less issue) returns
  `([], False)`.

### Issue record assembly (`_issue_record_at`)

- WHEN the timeline is complete and `_closed_at_from_timeline` is true THEN return `None`.
- WHEN `truncated` is `True` THEN both `labels` and `title` SHALL be omitted (`labels=[]`,
  `labels_as_of_t=False`, `title=""`, `title_as_of_t=False`) — fail closed on both fields together.
- WHEN the timeline is complete THEN `labels`/`title` SHALL be reconstructed via `_labels_at` /
  `_title_at`; `number` and `created_at` SHALL be copied from the live item (immutable).
- The returned record SHALL always carry keys `number`, `title`, `title_as_of_t`, `labels`,
  `labels_as_of_t`, `created_at`.

### Milestone derivation (`_milestone_at`)

- WHEN `created_at` is missing, unparseable, or `> until` THEN return `None`.
- OTHERWISE `state` SHALL be `"closed"` only when `closed_at` parses and is `<= until`, else
  `"open"` (the live API `state` field is ignored).
- The record SHALL carry only `number` and `state`; `title` and `due_on` SHALL be omitted (no
  as-of-T reconstruction source).

### List pagination (`_get_all`)

- SHALL paginate with `page=` appended to `url` (using `&` when `url` already has a query string),
  stopping on the first empty or short (`< per_page`) page or when `max_pages` is reached.
- SHALL return `(items, truncated)` where `truncated` is `True` when the page cap is hit with a
  full final page; request errors SHALL propagate (not caught inside `_get_all`).

### Context fetch (`fetch_context_at`)

- SHALL resolve `token` from the argument, else `GITHUB_TOKEN` env, else `None`.
- Issues/PRs SHALL be collected via `_collect_open_at` (newest-first pagination, open-at-T filter,
  per-item `_issue_record_at`); WHEN `_issues_truncated` is `True` THEN both `open_issues` and
  `open_prs` SHALL be discarded (`[]`) rather than serving a partial backlog.
- Milestones SHALL be derived via `_milestone_at` only when `_milestones_truncated` is `False`;
  WHEN truncated the list SHALL be `[]`.
- Releases SHALL include only items with parseable `published_at <= until` (drafts excluded); only
  `tag` and `published_at` are kept (`name` omitted); WHEN `_releases_truncated` is `True` the list
  SHALL be `[]`.
- The repo label catalog SHALL NOT be fetched (`labels` key absent from the return).
- The return SHALL always include `repo`, `open_issues`, `open_prs`, `milestones`, `releases`,
  `_source` (`"github-api"`), `_knowable_until` (`until.isoformat()`), and the three
  `_…_truncated` flags.

### Enrichment merge (`enrich_context`)

- WHEN `context` is not a `dict` THEN it SHALL be returned unchanged after a warning
  `github_context: enrich_context context is {type}, not a dict; returning unchanged`.
- OTHERWISE `owner`/`repo` SHALL be parsed from `origin_url(source_repo_path)` and `until` from
  `_frozen_at_date(context)`; WHEN any prerequisite is missing THEN return `context` unchanged.
- On success SHALL merge `repo`, `open_issues`, `open_prs`, `milestones`, `releases`, and
  `_ENRICH_META_KEYS` from `fetch_context_at`, set `_github_enriched=True`, and SHALL NOT propagate
  a `labels` key even if `fetch_context_at` regresses to produce one.
- Keys present in the GitHub payload overwrite stale base values; keys absent from the GitHub
  payload preserve the base value.
- On any exception SHALL return a copy of `context` with `_github_error` set to `str(exc)[:200]`
  (degrade to git-only, no raise).

### Backlog gate (`open_issues_from_context`)

- WHEN `context` is not a `dict` THEN return `None`.
- WHEN `context.get("_issues_truncated") is True` (identity check, not truthiness) THEN return
  `None` (skip backlog scoring — a partial backlog is as misleading as an unavailable one).
- OTHERWISE return `context.get("open_issues")` (which may be `None` when the key is absent).

## Out of scope

- The leakage policy in the abstract (Spec 003) and the forward-reference detector (`audit_context`,
  Spec 022).
- Git-only freeze record shapes (`freeze.py`, Spec 085).
- Network transport, rate limiting, and GitHub API authentication beyond token passthrough.

## Verification

- `tests/test_spec_081_github_context.py` exercises each EARS block above with **literal**
  expectations against in-memory fixtures (no network), including the remote-parse quirks,
  naive-vs-aware timestamp `TypeError`, `None` vs `[]` label semantics, timeline order-independence,
  truncation fail-closed rules, pagination caps, enrichment merge/degradation, and the `is True`
  backlog gate. Values use `repr` stable across platforms.
- Broader integration coverage remains in `tests/test_github_context.py`.
