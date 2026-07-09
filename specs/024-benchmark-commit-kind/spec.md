# Spec 024 — maintainer kind normalization (`commit_kind`, `plan_kind`)

- **Status:** draft (SDD Phase 1 — Specify)
- **Owner:** benchmark
- **Issue:** #855
- **Constitution:** [`AGENTS.md`](../../AGENTS.md) → *Benchmark integrity (M1–M3)*
- **Methodology:** [`blog/spec-driven-development.md`](../../blog/spec-driven-development.md)
- **Related:** [`specs/002-scoring-anchor`](../002-scoring-anchor/spec.md) (`kind_recall` consumes these helpers)

This spec makes the **existing, implicit** maintainer-kind normalization contract explicit. It
describes the as-built behavior of `benchmark/score.py::commit_kind` and `plan_kind`; it
introduces **no behavior change**. `kind_recall` keys off symmetric plan/commit vocabulary — those
mapping rules must be written down and verified.

## Why

Plan items carry a `kind` field and revealed commits carry subjects. `commit_kind` and `plan_kind`
normalize both into the same vocabulary so `kind_recall` can score anticipation deterministically.
An LLM may emit non-string kinds or unconventional subjects; the guards must be explicit.

## User stories

1. **As an agent developer**, I know which plan `kind` values map to commit kinds — so I
   anticipate maintainer work with the right vocabulary.
2. **As a reviewer**, release-cut handling and malformed-input guards are written down — so
   kind-scoring changes are checked against the spec.

## Constants

- `COMMIT_KINDS` — the normalized maintainer kinds `commit_kind` may return (excluding `None`):
  `feat`, `fix`, `docs`, `refactor`, `perf`, `test`, `build`, `ci`, `chore`, `style`, `revert`,
  `release`.
- `UNMAPPED_PLAN_KINDS` — plan kinds that deliberately map to no commit kind: `triage` (and any
  unknown string).

## Acceptance criteria (EARS)

### `commit_kind` — input guard

- `commit_kind(subject)` SHALL accept a commit subject string.
- WHEN `subject` is not a `str` THEN the function SHALL return `None` (not raise).

### `commit_kind` — conventional-commit prefix

- WHEN `subject` has a Conventional-Commit prefix (`type:`, `type(scope):`, `type!:`) THEN the
  function SHALL map the type (case-insensitive) to a normalized kind.
- Common synonyms SHALL normalize identically (`feature` → `feat`, `bugfix`/`bug` → `fix`,
  `doc`/`docs` → `docs`, `tests` → `test`, `dep`/`deps` → `chore`).

### `commit_kind` — release subjects

- WHEN `subject` is a genuine release/version-cut subject per `is_release_subject` THEN the
  function SHALL return `"release"`, including version cuts authored under `chore`/`build` types
  (`chore(release): 1.4.0`).
- WHEN a non-release CC prefix is present but the subject is still a release cut THEN the
  function SHALL return `"release"` (not the literal CC type).

### `commit_kind` — unclassified subjects

- WHEN `subject` has no CC prefix and is not a release subject THEN the function SHALL return
  `None` (e.g. merge commits, prefix-less subjects).
- WHEN `subject` is empty THEN the function SHALL return `None`.

### `plan_kind` — input guard

- `plan_kind(kind)` SHALL accept a plan item `kind` field value.
- WHEN `kind` is not a `str` THEN the function SHALL return `None` (not raise).

### `plan_kind` — normalization

- WHEN `kind` is a string THEN surrounding whitespace SHALL be stripped and matching SHALL be
  case-insensitive.

### `plan_kind` — vocabulary mapping

- WHEN `kind` matches a known plan alias THEN the function SHALL return the corresponding
  normalized commit kind (same vocabulary as `commit_kind`).
- WHEN `kind` is `triage` or any unknown string THEN the function SHALL return `None`.
- WHEN `kind` is empty after stripping THEN the function SHALL return `None`.

### Vocabulary symmetry

- For every plan alias in the mapping (except `triage`), `plan_kind(alias)` SHALL equal the
  normalized kind that `commit_kind` returns for a subject with the matching CC prefix.

### Pure evaluation

- Both functions SHALL perform no I/O and SHALL NOT depend on mutable global state.

## Out of scope

- `kind_recall` aggregation and scalar blending — [`specs/002-scoring-anchor`](../002-scoring-anchor/spec.md).
- `is_release_subject` disambiguation rules in full — referenced only where `commit_kind` delegates.
- Changing vocabulary mappings — code changes follow the SDD loop in their own PRs.

## Verification

- `tests/test_spec_024_commit_kind.py` (this PR) exercises each EARS block above.
- Broader anchor coverage remains in `tests/test_score.py`.
