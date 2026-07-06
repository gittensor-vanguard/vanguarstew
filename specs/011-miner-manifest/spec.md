# Spec 011 — the miner scored-surface manifest

- **Status:** draft (SDD Phase 1 — Specify)
- **Owner:** agent
- **Issue:** #726
- **Constitution:** [`AGENTS.md`](../../AGENTS.md) → *Agent contract (M0)* · *Scoring (gittensor SN74)*
- **Methodology:** [`blog/spec-driven-development.md`](../../blog/spec-driven-development.md)
- **Related:** [`specs/001-solve-contract`](../001-solve-contract/spec.md) (entrypoint the manifest names)

This spec makes the **existing, implicit** miner manifest contract explicit. It describes the
as-built policy encoded in `vanguarstew_agent_files.json`; it introduces **no behavior change**.
Only files listed in the manifest are treated as the scored agent surface — so the manifest's
shape, caps, and on-disk presence must be written down and verified.

## Why

Miners edit the agent implementation but must not expand the scored surface silently (adding
harness files, benchmark code, or undeclared modules). The manifest is the authoritative list of
what a submission may change and what CI scores. Making that contract explicit lets reviewers
check manifest edits against intent and gives M5 a reviewable definition of the editable seam.

## User stories

1. **As the validator**, I know exactly which paths constitute the scored agent surface — so
   changes outside the manifest never affect emission weight.
2. **As a miner**, I know the declared entrypoint and file cap — so I implement inside the
   allowed package without accidentally editing unscored infrastructure.
3. **As a reviewer**, manifest structure and presence rules are written down — so a manifest PR
   is checked against the spec.

## Acceptance criteria (EARS)

### Manifest document shape

- `vanguarstew_agent_files.json` SHALL be a JSON object containing at least the keys:
  `entrypoint`, `entrypoint_symbol`, `files`, and `max_files`.
- `entrypoint` SHALL name the single agent entry module (`agent.py`).
- `entrypoint_symbol` SHALL name the single callable entrypoint (`solve`).
- `files` SHALL be a non-empty list of repository-relative path strings using forward slashes.
- `max_files` SHALL be a positive integer cap on the length of `files`.

### On-disk presence and hygiene

- Every path in `files` SHALL exist as a file at the repository root.
- `files` SHALL contain no duplicate paths.
- No path in `files` SHALL be prefixed with `benchmark/` (harness code is not miner-editable).
- The maintainer-assist module `agent/review.py` SHALL NOT appear in `files` (it is not part of
  the scored replay surface).

### Entrypoint linkage

- The file named by `entrypoint` SHALL define a callable `solve` (the symbol named by
  `entrypoint_symbol`).
- The manifest's `files` list SHALL include `entrypoint` and every module on the import path the
  entrypoint uses for the scored agent steps (`agent/` package modules referenced by the
  as-built `agent.py` orchestration).

### File cap

- The number of entries in `files` SHALL be less than or equal to `max_files`.

### Robustness (per constitution)

- IF the manifest is malformed JSON or missing required keys THEN the verifying tests SHALL fail
  with a clear assertion — the manifest must remain machine-checkable in CI.

## Out of scope

- **Runtime enforcement** inside the benchmark harness (this spec documents policy; harness wiring
  is separate).
- **Which agent steps are scored for quality** — the benchmark measures decision quality; this
  spec fixes only the editable file list.
- Changing manifest contents — manifest edits follow review in their own PRs; this spec documents
  the as-built surface only.

## Verification

- `tests/test_spec_011_manifest.py` (this PR) exercises each EARS block above against the real
  `vanguarstew_agent_files.json` and repository tree.
- Broader smoke coverage of `solve()` remains in `tests/test_smoke.py`.
