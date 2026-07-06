# Spec 023 — semver parsing and bump classification (`parse_semver`, `bump_level`)

- **Status:** draft (SDD Phase 1 — Specify)
- **Owner:** benchmark
- **Issue:** #854
- **Constitution:** [`AGENTS.md`](../../AGENTS.md) → *Benchmark integrity (M1–M3)*
- **Methodology:** [`blog/spec-driven-development.md`](../../blog/spec-driven-development.md)
- **Related:** [`specs/002-scoring-anchor`](../002-scoring-anchor/spec.md) (release/bump axes consume these helpers)

This spec makes the **existing, implicit** semver parsing and bump-classification contract explicit.
It describes the as-built behavior of `benchmark/score.py::parse_semver` and `bump_level`; it
introduces **no behavior change**. Release/bump scoring keys off tolerant semver extraction and
forward-bump classification — those rules must be written down and verified.

## Why

An LLM may emit a non-string `base_version` or embed versions inside subject lines. `parse_semver`
and `bump_level` are the single normalizers for those inputs; making their contract explicit lets
reviewers check scoring changes against intent and guards malformed replay artifacts.

## User stories

1. **As a benchmark maintainer**, I know semver parsing tolerates a leading `v`, a missing patch,
   and ignores pre-release suffixes — so release subjects parse consistently.
2. **As a reviewer**, bump classification rules (forward-only, canonical levels) are written down
   — so `bump_actual` changes are checked against the spec.

## Constants

- `BUMP_LEVELS` — the canonical bump-level strings returned by `bump_level`:
  `("major", "minor", "patch")`. No other return value is valid.

## Acceptance criteria (EARS)

### `parse_semver` — input guard

- `parse_semver(text)` SHALL accept a `str` payload containing zero or one semver-looking token.
- WHEN `text` is not a `str` (e.g. `None`, `int`, `list`, `dict`) THEN the function SHALL return
  `None` (not raise).

### `parse_semver` — token extraction

- The function SHALL locate the **first** semver core in `text` matching `major.minor[.patch]`.
- WHEN the token has a leading `v` or `V` THEN it SHALL be stripped before parsing.
- WHEN the patch component is absent (`"1.2"` or `"v1.2"`) THEN the patch SHALL be `0`.
- WHEN a pre-release or build suffix follows the core (`-rc1`, `+build`) THEN the suffix SHALL be
  ignored and only the core components returned.
- WHEN no version-looking token is present THEN the function SHALL return `None`.

### `parse_semver` — output shape

- On success the function SHALL return a 3-tuple of non-negative `int` values
  `(major, minor, patch)`.
- The function SHALL NOT mutate its input string.

### `bump_level` — input guard

- `bump_level(old, new)` SHALL accept two semver tuples `(major, minor, patch)`.
- WHEN either argument is not a `tuple` THEN the function SHALL return `None` (not raise).
- WHEN either tuple has fewer than three elements THEN the function SHALL return `None`.
- WHEN either tuple is empty/falsy (`()`) THEN the function SHALL return `None`.

### `bump_level` — forward bump only

- The function SHALL return `None` when `new <= old` (no forward bump), including when
  `new == old`.
- WHEN `new` is strictly greater than `old` on the semver ordering THEN the function SHALL
  classify the delta.

### `bump_level` — classification

- WHEN `new[0] != old[0]` THEN the function SHALL return `"major"`.
- WHEN `new[0] == old[0]` and `new[1] != old[1]` THEN the function SHALL return `"minor"`.
- WHEN only `new[2] != old[2]` (major and minor unchanged) THEN the function SHALL return
  `"patch"`.
- Every non-`None` return value SHALL be one of `BUMP_LEVELS`.

### Pure evaluation

- Both functions SHALL perform no I/O and SHALL NOT depend on mutable global state.

## Out of scope

- `_semver_from_release_subject` disambiguation when multiple versions appear in one subject —
  separate release-subject spec territory.
- Changing parse or bump semantics — code changes follow the SDD loop in their own PRs.

## Verification

- `tests/test_spec_023_semver_parse.py` (this PR) exercises each EARS block above.
- Broader anchor coverage remains in `tests/test_score.py`.
