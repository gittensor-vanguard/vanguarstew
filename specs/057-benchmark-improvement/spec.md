# Spec 057 — improvement (candidate-over-baseline adoption) gate

- **Status:** draft (SDD Phase 1 — Specify)
- **Owner:** benchmark
- **Issue:** #647
- **Constitution:** [`AGENTS.md`](../../AGENTS.md) → *Benchmark integrity (M1–M3)*
- **Methodology:** [`blog/spec-driven-development.md`](../../blog/spec-driven-development.md)
- **Related:** [`benchmark/regression.py`](../../benchmark/regression.py) (blocks a drop below baseline),
  [`benchmark/promotion.py`](../../benchmark/promotion.py) (decisive-win + quality promotion gate),
  [`benchmark/trend.py`](../../benchmark/trend.py) (`headline_score` extraction),
  [`scripts/improvement.py`](../../scripts/improvement.py) (CLI exit code for CI)

This spec makes the **existing, implicit** improvement-gate contract explicit. It describes the
as-built behavior of `benchmark/improvement.py`; it introduces **no behavior change**.

## Why

`regression` blocks a candidate that *drops* below a baseline. The opposite adoption decision —
**should this run become the new current-best?** — needs an explicit gate: only accept a candidate
when its headline composite improves by at least a configurable margin over the baseline. A
candidate that merely matches the baseline (or edges it by rounding noise) is not worth adopting.

## User stories

1. **As a benchmark operator**, I can compare two `run_eval --out` artifacts and see whether the
   candidate improved enough to adopt.
2. **As a CI maintainer**, I can run `scripts/improvement.py --strict` and gate on a minimum gain.
3. **As a reviewer**, malformed-input handling, generalization partition semantics, and every
   headline branch are written down.

## Acceptance criteria (EARS)

### Input coercion

- `_dict(value)` SHALL return `value` when it is a `dict`, otherwise `{}`.
- `_is_number(value)` SHALL be true only for non-boolean `int`/`float` values.
- Non-dict `candidate` or `baseline` artifacts SHALL be coerced via `_dict` before score
  extraction; they SHALL NOT raise.

### Headline score extraction (`headline_score`)

`check_improvement` SHALL extract composites via `benchmark.trend.headline_score` for both inputs:

- Single-repo / multi-repo artifacts: top-level `composite_mean`.
- `--generalization` artifacts (both `tuned` and `held_out` are dicts): `tuned.composite_mean`.
- Unscored aggregate placeholders (`scored_repos == 0` with placeholder `0.0`): `None`.
- Missing or non-numeric composites: `None`.

### Improvement gate (`check_improvement`)

Every result SHALL include: `passed`, `checks`, `baseline_composite`, `candidate_composite`, `gain`,
`min_gain`.

All checks SHALL be reported; each fails closed; `passed` is true only when every check passes.

1. **`both_scored`** — both baseline and candidate headline composites are non-`None`.
2. **`improves_by_margin`** — WHEN both are scored THEN `gain = round(candidate - baseline, 3)` and
   the check passes iff `gain >= min_gain` (inclusive bound); WHEN either composite is missing
   THEN `gain` is `None` and the check fails with a cannot-compare detail.

`DEFAULT_MIN_GAIN` SHALL be `0.02`.

### Failed checks (`failed_checks`)

- Malformed `result` containers SHALL be coerced via `_dict`.
- `failed_checks` SHALL use `_check_rows_list` on `result["checks"]` and return names of rows whose
  `passed` is false.
- A non-list `checks` container SHALL be warned and treated as empty (never raise).

### Check-row sanitization (`_check_rows_list`)

- `None` (absent key) and `[]` SHALL yield `[]` silently.
- A non-list container SHALL log a warning and yield `[]`.
- A usable row SHALL be a `dict` with `str` `name` and `bool` `passed` (both keys present).
- Non-dict rows, missing keys, non-str `name`, and non-bool `passed` SHALL be skipped with a
  warning.
- WHEN every row in a non-empty list is unusable THEN a summary warning SHALL be logged.

### Improvement headline (`improvement_headline`)

- WHEN `checks` is missing, empty, a non-list container, or contains only unusable rows THEN the
  headline SHALL be exactly: `improvement: no checks evaluated`.
- WHEN `passed` is true THEN the headline SHALL be:
  `improvement: ADOPT (composite {baseline} -> {candidate}, gain {gain})` with three-decimal
  formatting via `_num` (or `n/a` when a field is missing).
- OTHERWISE the headline SHALL be:
  `improvement: HOLD ({n_failed}/{n_checks} checks failed: {names})`.

The headline SHALL never contain a bare `None` string for a missing score.

### Pure evaluation

- The module SHALL perform no I/O.
- `check_improvement()` SHALL NOT mutate its `candidate` or `baseline` inputs.

## Verification

- `tests/test_spec_057_improvement.py` exercises each EARS block above.
- Broader coverage remains in `tests/test_improvement.py`.
