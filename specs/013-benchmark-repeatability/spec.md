# Spec 013 — repeatability assessment

- **Status:** draft (SDD Phase 1 — Specify)
- **Owner:** benchmark
- **Issue:** #762
- **Constitution:** [`AGENTS.md`](../../AGENTS.md) → *Benchmark integrity (M1–M3)*
- **Methodology:** [`blog/spec-driven-development.md`](../../blog/spec-driven-development.md)
- **Related:** [`benchmark/trend.py`](../../benchmark/trend.py) (`headline_score`, score over *successive* runs),
  [`scripts/repeatability.py`](../../scripts/repeatability.py) (CLI gate)

This spec makes the **existing, implicit** repeatability contract explicit. It describes the
as-built behavior of `benchmark/repeatability.py`; it introduces **no behavior change**.

## Why

`trend` tracks a score across *successive* runs to catch regressions; `assess_repeatability`
measures the spread of *repeated* runs of the same config to decide whether a single benchmark
number can be trusted (ROADMAP M1 acceptance: "re-runs are stable"). The stability verdict feeds
CI gating via `scripts/repeatability.py`, so its exact semantics belong on the record.

## User stories

1. **As a benchmark operator**, I can quantify run-to-run spread (mean, stddev, CV) of repeated runs.
2. **As a CI maintainer**, I can gate on `assess_repeatability()["stable"]` with a stable headline.
3. **As a reviewer**, malformed-input handling, rounding, and every reason string are written down.

## Acceptance criteria (EARS)

### Input coercion

- `_repeatability_artifacts(value)` SHALL return `value` when it is a `list`.
- WHEN `value` is `None` THEN it SHALL return `[]` silently.
- WHEN `value` is any other non-list THEN it SHALL return `[]` after logging a warning naming the
  offending type (`"repeatability: artifacts is {type}, not a list; treating as empty"`).
- `_round(value)` SHALL return `round(float(value), 3)` for an `int`/`float` that is not a `bool`,
  otherwise `None`.

### Score extraction

- `assess_repeatability(artifacts, ...)` SHALL extract one score per artifact via
  `benchmark.trend.headline_score` (top-level `composite_mean`, or the `tuned` partition of a
  `--generalization` artifact).
- WHEN an artifact yields no usable score (`headline_score` returns `None`) THEN it SHALL be
  skipped — it contributes nothing and never raises.

### Repeatability assessment (`assess_repeatability`)

Every result SHALL include: `stable`, `runs`, `scores`, `mean`, `stddev`, `cv`, `min`, `max`,
`range`, `max_cv`, `min_runs`, `reason`. Defaults: `max_cv = 0.05`, `min_runs = 2`.

1. **Insufficient runs** — WHEN fewer than `min_runs` artifacts carry a usable score THEN the
   result SHALL have `stable` false, every statistic `None`, and `reason` exactly
   `insufficient runs: {runs} scored < min_runs {min_runs}`.
2. **Statistics** — `mean` SHALL be the arithmetic mean rounded to 3 decimal places; `stddev`
   SHALL be the **sample** (Bessel-corrected) standard deviation rounded to 3 decimal places
   (`0.0` for a single score); `min`/`max` SHALL be the extreme scores; `range` SHALL be
   `max - min` rounded to 3 decimal places.
3. **Coefficient of variation** — WHEN `stddev` is `0` THEN `cv` SHALL be `0.0` (identical runs
   are perfectly stable regardless of the mean); WHEN the mean is `0` but the spread is not THEN
   `cv` SHALL be `None` (it cannot be normalized); OTHERWISE `cv` SHALL be
   `stddev / |mean|` rounded to 3 decimal places.
4. **Stability verdict** — `stable` SHALL be true only when there are at least `min_runs` scored
   repeats and `cv` is a number at or below `max_cv` (the boundary is inclusive).
5. **Reason** — WHEN `cv` is `None` THEN `reason` SHALL be exactly
   `coefficient of variation undefined (zero mean with nonzero spread)`; WHEN `cv` exceeds
   `max_cv` THEN `reason` SHALL be exactly `cv {cv} exceeds max_cv {max_cv}`; WHEN stable THEN
   `reason` SHALL be the empty string.

### Repeatability headline

- WHEN the result is not a `dict`, or `runs` is missing/zero, THEN the headline SHALL be exactly:
  `repeatability: no scored runs`.
- WHEN `runs` is fewer than the result's `min_runs` (default `2` when absent) THEN the headline
  SHALL be: `repeatability: inconclusive ({runs} run(s))`.
- OTHERWISE the headline SHALL be:
  `repeatability: {STABLE|UNSTABLE} over {runs} runs (mean {mean}, cv {cv})`, where the verdict
  comes from `stable`, `cv` is formatted as a percentage with one decimal place when it is a
  number, and `n/a` otherwise.

### Pure evaluation

- The module SHALL perform no I/O.
- `assess_repeatability()` SHALL NOT mutate its input artifacts.

## Verification

- `tests/test_spec_013_repeatability.py` exercises each EARS block above.
- Broader coverage (CLI, realistic acceptance repeats) remains in `tests/test_repeatability.py`.
