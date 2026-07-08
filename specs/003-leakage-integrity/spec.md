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

### The freeze point T (exact)

- **T SHALL be the freeze commit's committer timestamp** — `git show -s --format=%ct <commit>`
  (Unix seconds), not the author timestamp. (Rationale: the author date can predate when a
  commit actually entered the branch's history; the committer date is when it became part of
  the state knowable at the freeze point.) Recent commits are recorded with committer ISO time
  (`%cI`), and every "≤ T" comparison below uses this committer T.

### Knowable-at-T inclusion

- The frozen context SHALL include only commits/issues/PRs/releases that existed at T — items
  `created_at`/`published_at` `<= T`; nothing created or published after T SHALL appear.
- An issue/PR SHALL count as "open at T" only if it was created by T and not yet closed by T
  (`_item_open_at`).
- Release tags SHALL be enumerated by creation date (`--sort=creatordate`) and filtered to those
  whose creator date is `<= T` — a tag created after T (even on a commit reachable at T) SHALL
  be dropped, and ordering SHALL be chronological, not git's default lexicographic refname order.
  - Residual limitation (documented, not a defect): for a **lightweight** tag, git records no
    creation time, so `creatordate` is its target commit's date. That date is `<= T` for any
    reachable commit, so a lightweight tag placed after T on an old commit cannot be detected —
    an accepted, spec-noted limitation, not silent breakage.

### As-of-T reconstruction of mutable fields

- IF a GitHub field is mutable and the live REST value would reflect the present THEN it SHALL
  be reconstructed as-of-T rather than copied live:
  - milestone state SHALL be derived from `created_at`/`closed_at` (`"closed"` only if closed by
    T) — `_milestone_at`;
  - issue/PR label membership SHALL be replayed from the item's timeline `labeled`/`unlabeled`
    events, applied in chronological order for events at/or before T (`_labels_at`).
  - **Partial-data handling (fail-closed):** WHEN the timeline is unavailable, empty, OR
    **truncated** (paged past the fetch cap, so an earlier `labeled`/`unlabeled` may be missing)
    THE labels SHALL be **omitted** with `labels_as_of_t = False` — a partial replay that could
    contradict true as-of-T membership SHALL NEVER be trusted, and the present-day set SHALL
    NEVER be substituted.
  - A non-list / malformed `events` value SHALL be treated as no events (guarded), not crash the
    freeze — per `AGENTS.md` → *Benchmark integrity*.
  - Residual limitation (documented): issue/PR `title` is copied live (present-day) — it may have
    been edited after T; recovering historical titles is out of scope for this contract.

### Forward-reference scrubbing

- Free-text fields (commit subjects, issue/PR titles, README excerpt, release names/tags) SHALL
  have forward-references neutralized: issue/PR back-references (`#N` → `#ref`), GitHub deep
  links (issues/pull/commit/compare/…) → masked, and raw commit SHAs → `<sha>`.
- **SHA detection (exact rule).** A token SHALL be treated as a SHA and masked to `<sha>` only
  when it is a word-bounded run of 7–40 characters, or exactly 64 characters, drawn from
  `[0-9a-f]` (case-insensitive) AND it contains **at least one** hex letter `a`–`f`
  (`_looks_like_sha` = `_SHA.fullmatch` + a hex-letter check). The 7–40 range covers abbreviated
  and full SHA-1 hashes; the exact-64 length covers a full SHA-256 object hash (git has supported
  the SHA-256 object format since 2.29). Consequently:
  - an all-numeric token (a count, year, ID, measurement) SHALL be **preserved** — it is
    technically valid hex but far more likely real content;
  - a token shorter than 7, of length 41–63, or longer than 64 hex chars SHALL NOT be masked
    (the 41–63 gap avoids masking arbitrary long hex-like tokens that are not real hashes);
  - the check is applied per whitespace/word-boundary token, so hex inside a larger word is not
    spuriously masked.

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

This spec ships a dedicated **contract test**, `tests/test_spec_003_leakage.py`, asserting the
non-obvious acceptance criteria directly against the code — proving the implementation satisfies
this spec:

- **freeze point T = committer time:** an annotated tag *created after* T (later tagger date) on
  a commit reachable at T is dropped from `releases`, while a tag at/before T is kept;
- **timeline partial data fails closed:** a truncated timeline yields `labels_as_of_t = False`
  and omitted labels (never a partial/present-day set); `_labels_at` returns `None` when only
  post-T events exist;
- **SHA detection (exact rule):** a hex token with a letter is masked when its length is 7–40
  (SHA-1) or exactly 64 (SHA-256), an all-numeric token is preserved, and a token below 7, of
  length 41–63, or above 64 hex chars is not masked;
- **milestone state as-of-T:** a milestone closed after T reads `open` at T.

These complement the broader coverage already in `tests/test_github_context.py`,
`tests/test_freeze.py`, and `tests/test_leakage.py`. The spec changes no product code.
