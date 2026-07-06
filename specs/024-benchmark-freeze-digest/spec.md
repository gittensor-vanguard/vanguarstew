# Spec 024 — the freeze digest (`freeze_digest`)

- **Status:** draft (SDD Phase 1 — Specify)
- **Owner:** benchmark
- **Issue:** #858
- **Constitution:** [`AGENTS.md`](../../AGENTS.md) → *Benchmark integrity (M1–M3)*
- **Methodology:** [`blog/spec-driven-development.md`](../../blog/spec-driven-development.md)

This spec makes the **existing, implicit** `benchmark/freeze_digest.py::freeze_digest` contract
explicit. It describes as-built behavior; it introduces **no product code change**. The digest is
a stable fingerprint of *which frozen repos/commits a run actually covered*, so two runs
(candidate vs baseline, or repeatability re-runs) can be checked for covering the same ground.

## Why

Comparing two runs is only meaningful if they scored the same frozen repos at the same commits.
`freeze_digest` extracts that identity set in a **stable, order-independent** form so a diff of
two digests is deterministic and robust to malformed artifact content — behavior that must be
written down.

## User stories

1. **As CI / a maintainer**, I get a stable digest of `(partition, repo, freeze_commit)` for a
   run — so I can confirm two artifacts covered the same repos/commits before trusting a
   comparison.
2. **As a reviewer**, the identity-resolution and sorting rules are written down — so a change to
   `freeze_digest.py` is checked against them.

## Acceptance criteria (EARS)

### Result shape

- `freeze_digest(artifact)` SHALL return `{"kind", "entries", "count"}` where `kind` is the
  artifact classification, `entries` is a list of `{"partition", "repo", "freeze_commit"}`, and
  `count == len(entries)`.

### Row collection per artifact kind

- `kind` SHALL be `artifact_kind(artifact)`: `generalization` (both `tuned` and `held_out` are
  objects and `generalization_gap` is present), `multi` (a top-level `per_repo`), `single`
  (otherwise), or `invalid` (empty / non-dict).
- WHEN `generalization` THE entries SHALL be collected from `tuned.per_repo` and
  `held_out.per_repo`, each row's `partition` set to `"tuned"` / `"held_out"`.
- WHEN `multi` THE entries SHALL be collected from the top-level `per_repo`, `partition` `"multi"`.
- WHEN `single` or `invalid` THE entries SHALL be empty (`count == 0`) — a single-repo/unusable
  artifact carries no per-repo identity rows.

### Identity resolution

- `repo` SHALL be the first non-empty of `repo_path`, `url`, `repo`, `name`, `repo_name`; else
  the row's `freeze_commit` shortened to 10 chars; else a stable key from the row's sorted keys.
- `freeze_commit` SHALL be the row's `freeze_commit` when it is a non-empty string, else `None`.

### Determinism & robustness

- `entries` SHALL be sorted by `(partition, repo, freeze_commit or "")`, so the digest is
  independent of input row order.
- IF `per_repo` is not a list THEN it SHALL be treated as empty (logged, not raised); a non-dict
  row SHALL be skipped — per `AGENTS.md` → *Benchmark integrity*.
- IF `artifact` is not a dict THEN the digest SHALL be `{"kind": "invalid", "entries": [],
  "count": 0}` (no crash).

### Headline

- `freeze_digest_headline(summary)` SHALL render `"freeze digest: {kind} with {count} entr(y|ies)"`
  (singular for a count of 1), tolerating a missing/malformed `summary` (`kind` → `"unknown"`,
  `count` → `"n/a"`).

## Out of scope

- `artifact_kind` itself (owned by `benchmark/comparability.py` / its own spec) — this spec relies
  on its classification, not its internals.
- How artifacts are produced (`run_replay`) and how digests are *compared* downstream.

## Verification

Ships `tests/test_spec_024_freeze_digest.py`, asserting: the result shape; the `generalization`,
`multi`, `single`, and `invalid`/non-dict paths; the `repo` key preference order and the
`freeze_commit` string/`None` rule; sort determinism (shuffled input → identical digest); non-list
`per_repo` and non-dict rows skipped without crashing; and the headline singular/plural + malformed
cases. Every claim was cross-checked against the code. The spec changes no product code.
