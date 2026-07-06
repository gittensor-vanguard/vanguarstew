# Spec 005 — repo-set / curation contract

- **Status:** draft (SDD Phase 1 — Specify)
- **Owner:** benchmark
- **Issue:** #628
- **Constitution:** [`AGENTS.md`](../../AGENTS.md) → *Benchmark integrity (M1–M3)*
- **Methodology:** [`blog/spec-driven-development.md`](../../blog/spec-driven-development.md)
- **Related:** [`specs/003-leakage-integrity`](../003-leakage-integrity/spec.md) (freezes whatever repo this set selects)

This spec makes the **existing, implicit** repo-set / curation contract explicit. It describes
the as-built behavior of `benchmark/repo_set.py`; it introduces **no behavior change**. The
corpus is the population an agent is scored over, so a malformed set must fail **loudly at load**
rather than silently erode the benchmark. This completes the foundational contract set for M5.

## Why

A typo in a repo-set config (an unknown field, a reversed date window) that loads "successfully"
but yields zero tasks quietly shrinks the curated, leakage-safe corpus — corrupting scores
without any error. The loader therefore validates strictly and fails fast; that contract must be
written down so the corpus stays trustworthy.

## User stories

1. **As the validator**, a bad repo-set config is rejected at load with a precise message — so I
   never score against a silently-degraded corpus.
2. **As a curator**, I get fail-fast feedback on field typos, mistyped hints, and impossible date
   windows — so the vetted set stays intact.
3. **As a reviewer**, the loader's strictness and the tuned/held-out split are written down — so
   changes to `repo_set.py` are checked against them.

## Acceptance criteria (EARS)

### Strict loading

- `load_repo_set(path)` SHALL require an explicit `path` (no implicit default) and SHALL raise
  `RepoSetError` on any problem; `validate_repo_set(data)` SHALL validate an already-parsed object.
- The top level SHALL require a non-empty `repos` list; `name`/`description`/`strategy` are
  optional strings; ANY other top-level key SHALL be a `RepoSetError` (not silently dropped).
- Each entry SHALL require a non-empty `name` (unique — duplicates rejected) and non-empty
  `source`; `tier` SHALL be one of `("recent", "obscure")`; `held_out` SHALL be a boolean
  (default `False`); `notes` SHALL be a string; ANY unknown entry key SHALL be a `RepoSetError`.

### Freeze-window hints (typed + bounded)

- `freeze_window` SHALL be an object whose keys are limited to `after`/`before` (str),
  `recent_bias` (bool), `rotation_seed`/`min_history` (int, **not** bool).
- `after`/`before` SHALL be non-empty AND parse as an ISO date (`YYYY-MM-DD`); a non-empty but
  unparseable bound SHALL be rejected **at load**, not deferred to an opaque taskgen crash.
- `min_history` SHALL be `>= 1`.
- **Reversed bounds SHALL be rejected:** WHEN both `after` and `before` are given, `after` SHALL
  be on or before `before` — a window that can contain no commit (silently zero tasks, repo
  quietly dropped) is a `RepoSetError`.

### Partitioning & mapping

- A `RepoSet` SHALL expose `tuned()` (entries with `held_out == False`), `held_out()`, `by_tier`,
  and `partition("tuned"|"held_out"|"all")`; an unknown partition name SHALL raise.
- Held-out repos SHALL be reserved for a separate generalization pass — never mixed into the
  tuned pass (per `AGENTS.md` → *Benchmark integrity*).
- `replay_kwargs(entry)` SHALL map only the present `freeze_window` hints onto `run_replay`
  keyword args (`recent_bias`, `rotation_seed`, `min_history`, `after`, `before`).

## Out of scope

- The **freeze / leakage** behavior applied to a selected repo — that is
  [`specs/003-leakage-integrity`](../003-leakage-integrity/spec.md).
- The *contents* of the curated set (which specific repos) and task generation over them.

## Verification

Ships `tests/test_spec_005_repo_set.py`, asserting the criteria against the loader: a valid config
yields the correct tuned/held-out split; unknown top-level and entry keys, a missing/blank
`name`/`source`, and a bad `tier` are each rejected; `freeze_window` type checks (bool-not-int),
an unparseable `after`, a reversed `after > before`, and `min_history < 1` all raise
`RepoSetError`; and `replay_kwargs` maps hints through. Complements `tests/test_repo_set.py`. The
spec changes no product code.
