# Spec 068 — improvement (adoption) gate

- **Status:** draft (SDD Phase 1 — Specify)
- **Owner:** benchmark
- **Issue:** #1900
- **Constitution:** [`AGENTS.md`](../../AGENTS.md) → *Benchmark integrity (M1–M3)*
- **Methodology:** [`blog/spec-driven-development.md`](../../blog/spec-driven-development.md)
- **Related:** [`benchmark/improvement.py`](../../benchmark/improvement.py) (the gate under test),
  [`benchmark/regression.py`](../../benchmark/regression.py) (the opposite gate — blocks a *drop*),
  [`benchmark/trend.py`](../../benchmark/trend.py) (`headline_score`),
  [`benchmark/acceptance.py`](../../benchmark/acceptance.py) (`_partition_error`),
  [`scripts/improvement.py`](../../scripts/improvement.py) (the CI entry point)

This spec makes the **existing, implicit** improvement contract explicit. It describes the as-built
behavior of `benchmark/improvement.py`; it introduces **no behavior change**.

## Why

`regression` blocks a candidate that *drops* below a baseline; `improvement` is the opposite gate — a
promotion/adoption decision: only accept a new run as the current best if it **improves** the
headline composite by at least a margin. A candidate that merely matches the baseline (or edges it
by rounding noise) isn't worth adopting; one that improves clearly is. The contract is currently
implicit; this writes it down.

## User stories

1. **As a CI maintainer**, I can gate adoption on `scripts/improvement.py` and log a stable
   `improvement_headline()` ADOPT/HOLD line.
2. **As a benchmark operator**, I can trust that ADOPT means both artifacts were fully scored (no
   top-level or per-repo error) and the candidate beat the baseline by at least `min_gain`.
3. **As a reviewer**, every error, missing-score, malformed-input and headline branch is written
   down (addressing the incompleteness class of rejection seen on Specs 057/059).

## Constants

- `DEFAULT_MIN_GAIN` SHALL be `0.02`.
- `_CHECK_ROW_KEYS` SHALL be `("name", "passed")`.

## Acceptance criteria (EARS)

### Helpers

- `_is_number(value)` SHALL be true only for a non-boolean, finite `int`/`float`; a `NaN`/`inf`
  SHALL be false, and an oversized `int` (`math.isfinite` raising `OverflowError`) SHALL be false.
- `_dict(value)` SHALL return `value` when it is a `dict`, otherwise `{}`.
- `_num(value)` SHALL be `f"{value:.3f}"` when `_is_number(value)`, otherwise `"n/a"`.
- `_headline_source(artifact)` SHALL return the `tuned` partition when both `tuned` and `held_out`
  are dicts, otherwise the artifact itself (a lone `tuned` dict without `held_out` is NOT treated as
  generalization).
- `_artifact_error(artifact)` SHALL return the artifact's truthy top-level `error`, else the first
  `_partition_error` of its `_headline_source` (a per-repo clone/freeze failure), else `None`.

### Gate (`check_improvement`)

- `base_score` / `cand_score` SHALL be `benchmark.trend.headline_score(baseline)` /
  `headline_score(candidate)`; `base_err` / `cand_err` SHALL be their `_artifact_error`.
- `both_scored` SHALL be true only when both scores are non-`None` AND both errors are `None`.
- `gain` SHALL be `round(cand_score - base_score, 3)` when `both_scored`, otherwise `None`.
- The result SHALL always carry `passed`, `checks`, `baseline_composite`, `candidate_composite`,
  `gain`, `min_gain`; `passed` SHALL be `all(c["passed"] for c in checks)`.
- Two checks SHALL be added in order: `both_scored`, `improves_by_margin`.
- `both_scored` detail SHALL be, in priority order:
  `"baseline composite {base}, candidate composite {cand}"` when `both_scored`; else
  `"baseline error: {base_err!r}"` when a baseline error exists; else
  `"candidate error: {cand_err!r}"` when a candidate error exists; else
  `"a composite score is missing from one artifact"`.
- `improves_by_margin` SHALL pass only when `gain is not None and gain >= min_gain`; its detail
  SHALL be `"gain {gain} >= {min_gain}"` when `gain is not None`, else `"cannot compare composites"`.

### Checks-row sanitation (`_check_rows_list`)

- `None` / non-list `checks` SHALL yield `[]` (with a warning for the non-list case).
- A row SHALL be skipped (with a warning) when it is not a dict, is missing `name`/`passed`, has a
  non-`str` `name`, or a non-`bool` `passed`.
- WHEN `checks` is non-empty but no row survives THEN a warning SHALL be logged.

### Failed checks and headline

- `failed_checks(result)` SHALL return the `name` of every sanitized check whose `passed` is falsy.
- WHEN no sanitized checks exist THEN `improvement_headline` SHALL be exactly
  `improvement: no checks evaluated`.
- WHEN `result.passed` is truthy THEN it SHALL be
  `improvement: ADOPT (composite {baseline} -> {candidate}, gain {gain})` (each rendered with
  `_num`).
- OTHERWISE it SHALL be `improvement: HOLD ({f}/{n} checks failed: {names})`.

### Pure evaluation

- The module SHALL perform no I/O.
- `check_improvement()` SHALL NOT mutate its inputs.

## Out of scope

- The regression gate (`regression`) and the score/quality gates (`acceptance`, `promotion`).
- `headline_score` (Spec — `trend`) semantics.

## Verification

- `tests/test_spec_068_improvement.py` exercises each EARS block above, pinning **literal**
  expected check names, `passed` values and detail strings.
- Broader coverage (including the CLI) remains in `tests/test_improvement.py`.
