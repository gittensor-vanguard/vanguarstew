# Spec 050 — margin outlook summary

- **Status:** draft (SDD Phase 1 — Specify)
- **Owner:** benchmark
- **Issue:** #1152
- **Constitution:** [`AGENTS.md`](../../AGENTS.md) → *Benchmark integrity (M1–M3)*
- **Methodology:** [`blog/spec-driven-development.md`](../../blog/spec-driven-development.md)
- **Related:** [`benchmark/promotion.py`](../../benchmark/promotion.py) (decisive-margin gate),
  [`benchmark/composite_spread.py`](../../benchmark/composite_spread.py) (judge vs objective spread),
  [`benchmark/comparability.py`](../../benchmark/comparability.py) (artifact kind classification)

This spec makes the **existing, implicit** margin-outlook contract explicit. It describes the
as-built behavior of `benchmark/margin_outlook.py`; it introduces **no behavior change**.

## Why

`promotion` gates on `decisive_margin`, but nothing exposes a compact read-only summary for CI
dashboards. `summarize_margin_outlook` reports the margin and whether the challenger is ahead,
tied, or behind the baseline.

## User stories

1. **As a benchmark operator**, I can read decisive margin and outlook from a replay artifact.
2. **As a CI maintainer**, I can log a stable `margin_outlook_headline()` string alongside the JSON
   summary.
3. **As a reviewer**, malformed-input handling and every headline branch are written down.

## Acceptance criteria (EARS)

### Input coercion

- WHEN the replay `artifact` is not a `dict` THEN `summarize_margin_outlook(artifact)` SHALL treat
  it as `{}` and evaluate (not raise).
- `_dict(value)` SHALL return `value` when it is a `dict`, otherwise `{}`.

### Whole-number count semantics (`_is_int`)

- Only built-in `int` values SHALL count as whole-number counts.
- `bool` SHALL NOT be treated as an integer.
- `float` values SHALL NOT be treated as integers.

### Tally margin (`_margin_from_tally`)

- SHALL read `challenger` and `baseline` from a tally dict.
- WHEN both counts pass `_is_int` THEN `_margin_from_tally` SHALL return `challenger - baseline`.
- OTHERWISE it SHALL return `None`.

### Margin resolution (`_margin`)

Resolution order SHALL be:

1. Top-level `decisive_margin` when it passes `_is_int`.
2. `_margin_from_tally(tally)` when `tally` is a `dict`.
3. `judge_report.wins - judge_report.losses` when both pass `_is_int`.
4. OTHERWISE `None`.

### Outlook (`_outlook`)

- WHEN `margin` is not a `_is_int` THEN `_outlook` SHALL return `None`.
- WHEN `margin > 0` THEN `_outlook` SHALL return `"ahead"`.
- WHEN `margin < 0` THEN `_outlook` SHALL return `"behind"`.
- WHEN `margin == 0` THEN `_outlook` SHALL return `"tied"`.

### Margin outlook summary (`summarize_margin_outlook`)

Every summary SHALL include: `kind`, `decisive_margin`, `outlook`.

- `kind` SHALL come from `artifact_kind(artifact)`.
- `decisive_margin` and `outlook` SHALL be derived from `_margin` and `_outlook`.

### Margin outlook headline

- WHEN `decisive_margin` is missing or not a `_is_int`, or `outlook` is `None` THEN the headline
  SHALL be exactly: `margin outlook: unavailable`.
- OTHERWISE the headline SHALL be:
  `margin outlook: {outlook} (decisive_margin {margin})`.

### Pure evaluation

- The module SHALL perform no I/O.
- `summarize_margin_outlook()` SHALL NOT mutate its input dict.

## Verification

- `tests/test_spec_050_margin_outlook.py` exercises each EARS block above.
- Broader coverage remains in `tests/test_margin_outlook.py`.
