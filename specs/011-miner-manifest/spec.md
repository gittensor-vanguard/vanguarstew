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
   is checked against the spec, and the check itself can't silently drift from the as-built
   `agent.py` import graph.

## Acceptance criteria (EARS)

### Manifest document shape

- `vanguarstew_agent_files.json` SHALL be a JSON object.
- It SHALL contain the keys `entrypoint` (string), `entrypoint_symbol` (string), `files`
  (non-empty list of strings), and `max_files` (positive integer, not a boolean).
- `entrypoint` SHALL name the single agent entry module (`agent.py`).
- `entrypoint_symbol` SHALL name the single callable entrypoint (`solve`).
- Every path in `files` SHALL be a repository-relative path string using forward slashes, with
  no leading `/`.

### On-disk presence and hygiene

- Every path in `files` SHALL exist as a file at the repository root.
- `files` SHALL contain no duplicate paths.

### Scored-surface confinement (harness isolation)

- Every path in `files` SHALL be either the declared `entrypoint` itself or a path under the
  `agent/` package (i.e. `agent/<name>`). This excludes `benchmark/`, `scripts/`, `tests/`,
  `specs/`, `docs/`, `tools/`, `blog/`, `docker/`, packaging files, and any other top-level
  directory equally, present or future — the rule is "inside the named agent surface," not an
  enumerated blocklist of harness directories.
- The maintainer-assist module `agent/review.py` SHALL NOT appear in `files` (it is a
  maintainer-assist CLI path, not part of the scored replay surface).

### Entrypoint linkage (import-graph derived, not enumerated)

- The file named by `entrypoint` SHALL define a callable named `entrypoint_symbol`.
- Starting from `entrypoint` and following only same-package (`agent.*`) imports transitively —
  including every package `__init__.py` implicitly executed along the way — the full set of
  `agent/` modules reachable SHALL be a subset of `files`. This closure is computed by parsing
  the actual import statements (not a fixed list), so the check tracks `agent.py`'s real
  dependencies as they evolve and cannot silently go stale.
- Imports outside the `agent` package (stdlib, or harness-side helpers such as
  `benchmark.score` that `agent/decider.py` reads from) are not part of the miner-editable
  surface and are intentionally excluded from this closure.

### File cap

- The number of entries in `files` SHALL be less than or equal to `max_files`.

### Robustness (per constitution)

- IF the manifest is malformed JSON or missing required keys THEN the verifying tests SHALL fail
  with a clear assertion — the manifest must remain machine-checkable in CI.

## Out of scope

- **Runtime enforcement** inside the benchmark harness (this spec documents policy; harness
  wiring is separate).
- **Which agent steps are scored for quality** — the benchmark measures decision quality; this
  spec fixes only the editable file list.
- Changing manifest contents — manifest edits follow review in their own PRs; this spec
  documents the as-built surface only.

## Verification

- `tests/test_spec_011_manifest.py` (this PR) exercises each EARS block above against the real
  `vanguarstew_agent_files.json` and repository tree, deriving the entrypoint linkage check from
  `agent.py`'s actual import graph via `ast` rather than a hardcoded module list.
- Broader smoke coverage of `solve()` remains in `tests/test_smoke.py`.
