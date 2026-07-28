# Spec 023 — semver parsing and bump classification (`parse_semver`, `bump_level`)

- **Status:** draft (SDD Phase 1 — Specify)
- **Owner:** benchmark
- **Issue:** #854
- **Constitution:** [`AGENTS.md`](../../AGENTS.md) → *Benchmark integrity (M1–M3)*
- **Methodology:** [`blog/spec-driven-development.md`](../../blog/spec-driven-development.md)
- **Related:** [`specs/002-scoring-anchor`](../002-scoring-anchor/spec.md) (`bump_actual` consumes
  these helpers)

This spec makes the **existing, implicit** semver-parsing and bump-classification contract
explicit. It describes the as-built behavior of `benchmark/score.py::parse_semver` and
`bump_level`; it introduces **no behavior change**. Release/bump scoring depends on tolerant
semver extraction and forward-only bump classification — those rules must be written down and
verified.

## Why

An agent may hand `base_version` straight through from an untrusted or malformed replay artifact,
and revealed commit subjects embed versions in free text. `parse_semver` and `bump_level` are the
two normalizers standing between that raw input and `bump_actual` scoring. Making their contract
explicit lets reviewers check scoring changes against intent and guards against malformed or
non-string inputs reaching the scorer unguarded.

## User stories

1. **As a benchmark maintainer**, I know semver extraction tolerates a leading `v`, a missing
   patch component, and ignores pre-release/build suffixes — so version strings drawn from commit
   subjects or artifact fields parse consistently.
2. **As a reviewer**, the forward-only bump rule and the canonical `major`/`minor`/`patch` output
   vocabulary are written down — so a change to `bump_actual` scoring can be checked against the
   spec rather than re-derived from the implementation.

## Constants

- `_BUMP_LEVELS` — the canonical bump-level strings `bump_level` may return (besides `None`):
  `("major", "minor", "patch")`.

## Acceptance criteria (EARS)

### `parse_semver` — input guard

- `parse_semver(text)` SHALL accept a payload that may or may not contain a semver-looking token.
- WHEN `text` is not a `str` (`None`, `int`, `float`, `bool`, `list`, `dict`, `tuple`) THEN the
  function SHALL return `None` (not raise).

### `parse_semver` — token extraction

- The function SHALL locate the **first** `major.minor[.patch]` core in `text`, case-insensitive.
- WHEN the token has a leading `v`/`V` THEN it SHALL be stripped before parsing.
- WHEN the patch component is absent (`"1.4"`, `"v9.10"`) THEN the patch SHALL default to `0`.
- WHEN a pre-release or build suffix follows the core (`-rc2`, `+build.42`) THEN the suffix SHALL
  be ignored and only the `major.minor.patch` core returned.
- WHEN the token is embedded inside surrounding prose (e.g. a commit subject) THEN the function
  SHALL still extract it, taking the first token when more than one appears.
- WHEN no version-looking token is present (including an empty or whitespace-only string) THEN
  the function SHALL return `None`.

### `parse_semver` — output shape

- On success the function SHALL return a 3-tuple of non-negative `int` values
  `(major, minor, patch)`.
- The function SHALL NOT mutate its input string.

### `bump_level` — input guard

- `bump_level(old, new)` SHALL accept two semver tuples in `(major, minor, patch)` shape.
- WHEN either argument is not a `tuple` THEN the function SHALL return `None` (not raise).
- WHEN either tuple has fewer than three elements, including the empty tuple `()`, THEN the
  function SHALL return `None`.

### `bump_level` — forward bump only

- WHEN `new` is not strictly greater than `old` under tuple ordering — including `new == old` and
  any `new < old` case — THEN the function SHALL return `None`.
- Only a strictly forward bump proceeds to classification.

### `bump_level` — classification

- WHEN `new[0] != old[0]` THEN the function SHALL return `"major"`.
- WHEN `new[0] == old[0]` and `new[1] != old[1]` THEN the function SHALL return `"minor"`.
- WHEN only `new[2] != old[2]` (major and minor unchanged) THEN the function SHALL return
  `"patch"`.
- A patch component of `0` on either side SHALL be treated as a legitimate value, not as a missing
  one.
- Every non-`None` return value SHALL be a member of `_BUMP_LEVELS`.

### Pure evaluation

- Both functions SHALL perform no I/O and SHALL NOT read or write mutable global state — calling
  either twice with the same arguments SHALL return equal results.

## Out of scope

- `_semver_from_release_subject` and `is_release_subject` disambiguation when a subject contains
  more than one plausible release version — separate release-subject territory.
- `bump_actual`/`kind_recall` aggregation that consumes these helpers —
  [`specs/002-scoring-anchor`](../002-scoring-anchor/spec.md).
- Changing parse or classification semantics — behavior changes follow the SDD loop in their own
  PR, not this docs-only characterization.

## Verification

- `tests/test_spec_023_semver_parse.py` (this PR) exercises each EARS block above.
- Broader anchor coverage remains in `tests/test_score.py`.
