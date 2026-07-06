# Spec 003 — knowable-at-T / anti-leakage integrity

- **Status:** draft (SDD Phase 1 — Specify)
- **Owner:** benchmark
- **Issue:** #509
- **Constitution:** [`AGENTS.md`](../../AGENTS.md) → *Benchmark integrity (M1–M3)*
- **Methodology:** [`blog/spec-driven-development.md`](../../blog/spec-driven-development.md)
- **Related:** [`specs/002-scoring-anchor`](../002-scoring-anchor/spec.md) (scores over this frozen context)

This spec makes the **existing, implicit** leakage-integrity contract explicit. It describes the
as-built behavior of `benchmark/freeze.py`, `benchmark/github_context.py`, and
`benchmark/leakage.py`; it introduces **no behavior change**. This is the contract the whole
benchmark's *trust* rests on — an agent must be graded on what a maintainer could actually have
known at freeze time T, never on the future.

## Why

The benchmark replays real GitHub history: the revealed window is the answer key. If any
future-looking signal survives into the frozen context the agent reasons over, the score is
compromised. "Knowable at T" is therefore a hard, testable boundary, not a best-effort — and it
must be written down so every freeze/context/leakage change is reviewed against it.

## User stories

1. **As the validator**, I freeze a repo at commit T so the agent sees only state that existed
   at T — so an agent can't "predict" what it was actually shown.
2. **As an agent developer**, I trust that nothing in the context leaks the future — so a strong
   score reflects genuine maintainer foresight, not leakage.
3. **As a reviewer**, every change to freeze/context/leakage is checked against this contract at
   the SDD phase boundary — so the trust boundary can't erode silently.

## Acceptance criteria (EARS)

### Knowable-at-T inclusion

- The frozen context SHALL include only commits/issues/PRs/releases that existed at T — items
  `created_at`/`published_at` `<= T`; nothing created or published after T SHALL appear.
- An issue/PR SHALL count as "open at T" only if it was created by T and not yet closed by T
  (`_item_open_at`).
- Release tags SHALL be enumerated by creation date and filtered to those created `<= T` — a
  tag created after T (even on a commit reachable at T) SHALL be dropped, and ordering SHALL be
  chronological, not git's default lexicographic refname order.

### As-of-T reconstruction of mutable fields

- IF a GitHub field is mutable and the live REST value would reflect the present THEN it SHALL
  be reconstructed as-of-T rather than copied live:
  - milestone state SHALL be derived from `created_at`/`closed_at` (`"closed"` only if closed by
    T) — `_milestone_at`;
  - issue/PR label membership SHALL be replayed from the item's timeline `labeled`/`unlabeled`
    events up to T (`_labels_at`); WHEN the timeline is unavailable, incomplete, or truncated
    THE labels SHALL be **omitted** (fail-closed), never the present-day set.
- A non-list / malformed timeline or context field SHALL degrade safely (coerce/guard), not
  crash the freeze — per `AGENTS.md` → *Benchmark integrity*.

### Forward-reference scrubbing

- Free-text fields (commit subjects, issue/PR titles, README excerpt, release names/tags) SHALL
  have forward-references neutralized: issue/PR back-references (`#N` → `#ref`), GitHub deep
  links (issues/pull/commit/compare/…) → masked, and raw commit SHAs → `<sha>`.
- A SHA-shaped token SHALL be masked only WHEN it contains a hex letter (`a`–`f`); an all-numeric
  token (a count, year, version part) SHALL be preserved (`_looks_like_sha`).

### Freeze-point selection & isolation

- Freeze-point selection SHALL prefer recent, deterministically-rotated points so answers aren't
  reused, and SHALL require no network beyond the managed-inference proxy.
- Held-out repos SHALL be reserved for a separate generalization pass, not the tuned pass.

## Out of scope

- The **scoring** of the agent's output over this context (that is `specs/002-scoring-anchor`).
- The **agent** entrypoint/contract (`specs/001-solve-contract`).
- Curating the vetted repo set itself (config/loader) — a separate concern; this spec governs
  the freeze/leakage behavior applied to whatever repo is chosen.

## Verification

Already exercised deterministically offline by `tests/test_github_context.py` (open-at-T
filtering, milestone/label as-of-T reconstruction, timeline fallback), `tests/test_freeze.py`
(chronological/`<= T` tag selection), and `tests/test_leakage.py` (ref/link/SHA scrubbing,
numeric-token preservation). This spec adds no code and does not require new tests.
