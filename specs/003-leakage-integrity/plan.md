# Plan 003 — knowable-at-T / anti-leakage integrity

- **Status:** draft (SDD Phase 2 — Plan)
- **Spec:** [`spec.md`](./spec.md) · **Issue:** #509

How the [spec](./spec.md) maps onto the code as-built. No new code is proposed; this records the
contract surface so future freeze/context/leakage changes are reviewed against a written plan.

## Architecture

Three layers produce and sanitize the frozen-at-T context:

```
freeze.build_context(repo, commit)                 # git-only knowable-at-T snapshot
  ├─ recent commits (log up to T)
  ├─ tags-as-releases: git tag --merged --sort=creatordate, dropped when creatordate > T
  └─ README excerpt
enrich_context(context, ...) → github_context.fetch_context_at(owner, repo, until=T)
  ├─ _item_open_at(item, T)                         # created ≤ T and not closed by T
  ├─ _issue_record_at → _labels_at(timeline, T)     # labels replayed as-of-T; omit if truncated/unavailable
  ├─ _milestone_at(milestone, T)                    # state from created/closed_at
  ├─ _timeline_events(...) / _get_all(...)          # non-list-safe, paginated
  └─ releases filtered by published_at ≤ T
leakage.scrub_context(context)                      # neutralize forward references in free text
  └─ strip_forward_refs: _GH_LINK→mask, #N→#ref, SHA→<sha> (only if _looks_like_sha)
```

## Data model

### The freeze boundary

- **T** = the freeze commit's time. Every inclusion/reconstruction test is relative to T.
- **Inclusion:** `created_at`/`published_at ≤ T`; open-at-T = created ≤ T and not closed ≤ T.
- **As-of-T fields:** milestone `state`; issue/PR `labels` (+ a per-item flag when reconstructed
  vs omitted). Fail-closed: unknown ⇒ omit, never leak the present.

### Scrubbing rules

| Pattern | Action | Note |
| ------- | ------ | ---- |
| `#N` | → `#ref` | issue/PR back-reference |
| `github.com/.../{issues,pull,commit,compare,...}/…` | → masked | forward deep-link |
| 7–40 or exactly-64 char hex with an `a`–`f` letter | → `<sha>` | real SHA-1 / SHA-256 |
| all-numeric hex token | preserved | count/year/version — not a SHA (`_looks_like_sha`) |

## Contract surface (functions this spec pins)

- `benchmark/freeze.py`: `build_context` (tag creatordate + `> T` drop), `write_frozen`.
- `benchmark/github_context.py`: `fetch_context_at`, `_item_open_at`, `_issue_record_at`,
  `_labels_at`, `_milestone_at`, `_timeline_events`, `_get_all`, `enrich_context`.
- `benchmark/leakage.py`: `strip_forward_refs`, `_looks_like_sha`, `scrub_context`,
  `_scrub_titles`/`_scrub_list`.

## Verification strategy

Deterministic + offline. Covered by `tests/test_github_context.py`, `tests/test_freeze.py`, and
`tests/test_leakage.py`. A future task MAY add a boundary-level property test (nothing with a
timestamp `> T` ever appears in a frozen context); tracked separately, not part of this
docs-only change.

## Out of scope for this plan

Changing any freeze/context/leakage behavior, or the repo-set selection. Code changes against
this contract follow the SDD loop (Tasks → Implement) in their own specs/PRs.
