# Spec 078 — knowable-at-T GitHub context contract

**Module:** `benchmark/github_context.py`
**Status:** Accepted (characterization + bug fixes)
**Tests:** `tests/test_github_context.py`
**Issue:** #1993

## Purpose

`freeze.py` gives the benchmark git-only context. `github_context.py` is where the maintainer's
real working surface — open issues/PRs, their labels and titles, milestones, releases — gets added
back in without leaking anything from after the freeze time T. Spec 003 states the leakage
principle and Spec 022 pins `audit_context` (the *detector* that checks a context for leakage);
nothing pinned the **producer**. A leak here does not crash — it quietly makes the agent's scored
context better than it should be, and every downstream score inherits it silently.

This spec documents the module's field-stability policy as executable acceptance criteria, and
fixes three places where the as-built behavior diverged from what the docstrings already
promised (see "Bug fixes" below). No other behavior changes.

## Definitions

- **Open at T.** An issue/PR counts as open at `until` iff `created_at <= until` and
  (`closed_at` is null or `closed_at > until`) — inclusive on both boundaries.
- **Derived-as-of-T fields.** Membership (open/closed), labels, and title are reconstructed from
  timeline events relative to T rather than copied from the live REST snapshot.
- **Fail-closed reconstruction.** When a timeline can't be verified complete (unavailable or
  truncated by the page cap), labels and title are *both* omitted (`*_as_of_t=False`) rather than
  trusting a partial replay that could actively contradict the truth.
- **Discard-on-truncation.** When issue/milestone/release pagination hits its page cap before
  exhausting history, the whole list is discarded (`[]`), not served partially — a partial backlog
  would misrepresent what was knowable at T.

## Bug fixes

Three places where the as-built behavior was narrower or wider than the docstring already
promised. All three are fixed here, each with a direct regression test:

1. **`parse_owner_repo` was not GitHub-specific.** A remote with no `github.com/` (e.g.
   `https://gitlab.com/o/r`, or an ssh remote to a different host) fell through to a bare `/`
   split and returned a truthy `(owner, repo)` pair anyway — `enrich_context` would then query
   `api.github.com` against the wrong namespace before degrading through its catch-all. Fixed:
   a non-GitHub remote (https or ssh) now returns `(None, None)` directly.
2. **The `.git` suffix strip was end-anchored**, so a remote with a trailing slash
   (`https://github.com/o/r.git/`) kept `.git` as part of the repo name (`"r.git"`). Fixed: the
   trailing slash is stripped before the `.git` check.
3. **A naive (offset-less) timestamp crashed instead of degrading.** `_parse_dt` is documented to
   return `None` "when the input is unusable", and did for a non-string or unparsable string —
   but `"2020-06-01T00:00:00"` parses into a *naive* `datetime`, and every caller compares it
   against a timezone-aware `until`, raising `TypeError: can't compare offset-naive and
   offset-aware datetimes`. That propagated through `fetch_context_at` into `enrich_context`'s
   catch-all, silently dropping the entire GitHub surface for the run. Fixed: `_parse_dt` now
   treats a naive result as unusable and returns `None`, matching its documented contract.

## Acceptance criteria (EARS)

- **AC-1 — Remote parsing is GitHub-only.** `parse_owner_repo` SHALL return `(None, None)` for
  any remote whose host is not `github.com`, for a non-string input, and when fewer than two
  path segments remain after stripping a `git@github.com:`/`.../github.com/` prefix.
- **AC-2 — `.git`/trailing-slash normalization.** `parse_owner_repo` SHALL strip a trailing `/`
  before stripping a trailing `.git`, so `.../o/r.git`, `.../o/r.git/`, and `.../o/r/` all
  resolve to repo `r`.
- **AC-3 — Subpaths ignored.** `parse_owner_repo` SHALL use only the first two non-empty path
  segments after `github.com/`, so `/tree/`, `/blob/`, or other subpaths do not affect the result.
- **AC-4 — Timestamp parsing degrades, never raises.** `_parse_dt` SHALL return `None` for a
  non-string, empty, unparsable, or **naive** (offset-less) value, and a timezone-aware
  `datetime` otherwise.
- **AC-5 — Open-at-T membership is inclusive both ends.** `_item_open_at` SHALL treat an item as
  open at `until` iff `created_at <= until` and (`closed_at` is absent/unparsable or
  `closed_at > until`); a missing/naive `created_at` SHALL exclude the item rather than raise.
- **AC-6 — Timeline-based close correction.** `_closed_at_from_timeline` SHALL replay
  `closed`/`reopened` timeline events up to `until` in chronological order (regardless of the
  order they arrive in) and return whether the item was actually closed at `until`, correcting a
  live-snapshot false positive for an item closed and reopened more than once; it SHALL return
  `False` (no correction) when the timeline carries no such event.
- **AC-7 — Labels fail closed.** `_labels_at` SHALL reconstruct the as-of-T label set from
  `labeled`/`unlabeled` events at or before `until`, returning `None` (not `[]`) when no usable
  label event exists — `None` and `[]` are not interchangeable: the caller reads `None` as
  "not reconstructable, omit" and `[]` as "reconstructed, genuinely unlabelled".
- **AC-8 — Title fail closed only on incomplete timelines.** `_title_at` SHALL return the title
  immediately before the earliest post-T rename when the (complete) timeline shows one, the live
  title unchanged when the complete timeline shows no renames at all, and SHALL NOT be called by
  `_issue_record_at` when the timeline is truncated (the caller omits the title instead).
- **AC-9 — Truncated timeline omits both labels and title together.** `_issue_record_at` SHALL
  set `labels_as_of_t=False` and `title_as_of_t=False` together whenever the item's timeline is
  truncated or unavailable, never just one of the pair.
- **AC-10 — An unavailable timeline reports truncated, not empty.** `_issue_timeline` SHALL
  report `([], True)` (not `([], False)`) when nothing could be fetched at all (missing number or
  a first-page error) — an empty-but-*fetched* timeline is the only case that reports
  `([], False)`, because that is the only case where "no rename events" safely means "title never
  changed".
- **AC-11 — Milestone state is derived as of T, other fields omitted.** `_milestone_at` SHALL
  return `None` for a milestone created after `until`; otherwise `state` SHALL be `"closed"` only
  when `closed_at <= until`, and the record SHALL carry only `number`/`state` (no live `due_on` or
  `title`, which carry no as-of-T reconstruction path).
- **AC-12 — Releases filtered by publish date, name omitted.** `fetch_context_at` SHALL include
  only releases with `published_at <= until` (excluding drafts, which have no `published_at`),
  keeping only `tag`/`published_at` (never the editable `name`).
- **AC-13 — Pagination cap discards, not truncates, the list.** `fetch_context_at` SHALL empty
  `open_issues`/`open_prs` (via `_issues_truncated`), `milestones` (via `_milestones_truncated`),
  and `releases` (via `_releases_truncated`) outright when their respective pagination hit its
  page cap before exhausting history — never serving a partial list.
- **AC-14 — Backlog gate checks the flag by identity.** `open_issues_from_context` SHALL return
  `None` only when `_issues_truncated` **is** the literal `True` (not merely truthy), and the
  `open_issues` list otherwise.
- **AC-15 — Enrichment degrades to git-only on any failure.** `enrich_context` SHALL return the
  input context annotated with `_github_error` (and no GitHub fields merged in) when remote
  parsing, date parsing, or the fetch itself raises or yields no usable owner/repo/`until`; it
  SHALL return a non-dict `context` unchanged (with a logged warning).

## Out of scope

- `audit_context` (the leakage detector, Spec 022) and the leakage principle itself (Spec 003).
- HTTP transport / retry behavior of `_get` and `_get_all` beyond what's stated above.
- Tuning `DEFAULT_MAX_ISSUE_PAGES` / `DEFAULT_MAX_LIST_PAGES` or any other default.

## Verification

`tests/test_github_context.py` exercises every AC above with in-memory fixtures — no network:
the three fixes get direct regression tests (`test_parse_owner_repo_rejects_non_github_remotes`,
`test_parse_owner_repo_strips_git_suffix_before_trailing_slash`,
`test_parse_dt_rejects_naive_timestamps`, plus `test_item_open_at_does_not_raise_on_naive_timestamps`
and `test_milestone_at_does_not_raise_on_naive_timestamps` pinning that the fix propagates through
the callers that used to raise) — alongside the existing open-at-T, timeline-correction,
label/title reconstruction, truncation, and enrichment-degradation coverage.
