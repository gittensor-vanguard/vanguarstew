# Spec 012 — benchmark trend headline score

- **Status:** draft (SDD Phase 1 — Specify)
- **Owner:** benchmark
- **Issue:** #761
- **Constitution:** [`AGENTS.md`](../../AGENTS.md) → *Benchmark integrity (M1–M3)*
- **Methodology:** [`blog/spec-driven-development.md`](../../blog/spec-driven-development.md)
- **Related:** [`specs/002-scoring-anchor`](../002-scoring-anchor/spec.md) (composite scores this reads)

This spec makes the **existing, implicit** `headline_score` contract explicit. It describes the
as-built behavior of `benchmark/trend.py::headline_score`; it introduces **no behavior change**.
The headline is the single comparable number used by trend, regression, repeatability, and CI
gates — its rules must be written down so unscored placeholders never masquerade as real scores.

## Why

Several benchmark gates compare artifacts via one headline composite. A multi-repo run that scored
nothing reports a placeholder `composite_mean: 0.0`; treating that as a real zero would falsely
trigger regressions and block healthy runs. The extraction rules therefore fail closed on missing
or placeholder scores, and that contract must be reviewable.

## User stories

1. **As the validator**, I extract one comparable score from any saved replay artifact — so
   trend/regression/repeatability gates agree on the number.
2. **As a reviewer**, unscored and generalization partitions are handled consistently — so a
   placeholder never passes as a measured score.
3. **As a maintainer**, changes to `headline_score` are checked against this contract at the SDD
   phase boundary — so the headline rules cannot erode silently.

## Acceptance criteria (EARS)

### Input tolerance

- `headline_score(artifact)` SHALL return `None` when `artifact` is not a `dict`.
- WHEN `composite_mean` is missing or not a finite number THEN the function SHALL return `None`.

### Single-repo and multi-repo artifacts

- WHEN the artifact exposes a numeric top-level `composite_mean` AND is not an unscored aggregate
  (below) THEN the function SHALL return that value rounded to three decimal places.
- WHEN `scored_repos` is a number equal to `0` on the score source THEN the function SHALL return
  `None` (the `composite_mean` is a placeholder, not a real measurement).

### Generalization artifacts

- WHEN the artifact carries both `tuned` and `held_out` dict partitions THEN the headline SHALL be
  read from the **tuned** partition (not `held_out`, not the top level).
- The unscored-placeholder rule (`scored_repos: 0` → `None`) SHALL apply to the tuned partition
  the same way it applies to a multi-repo artifact.

### Pure analysis

- The function SHALL perform no I/O and SHALL NOT mutate its input.

## Out of scope

- The N-way `trend()` summary, regression detection, and `trend_headline` formatting — only the
  per-artifact score extraction is specified here.
- How `composite_mean` is computed inside `run_replay` / `run_multi_replay`.

## Verification

Ships `tests/test_spec_012_headline.py`, asserting each EARS criterion against
`benchmark.trend.headline_score`. Broader trend behavior remains in `tests/test_trend.py`. The
spec changes no product code.
