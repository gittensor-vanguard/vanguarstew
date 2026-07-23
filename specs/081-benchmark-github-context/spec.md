# Spec 081 — knowable-at-T GitHub context

- **Status:** draft (SDD Phase 1 — Specify)
- **Owner:** benchmark
- **Issue:** #1993
- **Constitution:** [`AGENTS.md`](../../AGENTS.md) → *Benchmark integrity (M1–M3)* ("The system SHALL
  NOT let a forward-looking signal leak through the freeze boundary")
- **Methodology:** [`blog/spec-driven-development.md`](../../blog/spec-driven-development.md)
- **Related:** [`benchmark/github_context.py`](../../benchmark/github_context.py) (the module under
  test), [`specs/003-leakage-integrity`](../003-leakage-integrity/spec.md) (the leakage principle),
  [`specs/022-benchmark-leakage-audit`](../022-benchmark-leakage-audit/spec.md) (`audit_context`,
  the *detector* for what this module produces), [`benchmark/freeze.py`](../../benchmark/freeze.py)
  (`origin_url`, and the git-only context this enriches),
  [`benchmark/score.py`](../../benchmark/score.py) (`backlog_recall`, the consumer of
  `open_issues_from_context`)

This spec makes the **existing, implicit** knowable-at-T contract explicit. It describes the
as-built behavior of `benchmark/github_context.py`; it introduces **no behavior change**.

## Why

This module is where the freeze boundary is enforced for the maintainer's *working surface* — open
issues and PRs with their labels and titles, milestones, releases. Spec 003 states the principle and
Spec 022 pins the detector; the producer had nothing. A regression here does not crash: it silently
hands the agent a context that is better than it should be, and every downstream score inherits the
leak. The module already carries a careful field-stability policy in its docstring; this spec makes
that policy executable, including the two rules that are easy to "simplify" away — fail **closed**
when a reconstruction cannot be verified, and discard a **partial** list rather than serve it.

## Field-stability policy

| Field | Treatment |
| ----- | --------- |
| issue/PR membership | derived: `created_at <= T` and not closed by T, corrected from the timeline |
| issue/PR `labels` | reconstructed from `labeled`/`unlabeled` events; **omitted** when unavailable/truncated |
| issue/PR `title` | reconstructed from `renamed` events; **omitted** when unavailable/truncated |
| issue/PR `number`, `created_at` | copied live — immutable, so the live value *is* the as-of-T value |
| milestone `state` | derived from `closed_at` relative to T |
| milestone `number` | copied live (immutable) |
| milestone `title`, `due_on` | **omitted** — editable after T with no edit stream to replay |
| release `tag`, `published_at` | copied live (immutable), filtered to `published_at <= T` |
| release `name` | **omitted** — editable after publication with no edit stream |
| repo `labels` catalog | **not fetched** — the endpoint carries no created-at |

## Constants

- `API` SHALL be `"https://api.github.com"`.
- `DEFAULT_MAX_ISSUE_PAGES` and `DEFAULT_MAX_LIST_PAGES` SHALL each be `10`.
- `_ENRICH_META_KEYS` SHALL be `("_issues_truncated", "_milestones_truncated",
  "_releases_truncated", "_knowable_until", "_source")`.

## Acceptance criteria (EARS)

### Remote parsing (`parse_owner_repo`)

- A non-string remote SHALL yield `(None, None)`.
- A trailing `.git` SHALL be stripped, an `scp`-style `git@host:owner/repo` SHALL be split at the
  first `:`, and an `https://…github.com/` URL SHALL be split after `github.com/`.
- The result SHALL be the **first two** non-empty `/`-separated segments of what remains, so a
  trailing `/tree/main` or `/blob/…` subpath still resolves to the repository root; fewer than two
  segments SHALL yield `(None, None)`.
- Consequences that are part of the contract: the function is **not** GitHub-specific — a remote
  with no `github.com/` is split on `/` regardless, so `https://gitlab.com/o/r` yields
  `("https:", "gitlab.com")` rather than `(None, None)`; and because the `.git` strip is anchored to
  the end of the string, a trailing slash (`https://github.com/o/r.git/`) leaves repo `"r.git"`.

### Timestamp parsing (`_parse_dt`)

- A non-string or empty value SHALL yield `None`, and an unparseable string SHALL yield `None`
  (`ValueError` is caught).
- A trailing `Z` SHALL be normalized to `+00:00` before `datetime.fromisoformat`.
- An offset-less (**naive**) but otherwise valid timestamp SHALL parse to a *naive* `datetime`. It is
  therefore NOT comparable with the timezone-aware `until` the callers pass: `_item_open_at` and
  `_milestone_at` SHALL propagate `TypeError` for such an input. Inside `fetch_context_at` that is
  caught by `enrich_context`'s catch-all and degrades the run to git-only context.

### At-T membership (`_item_open_at`)

- It SHALL be true only when `created_at` parses and is `<= until`, **and** `closed_at` either does
  not parse or is `> until`. Both bounds are **inclusive at T**: an item created exactly at T counts
  as created by T, and an item closed exactly at T counts as closed.
- An unparseable/missing `created_at` SHALL yield `False` (an item that cannot be dated cannot be
  shown to have existed at T); an unparseable/missing `closed_at` SHALL read as "not closed".

### Timeline close correction (`_closed_at_from_timeline`)

- It SHALL replay the timeline's `closed`/`reopened` events dated `<= until`, in chronological
  order, and return the negation of the resulting state (`reopened` last ⇒ open ⇒ `False`).
- WHEN no such event exists at or before T (an empty, non-list, or event-less timeline, or one whose
  toggles are all after T) THEN it SHALL return `False` — no correction — because the item's state
  never changed by T and the live `closed_at` already reflects the truth.
- It SHALL sort before reading the final state, so a timeline delivered out of chronological order
  resolves identically to an ordered one.

### Issue/PR record (`_issue_record_at`)

- It SHALL fetch the item's timeline and, WHEN the timeline is **not** truncated AND
  `_closed_at_from_timeline` reports closed at T, return `None` — the item is dropped from the
  frozen context (the closed-then-reopened false positive).
- WHEN the timeline **is** truncated THEN the close correction SHALL be skipped (the live-snapshot
  decision stands) AND both `labels` and `title` SHALL be failed closed: `labels` `[]` with
  `labels_as_of_t` `False`, `title` `""` with `title_as_of_t` `False`. A partial reconstruction can
  contradict the truth, so it is never trusted.
- OTHERWISE the record SHALL be exactly `{"number", "title", "title_as_of_t", "labels",
  "labels_as_of_t", "created_at"}`, with `number`/`created_at` copied live, `labels` from
  `_labels_at` (`[]` and `labels_as_of_t` `False` when that is `None`), and `title` from `_title_at`
  (`""` and `title_as_of_t` `False` when that is `None`).

### Label reconstruction (`_labels_at`)

- It SHALL replay `labeled`/`unlabeled` events dated `<= until` in chronological order and return
  the resulting names **sorted**.
- A non-dict event SHALL be skipped **with a warning**; an event of another type, one whose
  timestamp is missing/unparseable/after T, one whose `label` is not a dict, and one whose `name` is
  not a non-blank string SHALL each be skipped silently. Names SHALL be stripped.
- WHEN no usable event survives (including a non-list or empty `events`) THEN it SHALL return
  `None` — "not reconstructable", which the caller fails closed on.
- `None` and `[]` are **distinct** results: `[]` means the reconstruction succeeded and the item
  genuinely carried no labels at T (every label added before T was also removed before T), and the
  caller reports `labels_as_of_t` `True` for it.
- The at-T bound is inclusive: an event dated exactly T SHALL be applied.

### Title reconstruction (`_title_at`)

- It SHALL collect `renamed` events with a parseable timestamp and a `rename` dict whose `from` and
  `to` are both strings; a non-dict `rename` SHALL be skipped **with a warning**, other malformed
  payloads silently.
- WHEN no usable rename exists THEN it SHALL return `live_title` when that is a string, else `None`
  — GitHub records every title change as a `renamed` event, so an event-less complete timeline means
  the live title has never changed.
- OTHERWISE, sorted chronologically: WHEN the earliest rename is **after** T THEN it SHALL return
  that rename's `from` (the title immediately before the first post-T edit). OTHERWISE it SHALL
  return the `to` of the last rename at or before T. An event dated exactly T counts as at-or-before.

### Milestones (`_milestone_at`)

- It SHALL return `None` when `created_at` is missing/unparseable or after T.
- OTHERWISE it SHALL return exactly `{"number", "state"}`, with `state` `"closed"` only when
  `closed_at` parses and is `<= until`, else `"open"`. `title` and `due_on` are never carried.

### Pagination (`_get_all`, `_issue_timeline`, `_collect_open_at`)

- `_get_all` SHALL append `page=` to the given URL (respecting an existing query string), stop on
  the first empty or short (`< per_page`) page or at `max_pages`, and return `(items, truncated)`
  where `truncated` is true only when the cap was reached **with a full final page**. Request errors
  SHALL propagate.
- `_issue_timeline` SHALL return `(events, truncated)` with `truncated` true whenever the timeline is
  not known to be complete: a missing `number`, any fetch error (including on the first page), or the
  page cap reached with a full final page. An **unavailable** timeline SHALL be `([], True)`, not
  `([], False)` — an empty timeline omits labels safely but reads as "title never changed", which
  would leak a post-T rename. Only a fetched, genuinely event-less timeline SHALL be `([], False)`.
- `_collect_open_at` SHALL walk issues created-descending, keep those `_item_open_at`, drop those
  whose `_issue_record_at` returns `None`, and route each into `open_prs` when the raw item carries
  `pull_request`, else `open_issues`. It SHALL stop on a short page (complete) or set `truncated` at
  the cap.

### Fetch (`fetch_context_at`)

- The token SHALL default to `GITHUB_TOKEN` from the environment when not passed.
- WHEN issue pagination is truncated THEN `open_issues` and `open_prs` SHALL both be emptied — a
  partial backlog violates the knowable-at-T contract, so nothing is served rather than a subset.
  Likewise a truncated milestone or release list SHALL yield `[]` for that list.
- Releases SHALL be kept only when `published_at` parses and is `<= until` (drafts carry no
  `published_at` and are excluded), and SHALL carry only `{"tag", "published_at"}` — never `name`.
- The result SHALL carry `repo`, `open_issues`, `open_prs`, `milestones`, `releases`, `_source`
  (`"github-api"`), `_knowable_until` (`until.isoformat()`), and the three truncation flags. It
  SHALL NOT carry a `labels` catalog.

### Enrichment (`enrich_context`)

- WHEN `context` is not a dict THEN it SHALL log a warning and return the input **unchanged**.
- WHEN the remote does not resolve to an owner/repo, or the context has no usable
  `frozen_at.date`, THEN it SHALL return the context unchanged (no request made).
- OTHERWISE it SHALL return a **copy** of the context with `repo`, `open_issues`, `open_prs`,
  `milestones`, `releases` and every present `_ENRICH_META_KEYS` entry overwritten from the fetched
  result, plus `_github_enriched` `True`. `labels` SHALL never be merged.
- IF anything raises (offline, rate limit, private repo, the naive-timestamp `TypeError` above) THEN
  it SHALL return a copy of the original context annotated with `_github_error` — the exception text
  truncated to 200 characters — and SHALL NOT raise.
- `_frozen_at_date` SHALL yield `None` for a non-dict context, a non-dict `frozen_at`, or an
  unusable `date`.

### Backlog gate (`open_issues_from_context`)

- It SHALL return `None` for a non-dict context, and `None` WHEN `_issues_truncated` **is the literal
  `True`** — a partial backlog would produce a misleading `backlog_recall`.
- The check is an identity test, not truthiness: a `_issues_truncated` of `"yes"` or `1` SHALL NOT
  suppress the backlog. OTHERWISE it SHALL return `context.get("open_issues")` verbatim (including
  `None` when the key is absent).

## Out of scope

- HTTP transport itself (`_get`'s headers, auth and error surface) beyond the pagination and
  error-propagation rules above; no test performs network I/O.
- `audit_context` (Spec 022) and the git-only builders in `freeze.py`.
- Correcting any of the divergences catalogued above; each is a behavior change and belongs in its
  own issue.

## Verification

- `tests/test_spec_081_github_context.py` exercises each EARS block above with **literal** expected
  values against in-memory fixtures, monkeypatching `_get` where a page walk is under test so no
  test touches the network.
- Broader behavioral coverage remains in `tests/test_github_context.py`.
